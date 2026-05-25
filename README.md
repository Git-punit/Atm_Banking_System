# LLM Evaluation Repository — Real-Time Fraud Detection Pipeline

A structured benchmark for comparing LLM-generated code solutions against a golden reference implementation. The domain is **Fintech — Payment Transaction Fraud Detection**.

---

## Repository Structure

```
llm-eval-repo/
├── prompt.md            # The domain-specific coding prompt given to LLMs
├── justification.md     # Side-by-side evaluation framework and scoring rubric
├── golden_response.py   # Production-quality reference implementation
└── README.md            # This file
```

---

## Project Overview

This repository contains everything needed to:

1. **Give a coding prompt to any LLM** (`prompt.md`) and collect its response
2. **Score the response** against the golden solution using the structured rubric in `justification.md`
3. **Compare two LLM responses** side-by-side to determine which better satisfies the prompt

### The Prompt Domain

The prompt asks an LLM to implement a `FraudDetectionPipeline` class in Python that:

- Evaluates payment transactions against **7 configurable fraud rules**
- Computes a **weighted risk score** (0–100) and maps it to a decision (`approved` / `flagged` / `blocked`)
- Returns a structured `FraudDecision` dataclass with a full **audit log**
- Accepts a **config dictionary** at instantiation to override all defaults
- Handles all **error cases** with descriptive `ValueError` exceptions
- Follows **Google-style docstrings** and full type hints throughout

---

## Running the Golden Response

### Prerequisites

Python 3.10 or later. No third-party dependencies — the golden response uses only the standard library.

```bash
python --version   # must be 3.10+
```

### Run the demo

```bash
python golden_response.py
```

Expected output:

```
======================================================================
  Fraud Detection Pipeline v1.0.0 — Demo
======================================================================

Transaction : txn-001
Decision    : FLAGGED
Risk Score  : 45.0 / 100.0
Rules Fired : ['R1', 'R4']
Evaluated At: 2024-...

Transaction : txn-002
Decision    : FLAGGED
Risk Score  : 40.0 / 100.0
Rules Fired : ['R3']

Transaction : txn-003
Decision    : APPROVED
Risk Score  : 0.0 / 100.0
Rules Fired : ['none']

Transaction : txn-004
Decision    : APPROVED
Risk Score  : 30.0 / 100.0
Rules Fired : ['R5', 'R7']

--- Validation Error Demo ---
Caught expected error: Field 'amount' must be positive, got -50.0

--- Velocity Check Demo (6 rapid transactions) ---
  txn 1: decision=approved, score=0, rules=[]
  txn 2: decision=approved, score=0, rules=[]
  txn 3: decision=approved, score=0, rules=[]
  txn 4: decision=approved, score=20.0, rules=['R6']
  txn 5: decision=approved, score=20.0, rules=['R6']
  txn 6: decision=flagged, score=45.0, rules=['R2', 'R6']
```

### Import as a module

```python
from golden_response import FraudDetectionPipeline, FraudDecision

pipeline = FraudDetectionPipeline(config={
    "high_risk_countries": ["NG", "RU"],
    "user_home_currency": {"u1": "USD"},
})

decision: FraudDecision = pipeline.evaluate({
    "transaction_id": "txn-xyz",
    "user_id": "u1",
    "amount": 500.0,
    "currency": "USD",
    "merchant_category": "grocery",
    "country_code": "US",
    "timestamp": "2024-06-01T10:00:00Z",
    "payment_method": "card",
    "is_international": False,
})

print(decision.decision)      # "approved"
print(decision.risk_score)    # 0.0
```

---

## Evaluation Methodology

### Step 1 — Collect LLM Responses

Submit `prompt.md` verbatim to two different LLMs (e.g., GPT-4o and Claude 3.5 Sonnet). Save each response as `response_a.py` and `response_b.py`.

### Step 2 — Automated Constraint Checks

Run each response against the following automated checks:

```bash
# Check that the module imports cleanly
python -c "import response_a"
python -c "import response_b"

# Run the demo block
python response_a.py
python response_b.py
```

Then manually verify each constraint from `prompt.md` using the checklist in `justification.md`.

### Step 3 — Score Each Dimension

Open `justification.md` and fill in the ✓/✗ cells for each dimension. Compute the weighted score using the formula at the bottom of the scoring table.

### Step 4 — Write the Verdict

Fill in the **Strengths and Weaknesses** sections and the **Final Verdict** narrative in `justification.md`.

### Scoring Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Rule Engine Completeness | 25% | Are all 5+ rules implemented correctly as independent methods? |
| Decision Output Structure | 15% | Does `FraudDecision` have all 6 required fields with correct types? |
| Risk Scoring Model | 20% | Is the weighted score correct, capped, and mapped to the right thresholds? |
| Audit Log Completeness | 15% | Does the audit log contain all required fields including `metadata`? |
| Configuration Flexibility | 10% | Can all config keys be overridden at instantiation? |
| Error Handling | 10% | Are all error cases caught with descriptive `ValueError` messages? |
| Code Quality & Formatting | 5% | Docstrings, type hints, no global state, clean `__main__` block? |

---

## Key Design Decisions in the Golden Response

| Decision | Rationale |
|----------|-----------|
| `defaultdict(list)` for history | Avoids `KeyError` on first access per user; no global state |
| Rule errors caught per-rule | A broken rule must not block the entire evaluation pipeline |
| History updated **after** evaluation | Prevents the current transaction from influencing its own velocity/repeat checks |
| `frozenset` for config lists | O(1) membership tests; immutable after construction |
| `TransactionValidationError(ValueError)` | Subclasses `ValueError` so callers can catch either |
| Timestamp normalisation (`Z` → `+00:00`) | Ensures Python < 3.11 compatibility without third-party libs |
| `min(raw_score, 100.0)` cap | Prevents score overflow when multiple high-weight rules fire simultaneously |

---

## Extending the Pipeline

To add a new rule:

1. Add a method `_rule_<name>(self, txn, ts) -> tuple[bool, dict]` following the existing pattern
2. Add the rule ID and default weight to `DEFAULT_RULE_WEIGHTS`
3. Register the method in the `rule_methods` dict inside `evaluate()`

No other changes are required.

---

## License

This repository is provided for LLM evaluation and benchmarking purposes.
