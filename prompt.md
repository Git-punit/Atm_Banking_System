# Build a Production-Grade ATM Banking System in Python

## Who this is for

I'm a senior backend engineer at a fintech company. We're building a full ATM banking backend for a mid-sized commercial bank — not a toy project, not a tutorial, but something a real bank could actually deploy. I need another senior engineer (or a capable LLM) to implement the whole thing from scratch.

This document is the full spec. Read it carefully before writing a single line of code. Everything in here is a real requirement, not a suggestion.

---

## The big picture

The system simulates real-world ATM infrastructure. Think of it as the backend that sits behind every ATM terminal in a bank's network — handling card authentication, cash dispensing, deposits, transfers, session management, fraud detection, and the admin tools the operations team uses to monitor everything.

It needs to support hundreds of ATM terminals and thousands of concurrent transactions without dropping consistency or compromising security. That means proper locking, atomic operations, and no shortcuts on the auth side.

The tech stack is fixed:

- **Python + FastAPI** for the backend
- **PostgreSQL** in production, **SQLite** for local dev and tests
- **SQLAlchemy** as the ORM with **Alembic** for migrations
- **bcrypt or Argon2** for PIN hashing, **JWT** for session tokens
- **Pytest** for tests, **Docker + docker-compose** for deployment
- **Swagger/OpenAPI** for API docs (FastAPI gives you this for free)

---

## Project structure

Organise the code as a proper Python package. Something like this:

```
atm-banking-system/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── dependencies.py
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── routers/         # FastAPI route handlers
│   ├── services/        # Business logic (no DB calls in routers)
│   └── core/            # Security, exceptions, logging
├── migrations/          # Alembic migration scripts
├── tests/
├── scripts/             # seed_data.py, create_admin.py
├── docker/
├── .env.example
├── requirements.txt
└── README.md
```

Keep business logic in services, not in routers. Routers should just validate input, call a service, and return a response.

---

## Authentication and card management

This is the most security-sensitive part of the system. Get it right.

### How login works

1. The ATM sends a card number and PIN to `POST /auth/login`
2. Validate the card number using the **Luhn algorithm** before touching the database
3. Look up the card, check its status (active / blocked / expired / lost)
4. Verify the PIN against the stored hash using bcrypt or Argon2 — never store or log plaintext PINs
5. If the PIN is wrong, increment `failed_attempt_count`. After **3 consecutive failures**, set `card_status = "blocked"` and persist it. This lock must survive a server restart.
6. If the card is already locked, reject the login immediately — don't even check the PIN
7. On success, reset `failed_attempt_count` to 0, create a session row in the database, and issue a JWT
8. The JWT must contain a `jti` claim that maps to the session row — this is how we invalidate tokens server-side
9. Sessions expire after **90 seconds of inactivity**. Each successful API call refreshes the timer.
10. Only one active session per card at a time. If a valid session already exists, reject the new login with a 409.

### Card data model

```python
card_number          # 16-digit string
linked_account_id    # FK to accounts
card_status          # "active" | "blocked" | "expired" | "lost" | "stolen"
expiry_date          # date
daily_withdrawal_limit
pin_hash             # bcrypt/Argon2 hash, never plaintext
failed_attempt_count # resets on successful login, persists on failure
last_used_timestamp
lost_or_stolen_flag  # bool, set by admin
```

Admins can block/unblock cards and flag them as lost or stolen via the admin API.

---

## Account management

### Account data model

```python
account_number
account_holder_name
account_type          # "savings" | "current" | "salary"
available_balance     # what the customer can spend right now
total_balance         # includes held funds
daily_withdrawal_limit
daily_withdrawal_used
daily_withdrawal_reset_date  # reset to 0 when date rolls over
daily_transfer_limit
daily_transfer_used
account_status        # "active" | "frozen" | "closed" | "dormant"
kyc_verification_status  # "pending" | "verified" | "rejected"
branch_code
currency              # ISO 4217
```

### What the account module needs to do

- Create accounts with an optional initial deposit
- Support multiple cards linked to one account
- Support joint accounts (is_joint_account flag)
- Balance inquiry — return both available and total balance, clearly labelled
- Balance holds — deposited funds may be held for a configurable number of days before becoming available
- Daily limit tracking — reset `daily_withdrawal_used` and `daily_transfer_used` when the calendar date changes
- Admin freeze/unfreeze — frozen accounts can't withdraw, deposit, or transfer
- Low balance alerts — log an audit event when balance drops below a configurable threshold

