# ATM Banking System

This is the backend for a bank's ATM network. Hundreds of physical terminals, one central server, real cash constraints. I built it at a fintech company and the spec came from an actual bank, so the edge cases are real — not hypothetical.

If you're setting this up for the first time, start at [Local Setup](#local-setup). If you're trying to understand why something works the way it does, the [Authentication Flow](#authentication-flow) and [Withdrawal Logic](#withdrawal-logic) sections explain the decisions.

---

## Why This Exists

Most ATM backends I've seen treat concurrency as someone else's problem. Two terminals hit the same account at once and you either get a race condition or a deadlock. A cassette runs dry and the system doesn't know until a customer gets an empty dispense. Sessions don't actually die — they just stop being checked.

This system treats those as first-class problems. The withdrawal endpoint holds a `SELECT FOR UPDATE` on the cassette row. Sessions expire at 90 seconds of inactivity and the check runs on every request, not in a background job. Card locks write to the database immediately and survive server restarts — which sounds obvious, but I've seen three production systems where the lock lived in Redis with a TTL.

---

## Table of Contents

- [Stack](#stack)
- [Local Setup](#local-setup)
- [Running with Docker](#running-with-docker)
- [Environment Variables](#environment-variables)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Authentication Flow](#authentication-flow)
- [Withdrawal Logic](#withdrawal-logic)
- [Deposits](#deposits)
- [Transfers](#transfers)
- [Fraud Detection](#fraud-detection)
- [Admin Panel](#admin-panel)
- [Tests](#tests)
- [Seeding Data](#seeding-data)
- [Creating an Admin](#creating-an-admin)

---

## Stack

Python 3.11 and FastAPI for the API layer. SQLAlchemy 2.x with declarative models, Pydantic v2 in strict mode for validation. JWTs via python-jose, PIN hashing via passlib (Argon2id by default, bcrypt as fallback). Alembic for migrations. structlog for logging — structured dicts only, no free-form strings. SlowAPI for rate limiting.

Tests run with pytest and httpx. Load testing uses Locust. Deployment is Docker + docker-compose.

SQLite works fine for local dev and test runs. PostgreSQL is what you want in production — the performance targets (p95 under 200ms on transaction endpoints) are measured against Postgres, not SQLite.

---

## Local Setup

You'll need Python 3.11+ and either PostgreSQL or SQLite.

```bash
git clone https://github.com/Git-punit/atm-banking-system.git
cd atm-banking-system

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# open .env and set SECRET_KEY, ADMIN_SECRET_KEY, and CARD_NUMBER_ENCRYPTION_KEY at minimum

alembic upgrade head

python scripts/seed_data.py
python scripts/create_admin.py

uvicorn app.main:app --reload
```

API runs at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs` — useful for manual testing before wiring up a frontend.

---

## Running with Docker

```bash
cp .env.example .env
# fill in the three required secrets

docker compose up --build
```

That's it. The compose file starts the API and PostgreSQL together. First run takes a minute for the image build. After that:

```bash
docker compose exec api python scripts/seed_data.py
docker compose exec api python scripts/create_admin.py
```

Docker files are under `docker/`. If you need to wipe and restart clean:

```bash
docker compose down -v
docker compose up --build
```

---

## Environment Variables

Three of these are required and have no defaults. The app won't start without them. The rest have sensible defaults you can leave alone for local dev.

```
# Required — no defaults
SECRET_KEY                   JWT signing secret for cardholder tokens
ADMIN_SECRET_KEY             JWT signing secret for admin tokens (separate from above)
CARD_NUMBER_ENCRYPTION_KEY   AES-256 key; card numbers are encrypted before they touch the DB

# App
APP_NAME                     default: "ATM Banking System"
APP_ENV                      development | production | testing

# Database
DATABASE_URL                 SQLAlchemy URL
                             postgresql+psycopg2://user:pass@localhost/atmdb
                             sqlite:///./dev.db works fine locally

# Auth / Sessions
ALGORITHM                    HS256
ACCESS_TOKEN_EXPIRE_MINUTES  default: 2  (JWT hard expiry)
SESSION_INACTIVITY_SECONDS   default: 90 (separate inactivity check)
MAX_PIN_ATTEMPTS             default: 3

# PIN Hashing
PIN_HASH_ALGORITHM           argon2 | bcrypt (default: argon2)
                             Argon2id with m=65536, t=3, p=4 — OWASP minimums

# Limits
DEFAULT_DENOMINATION         default: 20
DEFAULT_DAILY_WITHDRAWAL_LIMIT  default: 1000
MAX_SINGLE_WITHDRAWAL        default: 500
MAX_SINGLE_DEPOSIT           default: 10000
DEPOSIT_HOLD_DAYS            default: 1 — set to 0 to credit available_balance immediately

# ATM
LOW_CASH_THRESHOLD           default: 5000 — triggers low_cash_alert audit event

# Rate Limiting
RATE_LIMIT_PER_MINUTE        default: 60 globally; auth endpoints cap at 10

# Fraud
FRAUD_BLOCK_ON_CRITICAL      default: false
                             flip to true to auto-reject withdrawals that hit critical fraud rules

# Logging
LOG_LEVEL                    default: INFO
LOG_FORMAT                   json | console (default: console for local, json for prod)
```

---

## Database Schema

Eight tables. Migrations are in `migrations/versions/` — run `alembic upgrade head` before anything else.

### accounts

```
id                          UUID, PK
account_number              VARCHAR(20), UNIQUE, indexed
account_holder_name         VARCHAR(200)
account_type                savings | current | salary
available_balance           DECIMAL(15,2)  — spendable right now
total_balance               DECIMAL(15,2)  — includes held funds
daily_withdrawal_limit      DECIMAL(15,2)
daily_withdrawal_used       DECIMAL(15,2), default 0.0
daily_withdrawal_reset_date DATE           — resets at midnight, not rolling 24h
daily_transfer_limit        DECIMAL(15,2)
daily_transfer_used         DECIMAL(15,2), default 0.0
daily_transfer_reset_date   DATE
account_status              active | frozen | closed | dormant
kyc_verification_status     pending | verified | rejected
is_joint_account            BOOLEAN, default false
low_balance_threshold       DECIMAL(15,2), nullable
branch_code                 VARCHAR(20)
currency                    CHAR(3), default 'USD'
notes                       TEXT, nullable
created_at / updated_at     TIMESTAMPTZ
```

`available_balance` and `total_balance` are separate columns. They diverge during deposit holds and they need to stay separate — collapsing them into one field is a common mistake that requires a painful migration to undo later.

Daily limit resets are inline. When a withdrawal request comes in, check `daily_withdrawal_reset_date`. If it's before today, zero out `daily_withdrawal_used` and update the date in the same transaction. No scheduler needed.

### cards

```
id                   UUID, PK
card_number          VARCHAR(16), UNIQUE  — AES-256 encrypted at rest
linked_account_id    FK → accounts.id
card_status          active | blocked | expired | lost_stolen
expiry_date          DATE
pin_hash             VARCHAR(255)
failed_attempt_count INT, default 0
last_used_timestamp  TIMESTAMPTZ, nullable
lost_or_stolen_flag  BOOLEAN, default false
issued_at / created_at / updated_at  TIMESTAMPTZ
```

### sessions

```
id           UUID, PK
jti          VARCHAR(36), UNIQUE  — matches the JWT jti claim 1:1
card_id      FK → cards.id
account_id   FK → accounts.id
atm_id       FK → atm_terminals.id
is_active    BOOLEAN
started_at   TIMESTAMPTZ
last_active  TIMESTAMPTZ
ended_at     TIMESTAMPTZ, nullable
```

`jti` is what lets us invalidate tokens server-side. Every authenticated request does one indexed lookup on this column. It needs to be fast — session validation should add less than 5ms per request.

### atm_terminals

```
id                       UUID, PK
atm_code                 VARCHAR(20), UNIQUE
branch_code              VARCHAR(20)
physical_address         TEXT
terminal_status          online | offline | maintenance | out_of_cash
total_cash_available     DECIMAL(15,2)
daily_transaction_count  INT, default 0
daily_transaction_volume DECIMAL(15,2), default 0.0
last_serviced_at         TIMESTAMPTZ, nullable
backend_endpoint         VARCHAR(255), nullable
created_at / updated_at  TIMESTAMPTZ
```

### cash_cassettes

```
id           UUID, PK
atm_id       FK → atm_terminals.id
denomination INT    — 20 = $20 notes
note_count   INT
updated_at   TIMESTAMPTZ
```

Each ATM can have multiple cassettes for different denominations. The withdrawal logic locks the relevant cassette row before touching it.

### transactions

```
id                  UUID, PK
reference_id        VARCHAR(36), UNIQUE
group_reference_id  VARCHAR(36), nullable  — links both legs of a transfer
account_id          FK → accounts.id
atm_id              FK → atm_terminals.id, nullable
transaction_type    withdrawal | deposit | transfer_debit | transfer_credit
amount              DECIMAL(15,2)  — negative for debits, positive for credits
balance_after       DECIMAL(15,2)  — snapshot of available_balance after this row
description         TEXT, nullable
status              completed | failed | pending | reversed
created_at          TIMESTAMPTZ
```

Composite index on `(account_id, created_at DESC)` for history queries. Transaction history pagination uses DB-level `LIMIT`/`OFFSET` — not pulling everything into Python and slicing.

### audit_logs

```
id                  UUID, PK
event_type          VARCHAR(100)
atm_id              FK → atm_terminals.id, nullable
masked_account_ref  VARCHAR(50)   — last 4 digits, e.g. "****1234"
masked_card_ref     VARCHAR(50), nullable
description         TEXT
severity            info | warning | critical
ip_address          VARCHAR(45), nullable
metadata            JSON, nullable
created_at          TIMESTAMPTZ   — no updated_at; this table is append-only
```

No `UPDATE` or `DELETE` ever runs on this table. The application code makes that impossible to do accidentally — not just by convention, but structurally.

### admin_users

```
id             UUID, PK
username       VARCHAR(100), UNIQUE
password_hash  VARCHAR(255)
role           superadmin | admin | auditor
is_active      BOOLEAN, default true
created_at / updated_at  TIMESTAMPTZ
```

---

## API Endpoints

### Cardholder

```
POST   /auth/login
POST   /auth/logout

GET    /account/balance

POST   /transaction/withdraw
POST   /transaction/deposit
POST   /transaction/transfer
GET    /transaction/history      paginated; filter by date range and type
GET    /transaction/statement    last 10 transactions, newest first

GET    /atm/{atm_id}/status
GET    /health
```

`/health` and `/auth/login` don't require a token. Everything else does — `Authorization: Bearer <token>` header.

### Admin

```
POST   /admin/auth/login
POST   /admin/accounts/create
PUT    /admin/accounts/{id}/freeze
PUT    /admin/accounts/{id}/unfreeze
GET    /admin/accounts                  search by name, account number, or status
POST   /admin/cards/block
POST   /admin/cards/unblock
PUT    /admin/atm/{id}/refill
GET    /admin/reports/transactions      date range + type filter; export as JSON or CSV
GET    /admin/reports/failed-logins     failed PIN attempts by card and date
GET    /admin/reports/suspicious        audit rows where severity = critical
POST   /admin/users/create             superadmin only
```

Every response is a JSON object. Success responses have a `data` key. Errors always have `error_code`, `message`, and `http_status` — never a raw string or a 200 wrapping a failure.

---

## Authentication Flow

These steps run in this order every time a card is presented. Don't change the sequence.

1. Luhn check on the card number. Fails? Stop here — no DB query.
2. ATM lookup. Terminal isn't `online`? Return `ATM_OFFLINE`.
3. Card lookup. Not found? Generic error — don't reveal whether the card or PIN was the problem.
4. Check `lost_or_stolen_flag`, `card_status`, `expiry_date`. Each has its own error code.
5. `failed_attempt_count >= 3`? The card is locked. Return `ACCOUNT_LOCKED`. The user calls the bank.
6. PIN check. Wrong? Increment the counter and commit that write before returning `INVALID_PIN`. If the count just hit 3, set `card_status = 'blocked'` in the same commit — not after.
7. Active session check. Session still alive? Return `CONCURRENT_SESSION`. Session stale (over 90 seconds since last activity)? Close it, continue.
8. Reset `failed_attempt_count = 0`, update `last_used_timestamp`, create the session row, sign the JWT. Return it.

JWT hard expiry is 2 minutes. Inactivity timeout is 90 seconds. These are two separate checks on every request — they're not the same thing.

On every authenticated request the session check works like this: decode JWT and verify signature, look up the `jti` in the sessions table, check that `last_active + 90s > now`. If the session is still alive, update `last_active` and continue. If it's stale, flip `is_active = false` and return `SESSION_EXPIRED`.

---

## Withdrawal Logic

Check order matters here. The first failure stops everything. Nothing writes to the database until all eight checks pass.

1. `atm.terminal_status == 'online'` — `ATM_OFFLINE` (503) otherwise
2. `atm.total_cash_available > 0` — `ATM_OUT_OF_CASH` (503) otherwise
3. `account.account_status == 'active'` — `ACCOUNT_FROZEN` (403) otherwise
4. Amount divisible by denomination — `INVALID_DENOMINATION` (400) otherwise
5. Amount within per-transaction cap — `TRANSACTION_LIMIT_EXCEEDED` (422) otherwise
6. Amount within remaining daily limit — `DAILY_LIMIT_EXCEEDED` (422) otherwise
7. `account.available_balance >= amount` — `INSUFFICIENT_FUNDS` (422) otherwise
8. `SELECT ... FOR UPDATE` on the cassette row, verify note count — `INSUFFICIENT_ATM_CASH` (503) otherwise

After that, fraud checks run. Non-blocking by default. If they pass, everything commits in one transaction:

```
account.available_balance    -= amount
account.total_balance        -= amount
account.daily_withdrawal_used += amount
cassette.note_count          -= int(amount / denomination)
atm.total_cash_available     -= amount
atm.daily_transaction_count  += 1
atm.daily_transaction_volume += amount
+ one transactions row (type: withdrawal)
+ one audit_logs row (event: withdrawal_success)
```

After committing, if `total_cash_available` dropped below `LOW_CASH_THRESHOLD`, write a `low_cash_alert` audit event. If it's now zero, set `terminal_status = 'out_of_cash'`.

---

## Deposits

Simpler than withdrawal. Reject amounts <= 0 (`INVALID_AMOUNT`), amounts above the configured ceiling (`TRANSACTION_LIMIT_EXCEEDED`), and inactive accounts (`ACCOUNT_FROZEN`).

If `DEPOSIT_HOLD_DAYS` is greater than zero: `total_balance` increases immediately, `available_balance` stays put until the hold releases. The hold release date goes in the transaction description — that's the human-readable record of when the funds will clear.

If `DEPOSIT_HOLD_DAYS` is zero, both balances go up at once.

Either way, update the cassette note count, update ATM totals, write the transaction row and audit entry.

---

## Transfers

Validate first: source account is `active`, destination exists and is `active`, they're not the same account, amount fits within the remaining daily transfer limit, source has enough available balance.

Then two-phase processing:

```python
# Phase 1 — debit source
pre_debit_available = source.available_balance
pre_debit_total     = source.total_balance

source.available_balance   -= amount
source.total_balance       -= amount
source.daily_transfer_used += amount

# Phase 2 — credit destination
try:
    dest.available_balance += amount
    dest.total_balance     += amount
except Exception:
    # Credit failed. Put source back exactly as it was.
    # Leaving a debit with no matching credit means money vanished.
    source.available_balance   = pre_debit_available
    source.total_balance       = pre_debit_total
    source.daily_transfer_used -= amount
    raise TransferRollbackError("credit failed, debit reversed")
```

Two transaction rows, same `group_reference_id`: `transfer_debit` on the source (negative amount), `transfer_credit` on the destination (positive). One audit entry covers both.

---

## Fraud Detection

Runs post-validation, pre-commit. Three rules:

**Velocity** — more than 5 withdrawals from the same account in 10 minutes. Severity: critical.

**Large withdrawal** — amount is 80% or more of the daily limit. Severity: warning.

**ATM hopping** — same card used at a different terminal in the last 5 minutes. Severity: critical.

By default, fraud hits log a warning and the transaction goes through. Set `FRAUD_BLOCK_ON_CRITICAL=true` to auto-reject on critical hits. Every fraud audit entry includes the masked account ref, masked card ref, ATM ID, amount, rule name, and severity.

---

## Admin Panel

Admins authenticate separately — different table, different JWT secret, 8-hour tokens.

| Action | superadmin | admin | auditor |
|---|---|---|---|
| Create admin user | yes | no | no |
| Freeze / unfreeze account | yes | yes | no |
| Block / unblock card | yes | yes | no |
| View reports | yes | yes | yes |
| Refill ATM cassette | yes | yes | no |

---

## Tests

```bash
pytest                        # everything
pytest tests/unit/            # unit only
pytest tests/integration/     # integration only
pytest --cov=app tests/       # with coverage
```

Tests check DB state, not just HTTP responses. A withdrawal test that doesn't verify the account balance actually changed in the database isn't a real test.

Scenarios the test suite covers:

Correct PIN login creates a session row and returns a JWT with `failed_attempt_count = 0`. Three wrong PINs set `failed_attempt_count = 3` and flip `card_status` to `blocked`. Then you restart the server and try to log in again — still blocked. That last part is the persistence test. It's what proves the lock isn't in memory.

Successful withdrawal reduces `available_balance`, reduces cassette `note_count`, and inserts one transaction row. Insufficient balance returns 422 with zero DB changes. Daily limit breach returns 422 without touching `daily_withdrawal_used`. Non-denomination amount returns 400 before any DB query past auth. Empty cassette returns 503.

Deposit with hold: `total_balance` increases, `available_balance` unchanged, hold date visible in the transaction description. Transfer where the credit leg throws: source balance is byte-for-byte identical to what it was before the request, `daily_transfer_used` not incremented. Stale session returns `SESSION_EXPIRED`. Auditor trying to freeze an account returns `INSUFFICIENT_PERMISSIONS`.

**Load test:**

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

100 concurrent users, all withdrawing $20 from the same account that starts at $500. After the run: balance is non-negative, sum of successful transaction amounts equals the balance drop exactly, no duplicate `reference_id` values, no deadlock errors in the logs.

---

## Seeding Data

```bash
python scripts/seed_data.py
```

Creates 3 ATMs, 5 accounts with linked cards, and some transaction history. It checks before inserting so you can run it more than once without duplicating data.

---

## Creating an Admin

```bash
python scripts/create_admin.py
```

Prompts for a username and password and creates a superadmin account. Run this once after migrations. To add more admin users with different roles, use `POST /admin/users/create` through the API once you have a valid superadmin token.

---

## A Few Things Worth Knowing

Card numbers are AES-256 encrypted before they touch the database. The encryption key comes from `CARD_NUMBER_ENCRYPTION_KEY`. Plaintext card numbers don't appear anywhere in the database — not in logs, not in error messages.

All logs use structlog with structured dicts. No free-form strings. Every log record includes `event`, `timestamp`, `atm_id` (when available), `masked_account_ref` (last 4 digits only), and `severity`. Full card numbers and PINs never appear in any log. The masking happens before the log is written, not after.

The `audit_logs` table is append-only. There's no code path that runs `UPDATE` or `DELETE` against it. That's not enforced by a database trigger — it's enforced by the application layer not having those operations on that model. If you ever see an update or delete query targeting `audit_logs` in a migration or a service, that's a mistake.