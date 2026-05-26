# ATM Banking System — Build Brief

I'm a tech lead at a fintech company. I need a complete, production-grade ATM Banking System backend built in Python. This document tells you exactly what to build, how it should behave, and what I expect at the end. Read it fully before writing a single line of code.

---

## The Problem

A bank has hundreds of physical ATM terminals. Each one needs to connect to a central backend to handle card logins, cash withdrawals, deposits, and fund transfers. Bank staff need a separate admin interface to manage accounts, block cards, monitor ATMs, and pull reports.

The core engineering challenges are concurrency and integrity. Two ATMs can hit the same account at the same time. A cassette holds a fixed number of notes and can't dispense more than what's physically there. Sessions must die after 90 seconds of user inactivity. A card locked after 3 wrong PINs must stay locked across server restarts — it's a database state, not a memory state.

Everything else is secondary to getting those four things right.

---

## Tech Stack

Use exactly this. Don't substitute anything.

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x (declarative models)
- Pydantic v2 (strict mode for all request validation)
- python-jose for JWTs
- passlib with Argon2id (bcrypt as fallback, controlled by env var)
- SQLite for dev/testing, PostgreSQL for production
- Alembic for migrations
- structlog for all logging
- SlowAPI for rate limiting
- pytest + httpx for tests
- Locust for load testing
- Docker + docker-compose for deployment

---

## Performance Targets

These are hard requirements, not suggestions:

- API response time under 200ms at the 95th percentile for all transaction endpoints (measured on a single machine with PostgreSQL, not SQLite)
- The withdrawal endpoint must handle 100 concurrent requests against the same account without any request seeing a negative balance or corrupted state
- Session token validation must add no more than 5ms overhead per request (one indexed DB lookup on `jti`)
- Transaction history pagination must use DB-level LIMIT/OFFSET — no pulling all rows into Python and slicing
- Daily limit resets must not require a cron job — check and reset inline when the request comes in

---

## Project Structure

```
atm-banking-system/
├── app/
│   ├── main.py               # app factory — registers middleware, routers, exception handlers
│   ├── config.py             # all settings come from env vars via pydantic-settings
│   ├── database.py           # engine, SessionLocal, Base
│   ├── dependencies.py       # FastAPI Depends for session auth, account lookup, admin auth
│   ├── core/
│   │   ├── exceptions.py     # every domain error is its own class
│   │   ├── security.py       # PIN hashing, JWT sign/verify, card number masking
│   │   ├── logging_config.py # structlog configuration
│   │   └── luhn.py           # Luhn algorithm
│   ├── models/               # one SQLAlchemy model file per table
│   ├── routers/              # FastAPI routers — thin, no business logic
│   ├── services/             # all business logic
│   ├── schemas/              # Pydantic request/response models
│   └── middleware/           # rate limiter
├── migrations/               # Alembic env + version scripts
├── tests/
│   ├── unit/
│   ├── integration/
│   └── load/                 # Locust scripts
├── scripts/
│   ├── seed_data.py          # creates sample ATMs, accounts, cards
│   └── create_admin.py       # creates a superadmin user
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .env.example
├── requirements.txt          # pinned versions
└── README.md
```

Routers do three things: parse the request, call a service, return the response. Business logic belongs in services, not routers. If a router function is more than ~20 lines, something is wrong.

---

## Database Schema

### accounts

```
id                          UUID, PK
account_number              VARCHAR(20), UNIQUE, indexed
account_holder_name         VARCHAR(200)
account_type                ENUM: savings | current | salary
available_balance           DECIMAL(15,2)   -- spendable right now
total_balance               DECIMAL(15,2)   -- includes held funds
daily_withdrawal_limit      DECIMAL(15,2)
daily_withdrawal_used       DECIMAL(15,2), default 0.0
daily_withdrawal_reset_date DATE            -- resets at midnight, not rolling 24h
daily_transfer_limit        DECIMAL(15,2)
daily_transfer_used         DECIMAL(15,2), default 0.0
daily_transfer_reset_date   DATE
account_status              ENUM: active | frozen | closed | dormant
kyc_verification_status     ENUM: pending | verified | rejected
is_joint_account            BOOLEAN, default false
low_balance_threshold       DECIMAL(15,2), nullable
branch_code                 VARCHAR(20)
currency                    CHAR(3), default 'USD'
notes                       TEXT, nullable
created_at                  TIMESTAMPTZ
updated_at                  TIMESTAMPTZ
```

