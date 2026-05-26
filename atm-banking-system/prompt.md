# ATM Banking System — Master Development Prompt

## Context and Role

You are a **senior Python backend engineer** at a fintech company building a **production-grade ATM Banking System** for a mid-sized commercial bank. The system simulates real-world ATM infrastructure end-to-end: physical ATM terminals, centralized banking services, transaction processing, card authentication, audit logging, cash inventory management, fraud detection, and an administrative control panel.

Your mandate is to design and implement a backend that is:

- **Secure** — follows OWASP guidelines, never leaks sensitive data, uses hardware-grade hashing
- **Consistent** — transactional integrity under concurrent load, no phantom reads, no double-spends
- **Modular** — clearly separated concerns; every layer is independently testable and replaceable
- **Operationally observable** — structured logs, health checks, alerting hooks, audit trails
- **Production-ready** — works in Docker, supports environment-based config, has migration scripts

The system must be something a real bank could extend and deploy with minimal changes.

---

## Objective

Deliver a **complete, working Python backend** covering:

| Area | Deliverable |
|---|---|
| Auth | Card + PIN login, JWT sessions, lockout, logout |
| Accounts | CRUD, balance management, limits, KYC, freeze/unfreeze |
| Withdrawals | Validated, atomic cash dispensing with cassette management |
| Deposits | Hold periods, balance split (available vs total) |
| Transfers | Two-phase debit/credit with explicit rollback |
| Statements | Mini-statement, paginated history, CSV/JSON export |
| ATM Terminals | Terminal entity, status tracking, cassette inventory |
| Admin | Separate auth, reporting, monitoring, card and account control |
| Fraud | Rule-based detection, velocity checks, anomaly alerts |
| Observability | Structured logs, masked PII, append-only audit trail |
| Infrastructure | Docker, migrations, seed data, full test suite, load tests |

---

## 1. Authentication and Card Management

### 1.1 Authentication Flow

- Validate 16-digit card numbers using the **Luhn algorithm** before touching the database
- Hash PINs with **Argon2id** (preferred) or bcrypt; never store or log plaintext PINs
- Lock the card after **3 consecutive failed PIN attempts** — the lock must survive server restarts (persisted in DB, not in-memory)
- Issue **short-lived JWT tokens** (2-minute hard expiry) containing a `jti` claim mapped to the sessions table
- Enforce **90-second inactivity timeout** checked on every authenticated request
- Prevent **concurrent sessions** — a second login from a different terminal must invalidate or reject the existing session (configurable)
- Support explicit **logout** (invalidates the JWT by marking `jti` as expired in the DB)
- ATM admins can **force-terminate** any active session
- All login events (success, failure, lockout) are written to the audit log with the ATM ID and masked card reference

### 1.2 Card Data Model

```
cards
├── id                    UUID PK
├── card_number           VARCHAR(16) UNIQUE — stored encrypted at rest
├── linked_account_id     FK → accounts.id
├── card_status           ENUM(active, blocked, expired, lost_stolen)
├── expiry_date           DATE
├── pin_hash              VARCHAR(255)
├── failed_attempt_count  INT DEFAULT 0
├── last_used_timestamp   TIMESTAMPTZ
├── lost_or_stolen_flag   BOOLEAN DEFAULT false
├── issued_at             TIMESTAMPTZ
└── created_at / updated_at
```

### 1.3 Session Data Model

```
sessions
├── id            UUID PK
├── jti           VARCHAR(36) UNIQUE — maps 1:1 to the JWT jti claim
├── card_id       FK → cards.id
├── account_id    FK → accounts.id
├── atm_id        FK → atm_terminals.id
├── is_active     BOOLEAN
├── started_at    TIMESTAMPTZ
├── last_active   TIMESTAMPTZ
└── ended_at      TIMESTAMPTZ (nullable)
```

---

## 2. Account Management

### 2.1 Account Data Model

```
accounts
├── id                          UUID PK
├── account_number              VARCHAR(20) UNIQUE
├── account_holder_name         VARCHAR(200)
├── account_type                ENUM(savings, current, salary)
├── available_balance           DECIMAL(15,2)
├── total_balance               DECIMAL(15,2)   -- includes held funds
├── daily_withdrawal_limit      DECIMAL(15,2)
├── daily_withdrawal_used       DECIMAL(15,2)
├── daily_withdrawal_reset_date DATE
├── daily_transfer_limit        DECIMAL(15,2)
├── daily_transfer_used         DECIMAL(15,2)
├── daily_transfer_reset_date   DATE
├── account_status              ENUM(active, frozen, closed, dormant)
├── kyc_verification_status     ENUM(pending, verified, rejected)
├── is_joint_account            BOOLEAN
├── low_balance_threshold       DECIMAL(15,2)  -- nullable; triggers alert when crossed
├── branch_code                 VARCHAR(20)
├── currency                    CHAR(3) DEFAULT 'USD'
├── notes                       TEXT
└── created_at / updated_at
```

