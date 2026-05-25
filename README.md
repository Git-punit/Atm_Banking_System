# LLM Evaluation — Real-Time Fraud Detection Pipeline

This repo contains a coding prompt I wrote for a fintech fraud detection task, the golden reference implementation, and a structured comparison of how GPT-4o and Claude 3.5 Sonnet responded to it.

The evaluation uses the **RLHF seven-dimension framework** (Correctness, Relevance, Completeness, Style & Presentation, Coherence, Helpfulness, Creativity), each scored 1–5.

---

## Files

```
├── prompt.md            — the coding challenge given to both LLMs
├── golden_response.py   — the reference implementation
├── justification.md     — side-by-side evaluation of GPT-4o vs Claude 3.5 Sonnet
└── README.md            — this file
```

---

## The prompt

The challenge asks for a `FraudDetectionPipeline` class in Python that:

- Evaluates payment transactions against 7 configurable fraud rules (high amount, velocity, geographic anomaly, unusual hour, merchant category, repeated amount, currency mismatch)
- Computes a weighted risk score (0–100) and maps it to `approved` / `flagged` / `blocked`
- Returns a `FraudDecision` dataclass with a full audit log on every call
- Accepts a `config` dict at init to override all defaults
- Raises `ValueError` with descriptive messages on bad input
- Catches rule-level exceptions internally so one broken rule can't kill the pipeline
- Uses Google-style docstrings and type hints throughout

No external dependencies — standard library only.

---

## Running the reference implementation

Requires Python 3.10 or later.

```bash
python3 golden_response.py
```

Expected output:

```
INFO FraudDetectionPipeline initialised (version=1.0.0)
======================================================================
  Fraud Detection Pipeline v1.0.0 — Demo
======================================================================

Transaction : txn-001
Decision    : FLAGGED
Risk Score  : 45.0 / 100.0
Rules Fired : ['R1', 'R4']

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
Caught expected error: 'amount' must be positive, got -50.0

--- Velocity Check Demo (6 transactions, same user, same timestamp) ---
  txn 1: decision=approved, score=0, rules=[]
  txn 2: decision=approved, score=0, rules=[]
  txn 3: decision=approved, score=0, rules=[]
  txn 4: decision=approved, score=20.0, rules=['R6']
  txn 5: decision=approved, score=20.0, rules=['R6']
  txn 6: decision=flagged, score=45.0, rules=['R2', 'R6']
```

You can also import it directly:

```python
from golden_response import FraudDetectionPipeline, FraudDecision

pipeline = FraudDetectionPipeline(config={
    "high_risk_countries": ["NG", "RU"],
    "user_home_currency": {"alice": "USD"},
})

result = pipeline.evaluate({
    "transaction_id": "txn-xyz",
    "user_id": "alice",
    "amount": 500.0,
    "currency": "USD",
    "merchant_category": "grocery",
    "country_code": "US",
    "timestamp": "2024-06-01T10:00:00Z",
    "payment_method": "card",
    "is_international": False,
})

print(result.decision)     # approved
print(result.risk_score)   # 0.0
```

---

## Evaluation results summary

| Dimension | GPT-4o | Claude 3.5 Sonnet |
|-----------|--------|-------------------|
| Correctness | 4/5 | 4/5 |
| Relevance | 5/5 | 5/5 |
| Completeness | 4/5 | 4/5 |
| Style & Presentation | 4/5 | 5/5 |
| Coherence | 5/5 | 5/5 |
| Helpfulness | 4/5 | 5/5 |
| Creativity | 3/5 | 4/5 |
| **Average** | **4.14 / 5** | **4.57 / 5** |

**Winner: Claude 3.5 Sonnet**

Both models got one rule wrong — GPT-4o's velocity check (R2) ignored the time window, and Claude's currency mismatch (R7) flagged users with no home currency configured instead of skipping them. Claude's overall code quality was noticeably higher: better docstrings, `frozenset` for O(1) lookups, a `clear_history()` utility, and a more useful demo block.

Full analysis is in `justification.md`.

---

## Bugs found in each response

| Bug | GPT-4o | Claude 3.5 Sonnet |
|-----|--------|-------------------|
| R2 velocity check filters by time window | ✗ counts all history | ✓ correct |
| R7 skips users with no home currency | ✓ correct | ✗ flags them instead |
| Score capped at 100.0 | ✓ | ✓ |
| History updated after evaluation | ✓ | ✓ |
| Rule exceptions caught per-rule | ✓ | ✓ |

---

## Key design decisions in the golden response

**History updated after evaluation** — if you update history before running the rules, the current transaction counts toward its own velocity and repeated-amount checks. That's wrong.

**Rule errors caught per-rule** — one broken rule shouldn't stop the whole pipeline. In payments, failing open is usually safer than failing closed.

**`frozenset` for country/MCC lists** — O(1) membership checks, immutable after init.

**R7 skips unconfigured users** — flagging every transaction from users not in the home currency map would generate too much noise to be useful.

**`TransactionValidationError(ValueError)`** — subclasses `ValueError` so callers can catch either.

**"Z" → "+00:00" normalisation** — `fromisoformat()` didn't handle the "Z" suffix until Python 3.11.

---

## How to run your own evaluation

1. Copy the contents of `prompt.md` and paste it into any LLM
2. Save the response as `response.py`
3. Run it: `python3 response.py`
4. Check it imports cleanly: `python3 -c "import response"`
5. Score it against the seven dimensions in `justification.md`
6. Compare your scores to the GPT-4o and Claude 3.5 Sonnet results
