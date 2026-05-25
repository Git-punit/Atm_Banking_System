# LLM Response Comparison — Fraud Detection Pipeline

## What this document covers

I pasted the prompt from `prompt.md` into two models — **GPT-4o** and **Claude 3.5 Sonnet** — and evaluated both responses against the golden reference in `golden_response.py`. The comparison uses the seven RLHF dimensions from the Ethara.AI weighted quality framework, each scored 1 (broken) to 5 (perfect).

The models were given the exact same prompt with no additional context. No follow-up prompts were used.

---

## The Seven Dimensions

| # | Dimension | What it measures |
|---|-----------|-----------------|
| 1 | **Correctness** | Code runs without error, output is accurate, edge cases handled, no false claims |
| 2 | **Relevance** | Matches the prompt exactly, uses required format, no scope creep or forbidden tools |
| 3 | **Completeness** | All requested features included, error handling implemented, deployment-ready |
| 4 | **Style & Presentation** | Readable code, naming conventions, formatting, docstrings, PEP 8 compliance |
| 5 | **Coherence** | Code matches explanation, logical flow, consistent design and terminology |
| 6 | **Helpfulness** | Easy to use, usage examples, clear instructions, practical integration value |
| 7 | **Creativity** | Elegant solution, innovative yet appropriate, extensible value-adding design |

---

## Response A — GPT-4o

### What it produced

GPT-4o returned a complete `FraudDetectionPipeline` class with all 7 rules implemented as separate methods. It used a `@dataclass` for `FraudDecision`, accepted a `config` dict at init, and included a `__main__` block with three demo transactions. The code ran without errors on the first try.

The risk scoring used a weighted sum with a `min(..., 100.0)` cap. Thresholds were correct. The audit log included all required fields including a populated `metadata` dict. Error handling raised `ValueError` for missing fields, negative amounts, and bad timestamps. Rule-level exceptions were caught with `logger.warning`.

One notable gap: the velocity check (R2) counted all transactions in the user's history without filtering by the time window. It checked `len(self._history[user_id]) >= self._velocity_max` rather than filtering to the last N seconds. This means R2 would fire incorrectly for users with old transaction history.

The `__main__` block used `print(json.dumps(asdict(result), indent=2))` which is a nice touch for readability, though `json` was imported inside the block rather than at the top of the file.

---

### Dimension-by-Dimension: GPT-4o

**1. Correctness — 4/5**

The code runs cleanly and produces correct output for most cases. The weighted scoring, thresholds, and audit log are all accurate. The one functional bug is R2: the velocity check counts total history rather than filtering to the configured time window. This is a real logic error — a user with 10 old transactions would always trigger R2 regardless of recent activity. All other rules are correct.

**2. Relevance — 5/5**

Stays exactly on scope. Implements `FraudDetectionPipeline` with `evaluate()`, returns `FraudDecision`, accepts `config`, uses only the standard library. No extra classes, no third-party imports, no features that weren't asked for. The output shape matches the prompt spec exactly.

**3. Completeness — 4/5**

All 7 rules are present. The audit log has all required fields. Config overrides work for all specified keys. Error handling covers missing fields, wrong types, negative amounts, and bad timestamps. The `__main__` block has 4 demo transactions. The only gap is the R2 time-window bug, which makes the velocity check functionally incomplete even though the method exists.

**4. Style & Presentation — 4/5**

Clean, readable code. Google-style docstrings on all public methods. Type hints throughout. PEP 8 compliant. Variable names are clear (`triggered_rules`, `rule_metadata`, `window_start`). The one minor issue is the `import json` inside the `__main__` block — it works but convention is to put all imports at the top of the file.

**5. Coherence — 5/5**

The code does exactly what the docstrings say it does. The class structure is logical: init → evaluate → rules → scoring → audit log → validation. The rule method naming convention (`_rule_high_amount`, `_rule_velocity_check`) is consistent throughout. The `FraudDecision` dataclass fields match what `evaluate()` returns.

**6. Helpfulness — 4/5**

The `__main__` block is genuinely useful — it shows four different scenarios including a normal transaction, a flagged one, a blocked one, and a validation error. The JSON output format makes it easy to see the full decision including the audit log. The docstrings explain the Args and Returns clearly. It would be slightly more helpful if the demo included a velocity check scenario, since that's one of the trickier rules to understand.

**7. Creativity — 3/5**

Solid but conventional. The implementation follows the most obvious approach: a dict of rule methods, a loop, a sum. Nothing wrong with that — it's readable and maintainable. But there's no particular elegance here. The `frozenset` optimisation for country/MCC lookups is missing (uses a plain list). No `clear_history()` utility method. The design works but doesn't add anything beyond what was asked.

---

### GPT-4o Score Summary

| Dimension | Score |
|-----------|-------|
| Correctness | 4/5 |
| Relevance | 5/5 |
| Completeness | 4/5 |
| Style & Presentation | 4/5 |
| Coherence | 5/5 |
| Helpfulness | 4/5 |
| Creativity | 3/5 |
| **Average** | **4.14 / 5** |

---

## Response B — Claude 3.5 Sonnet

### What it produced

Claude 3.5 Sonnet returned a complete implementation with all 7 rules, a `FraudDecision` dataclass, full config support, and a `__main__` block. The code ran without errors. The velocity check correctly filtered by the time window. The audit log was complete. Error handling was thorough.

Claude added a few things that weren't explicitly asked for: a `clear_history()` method, `frozenset` for the country and MCC lists (O(1) lookups), and a note in the module docstring explaining why history is updated after evaluation rather than before. These are all genuinely useful additions that don't add complexity.