---

## Cash withdrawal

This is where most of the complexity lives. Every validation must happen before any money moves.

### Validation order (fail fast, in this order)

1. ATM is online and not out of cash
2. Account is active and not frozen
3. Amount is a positive integer and a multiple of the ATM's denomination (e.g. must be divisible by $20)
4. Amount is within the per-transaction limit
5. Amount doesn't exceed the remaining daily withdrawal limit
6. Account has sufficient available balance
7. ATM cassette has enough physical notes to cover the withdrawal

### On success (all atomic within one DB transaction)

- Deduct `available_balance` and `total_balance` on the account
- Deduct note count from the ATM cassette
- Update `daily_withdrawal_used`
- Update ATM daily transaction count and volume
- Create a transaction record
- Write an audit log entry
- If ATM cash drops below the configured low-cash threshold, write a `low_cash_alert` audit event

### On failure

Return a specific error for each case — don't just say "transaction failed". The error codes should be:
- `INSUFFICIENT_FUNDS`
- `ATM_OUT_OF_CASH`
- `INSUFFICIENT_ATM_CASH`
- `DAILY_LIMIT_EXCEEDED`
- `INVALID_DENOMINATION`
- `TRANSACTION_LIMIT_EXCEEDED`
- `ACCOUNT_FROZEN`
- `ATM_OFFLINE`

---

## Cash deposit

Simpler than withdrawal but still needs care around the available vs total balance distinction.

- Accept only positive integer amounts
- Enforce a configurable per-deposit ceiling (default $10,000)
- Apply a configurable hold period (default 1 day) — `total_balance` increases immediately, `available_balance` increases after the hold
- Update the ATM cassette inventory
- Log the deposit event
- The response must clearly show both `available_balance` and `total_balance` so the customer knows what they can spend right now

---

## Fund transfers

Peer-to-peer transfers between accounts. The tricky part is making sure the debit and credit are atomic.

### The transfer flow

1. Validate source account is active
2. Look up destination account by account number — return a clear error if it doesn't exist
3. Check destination account is active and can receive funds
4. Check daily transfer limit on the source account
5. Check source account has sufficient balance
6. **Debit the source account**
7. **Credit the destination account** — if this step fails for any reason, roll back the debit
8. Create two transaction records: one `transfer_debit` on the source, one `transfer_credit` on the destination
9. Both records should reference each other via `peer_reference_id`

The rollback in step 7 is critical. Add a comment in the code that explicitly says what state is being restored and why. Something like:

```python
# ROLLBACK: Restoring source account balance to pre-debit state.
# The credit leg failed, so no funds were actually moved.
# We restore available_balance, total_balance, and daily_transfer_used
# to prevent the customer from losing money without the recipient receiving it.
```

---

## Transaction history and mini-statement

### Mini-statement (for ATM receipt)

- Last 10 transactions, newest first
- Each entry shows: type, amount, balance after, timestamp, reference ID
- Debits and credits clearly labelled

### Full history (for admin and customer portal)

- Paginated (page + page_size)
- Filterable by date range and transaction type
- Exportable as CSV or JSON
- Must handle accounts with very large histories efficiently — use indexed queries, not in-memory filtering

---

## ATM terminal management

ATM terminals are first-class entities in the system, not just a config value.

### ATM data model

```python
atm_code              # human-readable ID like "ATM-HQ-001"
branch_code
physical_address
terminal_status       # "online" | "offline" | "maintenance" | "out_of_cash"
total_cash_available  # denormalised sum for quick checks
daily_transaction_count
daily_transaction_volume
stats_reset_date      # reset daily stats when date changes
last_serviced_at
connected_backend_endpoint
```

Each ATM has one or more cash cassettes, each holding a specific denomination. Track note count per cassette, not just total cash.

### Session management

- Sessions are tied to a specific ATM terminal
- Inactive sessions (no activity for 90 seconds) are expired automatically
- Logout and card removal both invalidate the session
- Session start and end events are logged in the audit table

---

## Admin control panel

Admins use a completely separate authentication system — separate table, separate JWT secret, separate login endpoint. An ATM session token must never grant admin access.

### What admins can do

- Freeze and unfreeze accounts (with a required reason)
- Block and unblock cards (with a required reason, option to flag as lost/stolen)
- Create new ATM terminals and configure their cassettes
- Refill ATM cassettes (logged as an audit event)
- Update ATM terminal status
- View all accounts with pagination
- Pull transaction reports with date/type filters and CSV export
- See cards with failed login attempts
- See recent fraud alerts and suspicious activity from the audit log
- Create new admin users (superadmin only)