### 2.2 Required Features

- Account creation with validation (unique account number, KYC status gate)
- Balance inquiry (return both `available_balance` and `total_balance` separately)
- Daily limit enforcement with **midnight-based reset** (not rolling 24 hours)
- Admin **freeze / unfreeze** with reason logging
- Admin **close** with balance check (must be zero before closing)
- Low-balance threshold alerts written to the audit log
- Multiple cards can be linked to one account
- Joint account flag tracked (business logic extension point)

---

## 3. Cash Withdrawal

### 3.1 Validation Rules (evaluated in order, fail fast)

1. ATM terminal is operational and not in `out_of_cash` status
2. Account is `active` (not frozen, closed, or dormant)
3. Amount is a positive integer **multiple of the configured denomination** (e.g. $20)
4. Amount does not exceed the **per-transaction limit**
5. Amount does not exceed the **remaining daily withdrawal limit**
6. Account `available_balance ≥ amount`
7. ATM cassette has enough **physical notes** to dispense (use `SELECT ... FOR UPDATE` to prevent race conditions)
8. Fraud checks pass (non-blocking — log and continue unless severity is critical)

### 3.2 Atomic Processing

All of the following must succeed together or all roll back:

- Deduct `available_balance` and `total_balance` from account
- Increment `daily_withdrawal_used`
- Deduct note count and cash total from `cash_cassettes`
- Update ATM `daily_transaction_count` and `daily_transaction_volume`
- Insert `Transaction` record
- Insert `AuditLog` record

### 3.3 Low-Cash Alerting

After every successful withdrawal, if `atm.total_cash_available < low_cash_threshold` (configurable, default $5,000), write a `low_cash_alert` audit event with severity `warning`. If the cassette hits zero, set `terminal_status = 'out_of_cash'`.

### 3.4 Error Taxonomy

Return distinct error codes — never a generic "transaction failed":

| Error Code | HTTP | Meaning |
|---|---|---|
| `INSUFFICIENT_FUNDS` | 422 | Account balance too low |
| `DAILY_LIMIT_EXCEEDED` | 422 | Would exceed daily limit |
| `TRANSACTION_LIMIT_EXCEEDED` | 422 | Single-txn cap breached |
| `INVALID_DENOMINATION` | 400 | Amount not a multiple of note denomination |
| `ATM_OUT_OF_CASH` | 503 | Cassette empty |
| `INSUFFICIENT_ATM_CASH` | 503 | Cassette has cash but not enough for this amount |
| `ACCOUNT_FROZEN` | 403 | Account is frozen/closed/dormant |
| `ATM_OFFLINE` | 503 | Terminal is offline/maintenance |

---

## 4. Cash Deposit

- Reject amounts ≤ 0 and amounts above the configurable ceiling (default $10,000 per transaction)
- If `deposit_hold_days > 0` (default: 1): credit `total_balance` immediately, credit `available_balance` only after the hold clears
- Record the `hold_release_date` in the transaction description
- Add deposited notes to the ATM cassette inventory and update ATM totals
- All deposit events appear in the audit log

---

## 5. Fund Transfer

### 5.1 Validation

- Source account must be `active`
- Destination account must exist and be `active` (can receive credits)
- Source and destination must be different accounts
- Amount must not exceed remaining `daily_transfer_limit`
- Source `available_balance ≥ amount`

### 5.2 Two-Phase Processing with Explicit Rollback

```
Phase 1 — DEBIT source
  • Save pre-debit balances for rollback
  • available_balance -= amount
  • total_balance     -= amount
  • daily_transfer_used += amount

Phase 2 — CREDIT destination
  • available_balance += amount
  • total_balance     += amount

  If Phase 2 raises any exception:
    ROLLBACK Phase 1
      • available_balance = pre_debit_available   (restores spendable funds)
      • total_balance     = pre_debit_total        (restores ledger balance)
      • daily_transfer_used -= amount              (restores limit headroom)
    raise TransferRollbackError
```

Code comments must explain **what** is restored and **why**.

### 5.3 Transaction Records

Create two transaction records per transfer, linked by a shared `group_reference_id`:

| Field | Debit Leg | Credit Leg |
|---|---|---|
| `transaction_type` | `transfer_debit` | `transfer_credit` |
| `amount` | negative | positive |
| `account_id` | source | destination |
| `reference_id` | unique UUID | unique UUID |
| `group_reference_id` | shared | shared |

---

## 6. Statements and History

### Mini-Statement (default)

- Last 10 transactions, reverse-chronological
- Each row: `type`, `amount`, `balance_after`, `timestamp`, `reference_id`, `description`
- Positive amounts = credits, negative = debits

### Full Transaction History

- Paginated (`page`, `page_size`, total count in response)
- Filter by: `date_from`, `date_to`, `transaction_type`
- Export in JSON (default) and CSV
- Must scale to accounts with millions of rows — use DB-level pagination, not Python slicing

---

## 7. ATM Terminal Management

### 7.1 Terminal Data Model

```
atm_terminals
├── id                       UUID PK
├── atm_code                 VARCHAR(20) UNIQUE
├── branch_code              VARCHAR(20)
├── physical_address         TEXT
├── terminal_status          ENUM(online, offline, maintenance, out_of_cash)
├── total_cash_available     DECIMAL(15,2)
├── daily_transaction_count  INT
├── daily_transaction_volume DECIMAL(15,2)
├── last_serviced_at         TIMESTAMPTZ
├── backend_endpoint         VARCHAR(255)
└── created_at / updated_at
```

### 7.2 Cash Cassette Model

```
cash_cassettes
├── id             UUID PK
├── atm_id         FK → atm_terminals.id
├── denomination   INT   -- e.g. 20
├── note_count     INT
└── updated_at
```

### 7.3 Session Contract

Every request to an authenticated endpoint must:
1. Verify the JWT signature and expiry
2. Look up the `jti` in the sessions table — reject if not found or `is_active = false`
3. Check `last_active + 90s > now()` — reject with `SESSION_EXPIRED` if stale, update otherwise

---

## 8. Admin Control Panel

### 8.1 Separate Auth System

Admin users authenticate against a separate table (`admin_users`) using a distinct JWT secret. Admin tokens are longer-lived (configurable, default 8 hours).

```
admin_users
├── id            UUID PK
├── username      VARCHAR(100) UNIQUE
├── password_hash VARCHAR(255)
├── role          ENUM(superadmin, admin, auditor)
├── is_active     BOOLEAN
└── created_at / updated_at
```

### 8.2 Role-Based Access

| Action | superadmin | admin | auditor |
|---|---|---|---|
| Create admin user | ✅ | ❌ | ❌ |
| Freeze/unfreeze account | ✅ | ✅ | ❌ |
| Block/unblock card | ✅ | ✅ | ❌ |
| View reports | ✅ | ✅ | ✅ |
| Refill ATM cassette | ✅ | ✅ | ❌ |

### 8.3 Required Endpoints

```
POST   /admin/auth/login
POST   /admin/accounts/create
PUT    /admin/accounts/{id}/freeze
PUT    /admin/accounts/{id}/unfreeze
GET    /admin/accounts               (search/filter)
POST   /admin/cards/block
POST   /admin/cards/unblock
PUT    /admin/atm/{id}/refill
GET    /admin/reports/transactions   (date range, type filter, CSV/JSON)
GET    /admin/reports/failed-logins
GET    /admin/reports/suspicious
POST   /admin/users/create           (superadmin only)
```

---

## 9. Fraud Detection

Implement a **non-blocking**, rule-based fraud engine called on every withdrawal. Hits are logged as audit events for human review — they do not auto-reject (unless severity is configurable to do so).

### Rules

| Rule | Trigger | Severity |
|---|---|---|
| Velocity | > 5 withdrawals in 10 minutes from same account | `critical` |
| Large withdrawal | Single amount ≥ 80% of daily limit | `warning` |
| Geographic anomaly | Same card used at two different ATMs within 5 minutes | `critical` |

Each fraud hit must log: `account_id` (masked), `atm_id`, `rule_triggered`, `amount`, `timestamp`, and severity.

---

## 10. Security Requirements

### Authentication

- Argon2id with OWASP-recommended parameters: `m=65536` (64 MiB), `t=3`, `p=4`
- bcrypt as fallback (configurable via `PIN_HASH_ALGORITHM` env var)
- JWT signed with HS256; `jti` claim enables server-side invalidation

### Input Validation

- All request bodies validated by Pydantic v2 with strict mode
- Card numbers validated by Luhn before any DB query
- All amounts validated as positive numbers with precision checks

### Data Protection