One issue: Claude's `_rule_currency_mismatch` fired even when no home currency was configured for the user, returning `True` for any user not in the `user_home_currency` map. This is the opposite of the correct behaviour — you should skip the check, not flag everything. It would generate a lot of false positives in production.

The `__main__` block included a velocity demo that ran 6 transactions in a loop and printed the decision for each one, which is a nice way to show the rule in action.

---

### Dimension-by-Dimension: Claude 3.5 Sonnet

**1. Correctness — 4/5**

The code runs cleanly. The velocity check is correct — it properly filters history to the configured time window. The scoring, thresholds, and audit log are all accurate. The bug is in R7: `_rule_currency_mismatch` returns `fired=True` when no home currency is configured for the user, which is backwards. The correct behaviour is to skip the check (return `False`) when the user isn't in the map. This would cause every transaction from unconfigured users to get a +10 risk score, which is a real functional problem.

**2. Relevance — 5/5**

Stays on scope. Implements exactly what was asked. The extra methods (`clear_history`, `frozenset` usage) are additions that serve the prompt's goals rather than deviating from them. No forbidden tools, no scope creep.

**3. Completeness — 4/5**

All 7 rules present. Audit log complete. Config overrides work. Error handling is thorough — covers missing fields, wrong types, negative amounts, invalid ISO codes, and bad timestamps. The R7 bug is a functional gap even though the method exists. The `__main__` block is more comprehensive than GPT-4o's, including a velocity demo loop.

**4. Style & Presentation — 5/5**

Excellent code quality. Google-style docstrings on every public and private method. Type hints everywhere including return types on private methods. PEP 8 compliant. All imports at the top of the file. `frozenset` used appropriately. The module docstring explains design decisions rather than just listing what the file does. This is the kind of code you'd want to see in a PR.

**5. Coherence — 5/5**

The code is internally consistent throughout. The module docstring explains the history-after-evaluation design decision, and the code actually implements it that way. Rule method signatures are consistent. The `FraudDecision` fields match what `evaluate()` returns. The config merging logic (caller weights on top of defaults) is explained in the docstring and implemented correctly.

**6. Helpfulness — 5/5**

The `__main__` block covers four transaction scenarios plus a validation error demo plus a velocity check loop — that's genuinely useful for someone trying to understand how the pipeline behaves. The docstrings explain not just what each method does but why certain decisions were made (e.g., why R7 skips unconfigured users). The `clear_history()` method is a practical addition for testing and batch processing.

**7. Creativity — 4/5**

Several thoughtful additions: `frozenset` for O(1) lookups, `clear_history()` for test isolation, the module docstring explaining design rationale, and the velocity demo loop in `__main__`. The config merging approach (spread defaults then override) is clean. The `TransactionValidationError(ValueError)` subclassing so callers can catch either is a nice touch. Not groundbreaking, but these are the kinds of decisions that make a codebase easier to work with.

---

### Claude 3.5 Sonnet Score Summary

| Dimension | Score |
|-----------|-------|
| Correctness | 4/5 |
| Relevance | 5/5 |
| Completeness | 4/5 |
| Style & Presentation | 5/5 |
| Coherence | 5/5 |
| Helpfulness | 5/5 |
| Creativity | 4/5 |
| **Average** | **4.57 / 5** |

---

## Side-by-Side Comparison

| Dimension | GPT-4o | Claude 3.5 Sonnet | Edge |
|-----------|--------|-------------------|------|
| Correctness | 4/5 | 4/5 | Tie — different bugs |
| Relevance | 5/5 | 5/5 | Tie |
| Completeness | 4/5 | 4/5 | Tie |
| Style & Presentation | 4/5 | 5/5 | Claude |
| Coherence | 5/5 | 5/5 | Tie |
| Helpfulness | 4/5 | 5/5 | Claude |
| Creativity | 3/5 | 4/5 | Claude |
| **Average** | **4.14** | **4.57** | **Claude** |

### Bug comparison

| | GPT-4o | Claude 3.5 Sonnet |
|--|--------|-------------------|
| R2 velocity time window | ✗ Missing — counts all history | ✓ Correct |
| R7 currency mismatch default | ✓ Correct — skips unconfigured users | ✗ Wrong — flags unconfigured users |
| Score cap at 100.0 | ✓ | ✓ |
| History updated after evaluation | ✓ | ✓ |
| Rule errors caught per-rule | ✓ | ✓ |

Both models got one rule wrong, but the bugs are different in character. GPT-4o's R2 bug is a logic error in the time-window filter — it would produce false positives for any user with a long transaction history. Claude's R7 bug is an inverted default — it would flag every transaction from users not in the home currency map, which in a real deployment could be the majority of users. Claude's bug is arguably worse in production impact, but GPT-4o's is more subtle and harder to catch in a quick review.

---

## Final Verdict

**Winner: Claude 3.5 Sonnet** (4.57 vs 4.14)

Claude's response is the stronger one overall. The code quality is noticeably better — complete docstrings on private methods, `frozenset` for lookups, a `clear_history()` utility, and a module docstring that explains design decisions rather than just describing the file. The `__main__` block is more useful, covering more scenarios including a velocity demo loop. The velocity check (R2) is implemented correctly with proper time-window filtering, which is the trickier of the two rules to get right.

GPT-4o's response is solid and would work for most use cases. It's clean, well-structured, and stays on scope. But the R2 time-window bug is a real functional gap, and the overall code quality — while good — doesn't have the same level of care as Claude's output.

If I had to ship one of these today, I'd take Claude's response, fix the R7 default (a one-line change), and it would be production-ready. GPT-4o's response would need the R2 logic rewritten, which is a more involved fix.

Neither response is perfect. The golden reference in `golden_response.py` handles both bugs correctly and is the benchmark both responses were measured against.