Admin roles: `superadmin`, `admin`, `auditor`. Auditors can read but not write.

---

## Security requirements

These are non-negotiable.

- **PIN hashing**: Argon2 preferred, bcrypt acceptable. Never store or log plaintext PINs.
- **JWT**: Separate secrets for ATM sessions and admin sessions. Include `jti` for server-side invalidation.
- **Session invalidation**: Invalidating a session means marking it inactive in the database. The JWT expiry alone is not enough.
- **Input validation**: Validate every field on every request. Reject malformed card numbers before hitting the database.
- **Rate limiting**: Apply per-IP rate limiting on the login endpoint (max 10 requests/minute).
- **Audit logs**: Append-only. Never update or delete audit log rows. Mask card numbers and account numbers in all log entries (show only last 4 digits).
- **Error responses**: Never expose stack traces, internal error messages, full card numbers, or PIN values in API responses.
- **SQL injection**: Use parameterised queries via SQLAlchemy ORM. Never concatenate user input into SQL strings.

---

## Database schema

At minimum, you need these tables:

| Table | Purpose |
|-------|---------|
| `accounts` | Bank accounts |
| `cards` | ATM/debit cards |
| `sessions` | Active and historical ATM sessions |
| `transactions` | Immutable transaction ledger |
| `atm_terminals` | ATM terminal registry |
| `cash_cassettes` | Per-denomination cash inventory per ATM |
| `admin_users` | Admin user accounts (separate from card holders) |
| `audit_logs` | Append-only security and compliance event log |

Use proper foreign keys. Index every column that appears in a WHERE clause or JOIN. Use `String(36)` UUIDs as primary keys for portability between SQLite and PostgreSQL.

Write Alembic migration scripts. The initial migration should create all tables. Don't use `create_all()` in production — use migrations.

---

## REST API endpoints

### Authentication
```
POST /auth/login          # card + PIN → JWT
POST /auth/logout         # invalidate session
POST /admin/auth/login    # admin credentials → admin JWT
```

### Account (requires ATM session JWT)
```
GET  /account/balance
```

### Transactions (requires ATM session JWT)
```
POST /transaction/withdraw
POST /transaction/deposit
POST /transaction/transfer
GET  /transaction/history
GET  /transaction/statement   # mini-statement
```

### ATM
```
GET  /atm/status              # requires ATM session JWT
GET  /atm/all                 # requires admin JWT
POST /atm/create              # requires admin JWT
POST /atm/{atm_id}/refill     # requires admin JWT
PUT  /atm/{atm_id}/status     # requires admin JWT
```

### Admin (all require admin JWT)
```
POST /admin/accounts/create
GET  /admin/accounts
PUT  /admin/accounts/{id}/freeze
PUT  /admin/accounts/{id}/unfreeze
POST /admin/cards/block
POST /admin/cards/unblock
GET  /admin/reports/transactions
GET  /admin/reports/failed-logins
GET  /admin/reports/suspicious
POST /admin/users/create      # superadmin only
```

Every endpoint must return structured JSON with consistent error shapes:
```json
{
  "error_code": "INSUFFICIENT_FUNDS",
  "message": "Insufficient funds. Available: 45.00"
}
```

---

## Error handling

Every domain error gets its own exception class. Don't catch generic `Exception` and return a 500 for everything.

The exception hierarchy should look something like:

```
ATMBaseException
├── Auth errors: InvalidCardNumberError, InvalidPINError, AccountLockedError,
│               CardBlockedError, CardExpiredError, SessionExpiredError,
│               ConcurrentSessionError
├── Account errors: AccountNotFoundError, AccountFrozenError, AccountClosedError
├── Transaction errors: InsufficientFundsError, DailyLimitExceededError,
│                      InvalidDenominationError, TransactionLimitExceededError,
│                      DepositCeilingExceededError, TransferRollbackError
├── ATM errors: ATMNotFoundError, ATMOfflineError, ATMOutOfCashError
└── Admin errors: AdminAuthError, InsufficientPermissionsError
```

Each exception class should have an `http_status` and `error_code` attribute so the FastAPI exception handler can convert it to a proper HTTP response automatically.

---

## Logging

Use structured logging (structlog recommended). Every log entry must include:

- `timestamp` (UTC, ISO 8601)
- `event_type` (e.g. `withdrawal_success`, `login_failed`)
- `atm_id` (when applicable)
- `masked_account_ref` (last 4 digits only)
- `masked_card_ref` (last 4 digits only)