- Card numbers encrypted at rest (AES-256 via `card_number_encryption_key` env var)
- Logs always use masked references — last 4 digits only
- Stack traces never returned in API responses
- Audit logs are append-only — no update or delete operations on `audit_logs`

### Rate Limiting

- SlowAPI middleware, configurable per-minute limit (default 60 req/min)
- Auth endpoints limited more aggressively (10 req/min)

---

## 11. Database Design

### Schema Summary

| Table | Purpose |
|---|---|
| `accounts` | Holder identity, balances, limits, KYC |
| `cards` | Card credentials, status, lockout |
| `sessions` | JWT session tracking with jti |
| `transactions` | Immutable ledger of all financial events |
| `atm_terminals` | Physical terminal state and statistics |
| `cash_cassettes` | Per-denomination note inventory |
| `audit_logs` | Append-only security and operations trail |
| `admin_users` | Admin authentication (separate from card auth) |

### Indexing Strategy

- `accounts.account_number` — UNIQUE index
- `cards.card_number` — UNIQUE index
- `sessions.jti` — UNIQUE index (hot path on every request)
- `transactions(account_id, created_at DESC)` — composite index for history queries
- `audit_logs(atm_id, created_at)` — for per-terminal reporting
- `transactions.transaction_type` — for type-filtered reporting

### Multi-DB Support

- **Development/Testing**: SQLite with `PRAGMA foreign_keys=ON`, WAL mode enabled
- **Production**: PostgreSQL with proper `DECIMAL(15,2)` columns, connection pooling

---

## 12. API Design

### Base Standards

- Every response is a structured JSON object — never a raw string or bare list
- Success responses include `status`, `data`, and optionally `meta` (pagination)
- Error responses include `error_code`, `message`, and `http_status`
- All endpoints return proper HTTP status codes (no 200 for errors)
- Authentication via `Authorization: Bearer <token>` header

### Endpoint Map

```
POST   /auth/login
POST   /auth/logout

GET    /account/balance

POST   /transaction/withdraw
POST   /transaction/deposit
POST   /transaction/transfer
GET    /transaction/history
GET    /transaction/statement

GET    /atm/{atm_id}/status

GET    /health
```

---

## 13. Error Handling

Every domain failure has its **own exception class** inheriting from `ATMBaseException`:

```python
ATMBaseException
├── InvalidCardNumberError      400
├── InvalidPINError             401
├── CardBlockedError            403
├── CardExpiredError            403
├── CardLostOrStolenError       403
├── AccountLockedError          403
├── SessionExpiredError         401
├── SessionNotFoundError        401
├── ConcurrentSessionError      409
├── AccountNotFoundError        404
├── AccountFrozenError          403
├── InsufficientFundsError      422
├── DailyLimitExceededError     422
├── TransactionLimitExceededError 422
├── InvalidDenominationError    400
├── ATMOutOfCashError           503
├── InsufficientATMCashError    503
├── ATMOfflineError             503
├── ATMNotFoundError            404
├── TransferRollbackError       500
├── AdminNotFoundError          404
├── AdminAuthError              401
├── DatabaseError               500
└── SystemError                 500
```

A single FastAPI exception handler converts these to structured JSON responses automatically.

---

## 14. Logging and Observability

### Structured Logs (structlog)

Every log record must include:
- `timestamp` (ISO-8601 UTC)
- `event` (snake_case event name e.g. `withdrawal_success`)
- `atm_id` (when available)
- `masked_account_ref` (last 4 digits only)
- `severity` (info / warning / critical)
- Arbitrary key-value context (amount, duration, etc.)

### Audit Log Table

```
audit_logs
├── id                 UUID PK
├── event_type         VARCHAR(100)
├── atm_id             FK → atm_terminals.id (nullable)
├── masked_account_ref VARCHAR(50)
├── masked_card_ref    VARCHAR(50)
├── description        TEXT
├── severity           ENUM(info, warning, critical)
├── ip_address         VARCHAR(45)
├── metadata           JSON
└── created_at         TIMESTAMPTZ  -- no updated_at; append-only
```

No `UPDATE` or `DELETE` operations are ever performed on `audit_logs`.

---

## 15. Technology Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.11+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.x (declarative) |
| Validation | Pydantic v2 |
| Auth | python-jose (JWT), passlib (Argon2/bcrypt) |
| Rate Limiting | SlowAPI |
| Logging | structlog |
| DB (dev) | SQLite with WAL mode |
| DB (prod) | PostgreSQL 15+ |
| Migrations | Alembic |
| Testing | pytest, pytest-asyncio, httpx |
| Load Testing | Locust |
| Containers | Docker, docker-compose |
| Docs | Swagger UI (built-in FastAPI) |

