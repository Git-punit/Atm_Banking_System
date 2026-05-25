# Domain-Specific Coding Prompt: Fintech — Real-Time Fraud Detection Pipeline

## Domain
**Financial Technology (Fintech) — Transaction Fraud Detection**

---

## Background

You are a backend engineer at a mid-sized digital payments company. The risk team has asked you to build a **real-time fraud detection pipeline** that evaluates incoming payment transactions and flags suspicious ones before they are settled.

The system must be self-contained, production-oriented, and written entirely in **Python**. It will be integrated into a larger microservices architecture later, but for now it must run as a standalone module with a clean public API.

---

## Task

Implement a `FraudDetectionPipeline` class in Python that:

1. Accepts a stream of payment transactions (as dictionaries or dataclass instances)
2. Runs each transaction through a configurable set of fraud-detection rules
3. Returns a structured result indicating whether the transaction is approved, flagged, or blocked
4. Maintains an in-memory transaction history per user to support velocity and pattern checks
5. Produces a structured audit log entry for every decision made

---

## Input Format

Each transaction is a dictionary with the following fields:

```python
{
    "transaction_id": str,        # UUID string, unique per transaction
    "user_id": str,               # Unique user identifier
    "amount": float,              # Transaction amount in USD (positive)
    "currency": str,              # ISO 4217 currency code, e.g. "USD"
    "merchant_category": str,     # MCC string, e.g. "grocery", "electronics", "travel"
    "country_code": str,          # ISO 3166-1 alpha-2, e.g. "US", "NG", "RU"
    "timestamp": str,             # ISO 8601 datetime string, e.g. "2024-06-01T14:32:00Z"
    "payment_method": str,        # "card", "wallet", "bank_transfer"
    "is_international": bool,     # True if cross-border transaction
}
```

---

## Constraints

### Constraint 1 — Rule Engine (Mandatory)
Implement **at least five** of the following fraud rules. Each rule must be a separate, independently callable method:

| Rule ID | Rule Name              | Description                                                                 |
|---------|------------------------|-----------------------------------------------------------------------------|
| R1      | High Amount            | Flag transactions above $10,000                                             |
| R2      | Velocity Check         | Flag if user has made more than 5 transactions in the last 60 seconds       |
| R3      | Geographic Anomaly     | Block if transaction originates from a high-risk country (configurable list)|
| R4      | Unusual Hour           | Flag transactions between 01:00–05:00 UTC                                   |
| R5      | Merchant Category Risk | Flag transactions in high-risk MCC categories (e.g., "gambling", "crypto")  |
| R6      | Repeated Amount        | Flag if the same amount appears more than 3 times in the last 10 minutes    |
| R7      | Currency Mismatch      | Flag if currency does not match the user's home currency (configurable)      |

### Constraint 2 — Decision Output (Mandatory)
Every call to `evaluate(transaction)` must return a `FraudDecision` object (dataclass or TypedDict) with **exactly** these fields:

```python
{
    "transaction_id": str,
    "decision": str,           # "approved" | "flagged" | "blocked"
    "risk_score": float,       # 0.0 – 100.0
    "triggered_rules": list[str],   # list of rule IDs that fired
    "audit_log": dict,         # structured audit entry (see Constraint 4)
    "evaluated_at": str,       # ISO 8601 timestamp of evaluation
}
```

### Constraint 3 — Risk Scoring (Mandatory)
Compute a `risk_score` between 0.0 and 100.0 using a **weighted scoring model**:

- Each rule that fires contributes a configurable weight to the score
- Default weights must be defined as a class-level constant
- Score must be capped at 100.0
- Decision thresholds:
  - `risk_score < 40`  → `"approved"`
  - `40 ≤ risk_score < 75` → `"flagged"`
  - `risk_score ≥ 75` → `"blocked"`

### Constraint 4 — Audit Log (Mandatory)
The `audit_log` field in every decision must be a dictionary containing:

```python
{
    "pipeline_version": str,
    "rules_evaluated": list[str],   # all rules that were checked
    "rules_triggered": list[str],   # rules that fired
    "risk_score": float,
    "decision": str,
    "user_id": str,
    "transaction_id": str,
    "timestamp": str,
    "metadata": dict,               # any extra context (e.g., velocity count, country)
}
```

### Constraint 5 — Configuration (Mandatory)
The pipeline must accept a `config` dictionary at instantiation time that allows overriding:

- `high_risk_countries`: list of ISO country codes
- `high_risk_mcc`: list of merchant category strings
- `rule_weights`: dict mapping rule ID → float weight
- `velocity_window_seconds`: int (default 60)
- `velocity_max_count`: int (default 5)
- `user_home_currency`: dict mapping user_id → currency code

### Constraint 6 — Error Handling (Mandatory)
- Raise a `ValueError` with a descriptive message for any malformed transaction (missing fields, wrong types, negative amount, invalid ISO codes)
- Never raise unhandled exceptions during rule evaluation — catch and log rule-level errors internally
- Invalid timestamps must raise `ValueError`, not silently pass

### Constraint 7 — Formatting & Code Quality (Mandatory)
- All public methods must have **Google-style docstrings**
- Type hints on every function signature
- No global mutable state
- The class must be importable and usable without side effects on import
- Include a `if __name__ == "__main__":` block with at least 3 demonstration transactions

---

## Expected Usage

```python
pipeline = FraudDetectionPipeline(config={
    "high_risk_countries": ["NG", "RU", "KP"],
    "high_risk_mcc": ["gambling", "crypto", "adult"],
    "rule_weights": {
        "R1": 30.0, "R2": 25.0, "R3": 40.0,
        "R4": 15.0, "R5": 20.0, "R6": 20.0, "R7": 10.0,
    },
    "velocity_window_seconds": 60,
    "velocity_max_count": 5,
    "user_home_currency": {"user_001": "USD", "user_002": "GBP"},
})

decision = pipeline.evaluate({
    "transaction_id": "txn-abc-123",
    "user_id": "user_001",
    "amount": 12000.0,
    "currency": "USD",
    "merchant_category": "electronics",
    "country_code": "US",
    "timestamp": "2024-06-01T03:15:00Z",
    "payment_method": "card",
    "is_international": False,
})

print(decision)
# FraudDecision(decision='blocked', risk_score=45.0, triggered_rules=['R1', 'R4'], ...)
```

---

## Evaluation Criteria

Your solution will be assessed on:

| Criterion                        | Weight |
|----------------------------------|--------|
| All 5+ rules correctly implemented | 25%  |
| Correct risk scoring & thresholds  | 20%  |
| Proper error handling              | 15%  |
| Audit log completeness             | 15%  |
| Code quality & docstrings          | 15%  |
| Configuration flexibility          | 10%  |

---

## Deliverable

A single Python file `fraud_detection.py` that can be run directly and imported as a module.