### cards

```
id                   UUID, PK
card_number          VARCHAR(16), UNIQUE  -- AES-256 encrypted at rest
linked_account_id    FK → accounts.id
card_status          ENUM: active | blocked | expired | lost_stolen
expiry_date          DATE
pin_hash             VARCHAR(255)
failed_attempt_count INT, default 0
last_used_timestamp  TIMESTAMPTZ, nullable
lost_or_stolen_flag  BOOLEAN, default false
issued_at            TIMESTAMPTZ
created_at           TIMESTAMPTZ
updated_at           TIMESTAMPTZ
```

### sessions

```
id           UUID, PK
jti          VARCHAR(36), UNIQUE  -- maps 1:1 to the JWT jti claim
card_id      FK → cards.id
account_id   FK → accounts.id
atm_id       FK → atm_terminals.id
is_active    BOOLEAN
started_at   TIMESTAMPTZ
last_active  TIMESTAMPTZ
ended_at     TIMESTAMPTZ, nullable
```

### atm_terminals

```
id                       UUID, PK
atm_code                 VARCHAR(20), UNIQUE
branch_code              VARCHAR(20)
physical_address         TEXT
terminal_status          ENUM: online | offline | maintenance | out_of_cash
total_cash_available     DECIMAL(15,2)
daily_transaction_count  INT, default 0
daily_transaction_volume DECIMAL(15,2), default 0.0
last_serviced_at         TIMESTAMPTZ, nullable
backend_endpoint         VARCHAR(255), nullable
created_at               TIMESTAMPTZ
updated_at               TIMESTAMPTZ
```

### cash_cassettes

```
id           UUID, PK
atm_id       FK → atm_terminals.id
denomination INT    -- 20 means $20 notes
note_count   INT
updated_at   TIMESTAMPTZ
```

### transactions

```
id                  UUID, PK
reference_id        VARCHAR(36), UNIQUE
group_reference_id  VARCHAR(36), nullable  -- links both legs of a transfer
account_id          FK → accounts.id
atm_id              FK → atm_terminals.id, nullable
transaction_type    ENUM: withdrawal | deposit | transfer_debit | transfer_credit
amount              DECIMAL(15,2)  -- positive for credits, negative for debits
balance_after       DECIMAL(15,2)  -- available_balance snapshot after this txn
description         TEXT, nullable
status              ENUM: completed | failed | pending | reversed
created_at          TIMESTAMPTZ
```

### audit_logs

```
id                  UUID, PK
event_type          VARCHAR(100)
atm_id              FK → atm_terminals.id, nullable
masked_account_ref  VARCHAR(50)   -- e.g. "****1234"
masked_card_ref     VARCHAR(50), nullable
description         TEXT
severity            ENUM: info | warning | critical
ip_address          VARCHAR(45), nullable
metadata            JSON, nullable
created_at          TIMESTAMPTZ   -- no updated_at; this table is append-only
```

No UPDATE or DELETE queries ever run on `audit_logs`. The application code should make this physically impossible to do accidentally.

### admin_users

```
id             UUID, PK
username       VARCHAR(100), UNIQUE
password_hash  VARCHAR(255)
role           ENUM: superadmin | admin | auditor
is_active      BOOLEAN, default true
created_at     TIMESTAMPTZ
updated_at     TIMESTAMPTZ
```

### Indexes to create