---

## 16. Testing Requirements

### Unit and Integration Tests

| Scenario | What to verify |
|---|---|
| Correct PIN auth | Session created, token returned |
| 3 wrong PINs | Card locked, persists after restart |
| Withdrawal success | Balance deducted, cassette deducted, txn created |
| Insufficient funds | 422, no state change |
| Daily limit hit | 422, used counter not incremented |
| Non-denomination amount | 400 |
| ATM out of cash | 503 |
| Deposit with hold | total_balance up, available_balance unchanged until hold date |
| Transfer rollback | Source balance restored if credit fails |
| Session timeout | 401 after 90s of inactivity |
| Admin role enforcement | Auditor cannot freeze accounts |
| Concurrent withdrawal | See load test below |

### Load Test (Locust)

Simulate **100 concurrent users** all attempting withdrawal from the **same account**. After all complete:
- `account.available_balance >= 0` always
- Total debited = sum of all successful transaction amounts
- No duplicate transactions
- No deadlock errors

---

## 17. Deployment

### Environment Variables

```
APP_NAME
APP_ENV                   (development | production | testing)
SECRET_KEY                (JWT signing secret)
ALGORITHM                 (HS256)
DATABASE_URL
ACCESS_TOKEN_EXPIRE_MINUTES
SESSION_INACTIVITY_SECONDS
PIN_HASH_ALGORITHM        (argon2 | bcrypt)
MAX_PIN_ATTEMPTS
CARD_NUMBER_ENCRYPTION_KEY
DEFAULT_DENOMINATION
LOW_CASH_THRESHOLD
DEFAULT_DAILY_WITHDRAWAL_LIMIT
MAX_SINGLE_WITHDRAWAL
MAX_SINGLE_DEPOSIT
DEPOSIT_HOLD_DAYS
RATE_LIMIT_PER_MINUTE
ADMIN_SECRET_KEY
LOG_LEVEL
LOG_FORMAT                (json | console)
```

### Docker

Provide:
- `Dockerfile` for the API service
- `docker-compose.yml` with API + PostgreSQL + (optional) Redis for future session caching
- Health check endpoint at `GET /health`
- Entrypoint that runs Alembic migrations before starting the server

---

## 18. Documentation Deliverables

- `README.md` — quickstart, environment setup, running locally and with Docker
- `docs/architecture.md` — component diagram, data flow, design decisions
- `docs/api.md` — all endpoints with request/response examples
- `docs/schema.md` — ERD and table descriptions
- `docs/deployment.md` — Docker, environment variables, migration steps
- `docs/testing.md` — how to run unit tests and load tests
- Swagger UI auto-generated at `/docs`
- Seed data script that creates sample ATMs, accounts, cards, and an admin user

---

## 19. Project Structure

```
atm-banking-system/
├── app/
│   ├── main.py                 # App factory, middleware, routers
│   ├── config.py               # Pydantic Settings
│   ├── database.py             # Engine, session factory, Base
│   ├── dependencies.py         # FastAPI Depends helpers
│   ├── core/
│   │   ├── exceptions.py       # Full exception hierarchy
│   │   ├── security.py         # Hashing, JWT, masking
│   │   ├── logging_config.py   # structlog setup
│   │   └── luhn.py             # Luhn algorithm
│   ├── models/                 # SQLAlchemy ORM models
│   ├── routers/                # FastAPI routers (auth, account, transaction, atm, admin)
│   ├── services/               # Business logic (auth, withdrawal, deposit, transfer, fraud, admin)
│   ├── schemas/                # Pydantic request/response schemas
│   └── middleware/             # Rate limiter
├── migrations/                 # Alembic
├── tests/
│   ├── unit/
│   ├── integration/
│   └── load/                   # Locust scripts
├── scripts/
│   └── seed_data.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── prompt.md                   # This file
└── README.md
```

---

## 20. Non-Negotiable Quality Rules

1. **No plaintext secrets** in source code — all via environment variables
2. **No raw SQL** — SQLAlchemy ORM only (except for performance-critical read queries, which must be reviewed)
3. **No silent failures** — every exception either raises a typed domain error or is logged at `critical` level
4. **No state mutation without audit** — every balance change has a corresponding `transactions` row and `audit_logs` row
5. **No card number or PIN in any log line** — use masked references everywhere
6. **No `200 OK` for errors** — use correct HTTP status codes
7. **No balance operations without row-level locking** — use `SELECT ... FOR UPDATE` on cash-sensitive rows
8. **Every new feature needs a test** — untested code is not considered delivered
