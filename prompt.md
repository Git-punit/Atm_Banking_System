# Coding Challenge: Build a Real-Time Fraud Detection Pipeline

## Background

I'm on the risk engineering team at a payments company. We process a few million transactions a day and our fraud checks are currently scattered across three different services — it's hard to maintain and even harder to extend. I'm consolidating the core detection logic into a single, well-structured Python module that the rest of the team can understand and build on without needing to ask me every time.

This is the prompt I'd give to a new backend engineer joining the team. It's realistic, it has real constraints, and there's no hand-holding.

---

## What you need to build

Write a `FraudDetectionPipeline` class in Python. The class takes in payment transactions one at a time, runs them through a set of fraud rules, and tells you whether to approve, flag, or block the transaction.

It needs to be a standalone Python file — no external dependencies, just the standard library. We'll wire it into our actual services later, but for now it just needs to work on its own.

Here's what the class needs to do:

- Accept a transaction as a plain dictionary
- Run it through a configurable set of fraud detection rules
- Return a structured decision object every time
- Keep a per-user transaction history in memory so rules like velocity checks actually work
- Write an audit log entry for every decision — compliance requires it

---

## Transaction format

Every transaction coming in looks like this:

```python
{
    "transaction_id": str,      # unique ID, usually a UUID
    "user_id": str,             # who made the transaction
    "amount": float,            # in USD, always positive
    "currency": str,            # ISO 4217, e.g. "USD", "GBP"
    "merchant_category": str,   # e.g. "grocery", "electronics", "gambling"
    "country_code": str,        # ISO 3166-1 alpha-2, e.g. "US", "NG"
    "timestamp": str,           # ISO 8601, e.g. "2024-06-01T14:32:00Z"
    "payment_method": str,      # "card", "wallet", or "bank_transfer"
    "is_international": bool,   # True if it crossed a border
}
```

---

## The fraud rules

Implement **at least five** of these. Each rule must be its own method — don't dump everything into one big function.

| ID | Name | What it checks |
|----|------|----------------|
| R1 | High Amount | Amount over $10,000 |
| R2 | Velocity Check | More than 5 transactions from the same user in the last 60 seconds |
| R3 | Geographic Anomaly | Transaction from a high-risk country (list is configurable) |
| R4 | Unusual Hour | Transaction between 1am and 5am UTC |
| R5 | Merchant Category Risk | High-risk MCC like "gambling" or "crypto" (list is configurable) |
| R6 | Repeated Amount | Same exact amount more than 3 times in the last 10 minutes |
| R7 | Currency Mismatch | Currency doesn't match the user's home currency (configurable per user) |

---

## What `evaluate()` must return

Every call to `evaluate(transaction)` must return a `FraudDecision` — either a dataclass or TypedDict, your choice. It needs exactly these fields:

```python
{
    "transaction_id": str,
    "decision": str,              # "approved", "flagged", or "blocked"
    "risk_score": float,          # between 0.0 and 100.0
    "triggered_rules": list[str], # e.g. ["R1", "R4"]
    "audit_log": dict,            # see the audit log section below
    "evaluated_at": str,          # ISO 8601 UTC timestamp of when the check ran
}
```

---

## Risk scoring

Don't just count rules — use a weighted model. Each rule that fires adds its weight to the score. The weights must be defined as a class-level constant so they're easy to find and change. Cap the score at 100.0.

Decision thresholds:
- Score under 40 → `"approved"`
- Score 40 to 74 → `"flagged"`
- Score 75 and above → `"blocked"`

---

## Audit log

The `audit_log` field inside every decision must be a dict containing at least:

```python
{
    "pipeline_version": str,
    "rules_evaluated": list[str],  # every rule that ran
    "rules_triggered": list[str],  # only the ones that fired
    "risk_score": float,
    "decision": str,
    "user_id": str,
    "transaction_id": str,
    "timestamp": str,
    "metadata": dict,              # extra context — velocity count, country, etc.
}
```

---

## Configuration

The pipeline must accept a `config` dict when you create it. These keys need to be overridable:

- `high_risk_countries` — list of ISO 3166-1 alpha-2 country codes
- `high_risk_mcc` — list of merchant category strings
- `rule_weights` — dict of rule ID to weight (only override what you need)
- `velocity_window_seconds` — default 60
- `velocity_max_count` — default 5
- `user_home_currency` — dict of user_id to ISO 4217 currency code

If a key isn't provided, fall back to sensible defaults.

---

## Error handling

- If a transaction is missing a field, has the wrong type, has a negative amount, or has an invalid ISO code — raise a `ValueError` with a message that actually explains what's wrong
- If a rule itself throws an exception during evaluation, catch it, log a warning, and keep going. One broken rule shouldn't take down the whole pipeline
- Bad timestamps must raise `ValueError`, not silently produce garbage

---

## Code quality requirements

- Google-style docstrings on every public method
- Type hints on every function signature
- No global mutable state — the class must be safe to instantiate multiple times
- The file must be importable without any side effects
- Include a `if __name__ == "__main__":` block that demonstrates at least 3 different transactions (one approved, one flagged, one that hits a validation error)

---

## Example usage

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

print(decision.decision)         # "flagged"
print(decision.risk_score)       # 45.0
print(decision.triggered_rules)  # ["R1", "R4"]
```

---

## Grading

| What I'm looking at | Weight |
|---------------------|--------|
| Rules implemented correctly and independently | 25% |
| Risk scoring and thresholds | 20% |
| Error handling | 15% |
| Audit log completeness | 15% |
| Code quality and docstrings | 15% |
| Config flexibility | 10% |

---

## Deliverable

One Python file called `fraud_detection.py`. It should run directly and also be importable as a module with no side effects.