In production, log as JSON. In development, use the human-readable console renderer.

Never log: full card numbers, PINs, JWT tokens, or raw SQL queries containing user data.

---

## Fraud detection

Implement basic rule-based fraud detection inside the withdrawal service. These checks run on every withdrawal and log alerts to the audit table — they don't block the transaction, they flag it for human review.

Rules to implement:

1. **Velocity**: More than 5 withdrawals in the last 10 minutes from the same account → `fraud_alert`
2. **Large withdrawal**: Single withdrawal over 80% of the daily limit → `fraud_alert`
3. **Multi-location**: Withdrawal at a different ATM within 5 minutes of a previous withdrawal → `fraud_alert`

---

## Testing

Write tests for every meaningful behaviour, not just the happy path.

### Required test scenarios

| Scenario | What to verify |
|----------|---------------|
| Correct PIN login | Returns JWT, session created, failed_attempt_count reset |
| Wrong PIN × 3 | Card status becomes "blocked", persists after restart |
| Withdrawal success | Balance deducted, cassette decremented, transaction created |
| Withdrawal — insufficient funds | 422 with INSUFFICIENT_FUNDS error code |
| Withdrawal — invalid denomination | 400 with INVALID_DENOMINATION error code |
| Withdrawal — daily limit | 422 with DAILY_LIMIT_EXCEEDED error code |
| Withdrawal — frozen account | 403 with ACCOUNT_FROZEN error code |
| Withdrawal — ATM out of cash | 503 with ATM_OUT_OF_CASH error code |
| Transfer success | Both accounts updated, two transaction records created |
| Transfer rollback | If credit fails, source balance is fully restored |
| Session expiry | Request after 90s inactivity returns 401 SESSION_EXPIRED |
| Concurrent session | Second login with same card returns 409 CONCURRENT_SESSION |
| Admin auth | ATM token rejected on admin endpoints |
| Low cash alert | Audit log contains low_cash_alert after cassette drops below threshold |

### Load test

Simulate 100 concurrent withdrawal requests against the same account. Verify:
- The final balance is never negative
- No race conditions (balance deducted exactly as many times as successful withdrawals)
- All transactions are consistent and accounted for

Use SQLite with WAL mode for the load test so you don't need a running PostgreSQL instance.

---

## Seed data

Provide a `scripts/seed_data.py` that creates:

- 1 superadmin user (print credentials to stdout)
- 3 ATM terminals with realistic cash cassette configurations
- 5 customer accounts with different types and balances
- 5 ATM cards (one per account) with known PINs (print them to stdout)
- Some historical transactions for each account

The seed script should be idempotent — running it twice shouldn't create duplicates.

---

## Docker setup

Provide a `docker-compose.yml` that brings up:

- The FastAPI application
- PostgreSQL
- (Optional) pgAdmin for database inspection

The app container should run database migrations automatically on startup before accepting requests.

Provide a `.env.example` with every environment variable the app needs, with sensible defaults and comments explaining each one.

---

## Documentation

The README needs to cover:

1. **What this is** — one paragraph
2. **Prerequisites** — Python version, Docker, etc.
3. **Quick start** — clone, copy `.env.example`, `docker-compose up`, seed data, first API call
4. **Environment variables** — table with name, description, default
5. **Running tests** — `pytest` command, how to run load tests separately
6. **API overview** — link to the Swagger docs, brief description of each endpoint group
7. **Database schema** — brief description of each table and its purpose
8. **Architecture notes** — why services are separate from routers, why history is updated after evaluation in fraud checks, etc.
9. **Extending the system** — how to add a new fraud rule, how to add a new ATM terminal

---

## What I expect to receive

A complete, working codebase. Not pseudocode, not a skeleton with `# TODO` everywhere. Every file listed in the project structure should exist and contain real, runnable code.

Specifically:

- All source files under `app/`
- Alembic migration in `migrations/versions/`
- All test files under `tests/` — they should pass with `pytest`
- `scripts/seed_data.py` and `scripts/create_admin.py`
- `docker/Dockerfile` and `docker/docker-compose.yml`
- `.env.example` with all variables documented
- `requirements.txt` with pinned versions
- `README.md` covering everything in the documentation section above

The code should be clean enough that a new engineer could read it, understand it, and extend it without needing to ask questions. That means meaningful variable names, docstrings on public methods, and comments explaining non-obvious decisions — not comments that just restate what the code does.