- `cards.card_number` — UNIQUE (already indexed)
- `sessions.jti` — UNIQUE (this is the hot path, queried on every request)
- `transactions(account_id, created_at DESC)` — composite, for history queries
- `audit_logs(atm_id, created_at)` — for per-terminal reporting
- `transactions.transaction_type` — for type-filtered reports

---

## Card Authentication Flow

When a card is presented and a PIN entered, process in this exact order:

1. Run the Luhn algorithm on the card number. If it fails, reject without querying the database.
2. Look up the ATM terminal by ID. If the terminal status is not `online`, return `ATM_OFFLINE`.
3. Look up the card by card number. If not found, return a generic "card not recognized" error — don't hint whether the card or PIN caused the failure.
4. If `lost_or_stolen_flag` is true, return `CARD_LOST_OR_STOLEN`. If `card_status` is not `active`, return `CARD_BLOCKED` or `CARD_EXPIRED` depending on the value. If the card is past its `expiry_date`, return `CARD_EXPIRED`.
5. If `failed_attempt_count >= 3`, return `ACCOUNT_LOCKED` — card is frozen and the user must contact the bank.
6. Verify the PIN. If wrong: increment `failed_attempt_count`, commit that change, return `INVALID_PIN` with the remaining attempt count. If `failed_attempt_count` just hit 3, also set `card_status = 'blocked'` in the same commit.
7. Check for an existing active session on this card. If one exists and `last_active + 90 seconds > now`, reject with `CONCURRENT_SESSION`. If the existing session is stale, close it (set `is_active = false`, `ended_at = now`) and continue.
8. Reset `failed_attempt_count` to 0. Set `last_used_timestamp = now`. Commit.
9. Create a new row in `sessions` with a fresh UUID as `jti`.
10. Sign a JWT containing `{card_id, account_id, atm_id, jti, exp: now + 2 minutes}`. Return it.

JWT hard expiry is 2 minutes. Inactivity timeout is 90 seconds. Both are enforced independently.

Session check on every authenticated request:

1. Decode the JWT — reject with 401 if signature is invalid or `exp` is in the past.
2. Query `sessions` by `jti` — reject with `SESSION_NOT_FOUND` if the row doesn't exist or `is_active` is false.
3. Check `last_active + 90 seconds > now` — if stale, set `is_active = false` and return `SESSION_EXPIRED`. If valid, update `last_active = now` and continue.

---

## Withdrawal Logic

Check these conditions in order. The first failure returns an error and stops. Nothing is modified in the database until all checks pass.

1. `atm.terminal_status == 'online'` — otherwise `ATM_OFFLINE`
2. `atm.total_cash_available > 0` — otherwise `ATM_OUT_OF_CASH`
3. `account.account_status == 'active'` — otherwise `ACCOUNT_FROZEN`
4. `amount % settings.default_denomination == 0` — otherwise `INVALID_DENOMINATION`
5. `amount <= settings.max_single_withdrawal` — otherwise `TRANSACTION_LIMIT_EXCEEDED`
6. `amount <= (account.daily_withdrawal_limit - account.daily_withdrawal_used)` — otherwise `DAILY_LIMIT_EXCEEDED`
7. `account.available_balance >= amount` — otherwise `INSUFFICIENT_FUNDS`
8. Lock the cassette row with `SELECT ... FOR UPDATE` and check `(cassette.note_count * denomination) >= amount` — otherwise `INSUFFICIENT_ATM_CASH`

Then run fraud checks (described below) — non-blocking by default.

Then, in a single transaction:

- `account.available_balance -= amount`
- `account.total_balance -= amount`
- `account.daily_withdrawal_used += amount`
- `cassette.note_count -= int(amount / denomination)`
- `atm.total_cash_available -= amount`
- `atm.daily_transaction_count += 1`
- `atm.daily_transaction_volume += amount`
- Insert one row in `transactions` with `transaction_type = 'withdrawal'`
- Insert one row in `audit_logs` with `event_type = 'withdrawal_success'`

