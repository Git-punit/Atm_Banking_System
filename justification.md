# Justification: Side-by-Side LLM Response Evaluation

## Prompt Under Evaluation
**Real-Time Fraud Detection Pipeline** (see `prompt.md`)

---

## Evaluation Framework

This document provides a structured methodology for comparing two LLM-generated responses (Response A and Response B) against the golden reference solution (`golden_response.py`). Each dimension is scored 1–5.

---

## Side-by-Side Analysis

### Dimension 1 — Rule Engine Completeness

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| Number of rules implemented | _fill after evaluation_ | _fill after evaluation_ |
| Rules are independent methods | ✓ / ✗ | ✓ / ✗ |
| R1 High Amount correct | ✓ / ✗ | ✓ / ✗ |
| R2 Velocity Check uses time window | ✓ / ✗ | ✓ / ✗ |
| R3 Geographic Anomaly uses config list | ✓ / ✗ | ✓ / ✗ |
| R4 Unusual Hour checks UTC 01–05 | ✓ / ✗ | ✓ / ✗ |
| R5 Merchant Category uses config list | ✓ / ✗ | ✓ / ✗ |
| R6 Repeated Amount uses 10-min window | ✓ / ✗ | ✓ / ✗ |
| R7 Currency Mismatch uses user map | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

**Notes:**
> _Evaluator fills in observations here after running both responses._

---

### Dimension 2 — Decision Output Structure

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| Returns `FraudDecision` dataclass/TypedDict | ✓ / ✗ | ✓ / ✗ |
| All 6 required fields present | ✓ / ✗ | ✓ / ✗ |
| `decision` is one of approved/flagged/blocked | ✓ / ✗ | ✓ / ✗ |
| `risk_score` is float in [0.0, 100.0] | ✓ / ✗ | ✓ / ✗ |
| `triggered_rules` is a list of rule IDs | ✓ / ✗ | ✓ / ✗ |
| `evaluated_at` is ISO 8601 string | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

### Dimension 3 — Risk Scoring Model

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| Weighted scoring implemented | ✓ / ✗ | ✓ / ✗ |
| Weights defined as class-level constant | ✓ / ✗ | ✓ / ✗ |
| Score capped at 100.0 | ✓ / ✗ | ✓ / ✗ |
| Correct threshold: <40 → approved | ✓ / ✗ | ✓ / ✗ |
| Correct threshold: 40–74 → flagged | ✓ / ✗ | ✓ / ✗ |
| Correct threshold: ≥75 → blocked | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

### Dimension 4 — Audit Log Completeness

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| `pipeline_version` present | ✓ / ✗ | ✓ / ✗ |
| `rules_evaluated` (all checked) present | ✓ / ✗ | ✓ / ✗ |
| `rules_triggered` (fired only) present | ✓ / ✗ | ✓ / ✗ |
| `metadata` dict with context | ✓ / ✗ | ✓ / ✗ |
| Audit log matches decision output | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

### Dimension 5 — Configuration Flexibility

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| `config` accepted at `__init__` | ✓ / ✗ | ✓ / ✗ |
| `high_risk_countries` overridable | ✓ / ✗ | ✓ / ✗ |
| `high_risk_mcc` overridable | ✓ / ✗ | ✓ / ✗ |
| `rule_weights` overridable | ✓ / ✗ | ✓ / ✗ |
| `velocity_window_seconds` overridable | ✓ / ✗ | ✓ / ✗ |
| `user_home_currency` map supported | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

### Dimension 6 — Error Handling

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| Missing fields raise `ValueError` | ✓ / ✗ | ✓ / ✗ |
| Negative amount raises `ValueError` | ✓ / ✗ | ✓ / ✗ |
| Invalid timestamp raises `ValueError` | ✓ / ✗ | ✓ / ✗ |
| Rule-level errors caught internally | ✓ / ✗ | ✓ / ✗ |
| No unhandled exceptions on bad input | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

### Dimension 7 — Code Quality & Formatting

| Criterion | Response A | Response B |
|-----------|-----------|-----------|
| Google-style docstrings on all public methods | ✓ / ✗ | ✓ / ✗ |
| Type hints on every function signature | ✓ / ✗ | ✓ / ✗ |
| No global mutable state | ✓ / ✗ | ✓ / ✗ |
| Importable without side effects | ✓ / ✗ | ✓ / ✗ |
| `__main__` block with 3+ demo transactions | ✓ / ✗ | ✓ / ✗ |
| Readable variable/method naming | ✓ / ✗ | ✓ / ✗ |
| Logical code organisation | ✓ / ✗ | ✓ / ✗ |
| **Score (1–5)** | | |

---

## Strengths and Weaknesses

### Response A

**Strengths:**
- _Evaluator fills in after assessment_
- e.g., "Correctly implements all 7 rules with clean separation"
- e.g., "Weighted scoring model is accurate and well-documented"

**Weaknesses:**
- _Evaluator fills in after assessment_
- e.g., "Audit log missing `metadata` field"
- e.g., "No error handling for invalid ISO country codes"

---

### Response B

**Strengths:**
- _Evaluator fills in after assessment_
- e.g., "Strong error handling with descriptive messages"
- e.g., "Configuration is fully flexible and well-defaulted"

**Weaknesses:**
- _Evaluator fills in after assessment_
- e.g., "Risk score not capped at 100.0"
- e.g., "Velocity check uses count only, ignores time window"

---

## Scoring Summary

| Dimension | Weight | Response A Score | Response B Score |
|-----------|--------|-----------------|-----------------|
| Rule Engine Completeness | 25% | /5 | /5 |
| Decision Output Structure | 15% | /5 | /5 |
| Risk Scoring Model | 20% | /5 | /5 |
| Audit Log Completeness | 15% | /5 | /5 |
| Configuration Flexibility | 10% | /5 | /5 |
| Error Handling | 10% | /5 | /5 |
| Code Quality & Formatting | 5% | /5 | /5 |
| **Weighted Total** | 100% | **/5** | **/5** |

### Weighted Score Calculation

```
Weighted Score = Σ (dimension_score × dimension_weight)
```

---

## Final Verdict

| | Response A | Response B |
|--|-----------|-----------|
| **Weighted Score** | _/5_ | _/5_ |
| **Winner** | ✓ / ✗ | ✓ / ✗ |

### Verdict Narrative

> _Evaluator writes 3–5 sentences here summarising which response better satisfies the prompt, why, and what the key differentiating factors were._
>
> Example: "Response B is the stronger solution. It correctly implements all 7 fraud rules as independent methods, produces a fully compliant `FraudDecision` output, and handles all specified error cases with descriptive `ValueError` messages. Response A's risk scoring is accurate but its audit log omits the `metadata` field and the velocity check ignores the time window, making it non-compliant with Constraints 2 and 4. Response B's code quality is also higher, with complete Google-style docstrings and a clean `__main__` demonstration block."

---

## Evaluation Methodology Notes

1. **Automated checks first** — run `golden_response.py` test cases against each response to catch objective failures before subjective review.
2. **Constraint compliance is binary** — a constraint is either met or not; partial credit is only awarded in the scoring table, not in the compliance checklist.
3. **Implicit quality matters** — two responses can both pass all explicit constraints but differ significantly in readability, maintainability, and edge-case handling. These are captured in Dimension 7.
4. **Reproducibility** — this framework should produce the same verdict when applied by two independent evaluators, given the same responses.