After committing, if `atm.total_cash_available < settings.low_cash_threshold`, write a `low_cash_alert` audit event. If `total_cash_available` is now 0, set `atm.terminal_status = 'out_of_cash'`.

Error code reference for this endpoint:

| Error Code | HTTP Status | Condition |
|---|---|---|
| `ATM_OFFLINE` | 503 | Terminal not online |
| `ATM_OUT_OF_CASH` | 503 | Cassette is empty |
| `ACCOUNT_FROZEN` | 403 | Account is frozen / closed / dormant |
| `INVALID_DENOMINATION` | 400 | Amount not divisible by note denomination |
| `TRANSACTION_LIMIT_EXCEEDED` | 422 | Exceeds per-transaction cap |
| `DAILY_LIMIT_EXCEEDED` | 422 | Would exceed daily withdrawal limit |
| `INSUFFICIENT_FUNDS` | 422 | Account balance too low |
| `INSUFFICIENT_ATM_CASH` | 503 | Cassette has cash but not enough for this amount |

---

## Deposit Logic

- Reject amounts <= 0 with `INVALID_AMOUNT`
- Reject amounts above `settings.max_single_deposit` with `TRANSACTION_LIMIT_EXCEEDED`
- Reject if account status is not `active` with `ACCOUNT_FROZEN`

If `settings.deposit_hold_days > 0`:
- `account.total_balance += amount` immediately
- `account.available_balance` stays unchanged until the hold clears
- Record `hold_release_date = today + hold_days` in the transaction description

If `settings.deposit_hold_days == 0`:
- Both `total_balance` and `available_balance` go up by `amount` immediately

Either way, add notes to the cassette: `cassette.note_count += int(amount / denomination)`. Update ATM totals. Insert transaction and audit log rows.

---

## Transfer Logic

Validation:
- Source account must be `active`
- Destination account number must exist in the database and its account must be `active`
- Source and destination accounts must be different
- `amount <= (source.daily_transfer_limit - source.daily_transfer_used)`
- `source.available_balance >= amount`

Processing — two phases:

```
Phase 1: Debit source
    pre_debit_available = source.available_balance
    pre_debit_total     = source.total_balance

    source.available_balance   -= amount
    source.total_balance       -= amount
    source.daily_transfer_used += amount

Phase 2: Credit destination
    dest.available_balance += amount
    dest.total_balance     += amount

    If Phase 2 raises any exception:
        # restore source exactly as it was before Phase 1 touched it
        source.available_balance   = pre_debit_available
        source.total_balance       = pre_debit_total
        source.daily_transfer_used -= amount
        raise TransferRollbackError("credit failed, debit reversed")
```

Create two transaction rows linked by the same `group_reference_id` UUID:
- `transfer_debit` on the source account (amount is negative)
- `transfer_credit` on the destination account (amount is positive)

Write one audit log entry covering both legs.

---

## Fraud Detection

Runs after all withdrawal validation passes, before committing anything. Non-blocking by default — a fraud hit logs a warning but doesn't stop the transaction. Set `FRAUD_BLOCK_ON_CRITICAL=true` in env to auto-reject on critical hits.

Three rules:

1. **Velocity check** — if the same account had more than 5 withdrawals in the last 10 minutes, write a `fraud_alert` with `severity = 'critical'`
2. **Large withdrawal** — if the amount is 80% or more of the daily limit, write a `fraud_alert` with `severity = 'warning'`
3. **ATM hopping** — if the same card was used at a different ATM in the last 5 minutes, write a `fraud_alert` with `severity = 'critical'`

Fraud audit entries must include: masked account ref, masked card ref, ATM ID, amount, rule name, severity.

---

## Admin Panel

Admin users authenticate separately from card holders. They get their own table (`admin_users`), their own JWT secret (`ADMIN_SECRET_KEY` env var), and longer-lived tokens (8 hours by default).

Role permissions:

| Action | superadmin | admin | auditor |
|---|---|---|---|
| Create admin user | yes | no | no |
| Freeze / unfreeze account | yes | yes | no |
| Block / unblock card | yes | yes | no |
| View reports | yes | yes | yes |
| Refill ATM cassette | yes | yes | no |

Endpoints:

```
POST   /admin/auth/login
POST   /admin/accounts/create
PUT    /admin/accounts/{id}/freeze
PUT    /admin/accounts/{id}/unfreeze
GET    /admin/accounts                   -- search by name, account number, status
POST   /admin/cards/block
POST   /admin/cards/unblock
PUT    /admin/atm/{id}/refill
GET    /admin/reports/transactions       -- filter by date range and type; export as JSON or CSV
GET    /admin/reports/failed-logins      -- failed PIN attempts grouped by card and date
GET    /admin/reports/suspicious         -- audit_log rows with severity = 'critical'
POST   /admin/users/create              -- superadmin only
```

---

## Public API Endpoints

```
POST   /auth/login
POST   /auth/logout

GET    /account/balance

POST   /transaction/withdraw
POST   /transaction/deposit
POST   /transaction/transfer
GET    /transaction/history       -- paginated, filter by date and type
GET    /transaction/statement     -- last 10 transactions, newest first

GET    /atm/{atm_id}/status

GET    /health
```

All endpoints except `/health` and `/auth/login` require `Authorization: Bearer <token>`.

Every response is a JSON object. Success responses have a `data` key. Error responses have `error_code`, `message`, and `http_status`. No raw strings, no bare arrays, no 200 status for failures.

---

## Exception Hierarchy

Every failure is a typed exception. One FastAPI handler at the app level catches them and converts to JSON. No other error handling scattered around the codebase.

```
ATMBaseException                    (base — holds http_status and error_code)
├── InvalidCardNumberError          400
├── InvalidPINError                 401
├── CardBlockedError                403
├── CardExpiredError                403
├── CardLostOrStolenError           403
├── AccountLockedError              403
├── SessionExpiredError             401
├── SessionNotFoundError            401
├── ConcurrentSessionError          409
├── AccountNotFoundError            404
├── AccountFrozenError              403
├── InsufficientFundsError          422
├── DailyLimitExceededError         422
├── TransactionLimitExceededError   422
├── InvalidDenominationError        400
├── InvalidAmountError              400
├── ATMOutOfCashError               503
├── InsufficientATMCashError        503
├── ATMOfflineError                 503
├── ATMNotFoundError                404
├── TransferRollbackError           500
├── AdminNotFoundError              404
├── AdminAuthError                  401
├── InsufficientPermissionsError    403
├── DatabaseError                   500
└── SystemError                     500
```

---

## Logging

structlog only. Every log record is a structured dict — no free-form string messages.

Required fields on every record:
- `event` — snake_case name, e.g. `withdrawal_success`, `login_failed`
- `timestamp` — ISO-8601 UTC
- `atm_id` — include when available
- `masked_account_ref` — always last 4 digits only, e.g. `****1234`
- `severity` — info | warning | critical

Full card numbers, PINs, and stack traces never appear in any log line. Ever. Mask before logging, not after.

---

## Security

**PIN hashing:** Argon2id with `m=65536` (64 MiB), `t=3`, `p=4`. Those are the OWASP PHC minimum parameters. bcrypt if Argon2 isn't available — controlled by `PIN_HASH_ALGORITHM` env var.

**Card numbers:** AES-256 encrypted at rest. Key comes from `CARD_NUMBER_ENCRYPTION_KEY` env var. Plaintext card numbers don't touch the database.

**JWT:** HS256, signed with `SECRET_KEY`. The `jti` claim is a UUID stored in the `sessions` table — this is what lets us invalidate a token server-side without a separate blocklist.

**Rate limiting:** 60 requests/minute by default across all endpoints. Auth endpoints cap at 10 requests/minute. Exceeding it returns 429.

**Error responses:** Stack traces never go to the client. The generic 500 handler logs internally and returns `{"error_code": "SYSTEM_ERROR", "message": "Something went wrong"}`.

---

## Environment Variables

```
APP_NAME                          default: "ATM Banking System"
APP_ENV                           development | production | testing
SECRET_KEY                        JWT signing secret — no default, must be set
ALGORITHM                         HS256
DATABASE_URL                      SQLAlchemy connection string
ACCESS_TOKEN_EXPIRE_MINUTES       default: 2
SESSION_INACTIVITY_SECONDS        default: 90
PIN_HASH_ALGORITHM                argon2 | bcrypt  (default: argon2)
MAX_PIN_ATTEMPTS                  default: 3
CARD_NUMBER_ENCRYPTION_KEY        no default, must be set
DEFAULT_DENOMINATION              default: 20
LOW_CASH_THRESHOLD                default: 5000
DEFAULT_DAILY_WITHDRAWAL_LIMIT    default: 1000
MAX_SINGLE_WITHDRAWAL             default: 500
MAX_SINGLE_DEPOSIT                default: 10000
DEPOSIT_HOLD_DAYS                 default: 1
RATE_LIMIT_PER_MINUTE             default: 60
ADMIN_SECRET_KEY                  no default, must be set
FRAUD_BLOCK_ON_CRITICAL           default: false
LOG_LEVEL                         default: INFO
LOG_FORMAT                        json | console  (default: console)
```

---

## Tests

Every test must assert that the DB state is correct, not just that the HTTP response looks right. If a withdrawal test passes but the balance in the DB isn't reduced, it's not a passing test.

Scenarios to cover:

- Login with correct PIN → session row created, JWT returned, `failed_attempt_count` is 0
- Login with wrong PIN × 3 → card `failed_attempt_count` is 3, card status is `blocked`. Stop the server. Restart it. Try to login again → still blocked. This proves the lock is persisted, not in-memory.
- Withdrawal with sufficient balance → `available_balance` reduced, cassette `note_count` reduced, one transaction row inserted
- Withdrawal with insufficient balance → 422, no DB state changed at all
- Withdrawal that would hit daily limit → 422, `daily_withdrawal_used` not incremented
- Withdrawal with amount not divisible by denomination → 400, no DB queries beyond auth validation
- Withdrawal when cassette is empty → 503
- Deposit with hold → `total_balance` goes up, `available_balance` unchanged, hold date in transaction description
- Transfer where credit leg throws → source `available_balance` is identical to what it was before the request. `daily_transfer_used` is not incremented.
- Request after 90 seconds of session inactivity → 401 SESSION_EXPIRED
- Auditor tries to freeze an account → 403 INSUFFICIENT_PERMISSIONS

**Load test (Locust):** 100 users all send `POST /transaction/withdraw` for $20 against the same account which starts with $500. After all requests complete:
- `account.available_balance >= 0` — never negative
- The sum of all successful transaction amounts equals exactly how much the balance dropped
- No transaction rows have duplicate `reference_id` values
- No SQLAlchemy deadlock errors in the logs

---

## Deliverables

A complete, working codebase. Not a skeleton. Every file in the project structure above must exist and contain real, runnable code.

- All source files under `app/`
- At least one Alembic migration in `migrations/versions/` that creates all tables
- All test files under `tests/` — `pytest` runs cleanly with no skips on the core scenarios above
- `scripts/seed_data.py` — creates 3 ATMs, 5 accounts with linked cards, some transaction history
- `scripts/create_admin.py` — prompts for username and password, creates a superadmin
- `docker/Dockerfile` and `docker/docker-compose.yml` — `docker compose up` should start the API against PostgreSQL with no extra steps
- `.env.example` — every variable listed above with a one-line comment explaining it
- `requirements.txt` — pinned versions, `pip install -r requirements.txt` works on a clean Python 3.11 env
- `README.md` — covers: local setup, running with Docker, all env vars, running tests, seeding data, creating an admin user
