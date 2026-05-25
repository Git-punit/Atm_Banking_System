"""
fraud_detection.py — Real-Time Fraud Detection Pipeline

This is the reference implementation I wrote to benchmark LLM responses against.
The domain is fintech — specifically evaluating payment transactions in real time
and deciding whether to approve, flag, or block them based on a configurable
set of fraud rules.

I tried to keep this production-minded without over-engineering it. The main
design choices worth knowing upfront:

  - Transaction history is updated *after* evaluation, so a transaction can't
    count toward its own velocity or repeated-amount checks.
  - Each rule's exceptions are caught individually. One broken rule shouldn't
    take down the whole pipeline — in payments, failing open is usually safer
    than failing closed.
  - R7 (currency mismatch) silently skips users with no home currency on file
    rather than flagging everything. Noise is the enemy of a useful fraud signal.
  - frozenset for country/MCC lists gives O(1) lookups and prevents accidental
    mutation after init.
  - The "Z" → "+00:00" normalisation keeps this compatible with Python 3.10.
    fromisoformat() didn't handle "Z" until 3.11.

Usage:
    python3 fraud_detection.py          # runs the demo
    from fraud_detection import FraudDetectionPipeline
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"

# Every transaction must have these fields with these types.
_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "transaction_id": str,
    "user_id": str,
    "amount": (int, float),
    "currency": str,
    "merchant_category": str,
    "country_code": str,
    "timestamp": str,
    "payment_method": str,
    "is_international": bool,
}

# Recognised ISO 4217 currency codes — extend this list as needed.
_VALID_CURRENCIES: frozenset[str] = frozenset([
    "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY",
    "SEK", "NZD", "MXN", "SGD", "HKD", "NOK", "KRW", "TRY",
    "INR", "BRL", "ZAR", "NGN", "RUB",
])


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class FraudDecision:
    """The result you get back from FraudDetectionPipeline.evaluate().

    Attributes:
        transaction_id: ID of the transaction that was evaluated.
        decision: One of "approved", "flagged", or "blocked".
        risk_score: Weighted score in [0.0, 100.0].
        triggered_rules: Rule IDs that fired, e.g. ["R1", "R4"].
        audit_log: Full audit entry — keep this for compliance records.
        evaluated_at: ISO 8601 UTC timestamp of when the check ran.
    """
    transaction_id: str
    decision: str
    risk_score: float
    triggered_rules: list[str]
    audit_log: dict[str, Any]
    evaluated_at: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TransactionValidationError(ValueError):
    """Raised when a transaction dict fails input validation.

    Subclasses ValueError so callers can catch either this or the base class.
    """


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class FraudDetectionPipeline:
    """Real-time fraud detection pipeline for payment transactions.

    Runs each transaction through a configurable rule engine, computes a
    weighted risk score, and returns a FraudDecision with a full audit log.

    The pipeline keeps per-user transaction history in memory so time-based
    rules (velocity, repeated amount) work correctly. This history resets
    when the process restarts — it is not persisted.

    Rules:
        R1 — High Amount        (transaction over $10k)
        R2 — Velocity Check     (too many transactions in a short window)
        R3 — Geographic Anomaly (transaction from a high-risk country)
        R4 — Unusual Hour       (between 1am and 5am UTC)
        R5 — Merchant Category  (high-risk MCC like gambling or crypto)
        R6 — Repeated Amount    (same amount too many times recently)
        R7 — Currency Mismatch  (doesn't match user's home currency)

    Example:
        pipeline = FraudDetectionPipeline(config={
            "high_risk_countries": ["NG", "RU", "KP"],
            "high_risk_mcc": ["gambling", "crypto"],
            "rule_weights": {"R1": 30.0, "R2": 25.0, "R3": 40.0},
        })
        result = pipeline.evaluate(transaction_dict)
        print(result.decision, result.risk_score)
    """

    # Default weights — override any of these via the config dict.
    DEFAULT_RULE_WEIGHTS: dict[str, float] = {
        "R1": 30.0,   # High Amount
        "R2": 25.0,   # Velocity Check
        "R3": 40.0,   # Geographic Anomaly
        "R4": 15.0,   # Unusual Hour
        "R5": 20.0,   # Merchant Category Risk
        "R6": 20.0,   # Repeated Amount
        "R7": 10.0,   # Currency Mismatch
    }

    DEFAULT_HIGH_RISK_COUNTRIES: list[str] = ["NG", "RU", "KP", "IR", "SY", "CU"]
    DEFAULT_HIGH_RISK_MCC: list[str] = ["gambling", "crypto", "adult", "firearms"]
    DEFAULT_VELOCITY_WINDOW_SECONDS: int = 60
    DEFAULT_VELOCITY_MAX_COUNT: int = 5
    DEFAULT_HIGH_AMOUNT_THRESHOLD: float = 10_000.0
    DEFAULT_REPEATED_AMOUNT_WINDOW_SECONDS: int = 600   # 10 minutes
    DEFAULT_REPEATED_AMOUNT_MAX_COUNT: int = 3
    DEFAULT_UNUSUAL_HOUR_START: int = 1    # 01:00 UTC inclusive
    DEFAULT_UNUSUAL_HOUR_END: int = 5      # 05:00 UTC exclusive

    # Score thresholds
    FLAGGED_THRESHOLD: float = 40.0
    BLOCKED_THRESHOLD: float = 75.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Set up the pipeline with optional config overrides.

        All keys are optional — anything not provided falls back to the
        class-level defaults above.

        Args:
            config: Dict of settings. Supported keys:
                high_risk_countries (list[str]): ISO 3166-1 alpha-2 codes.
                high_risk_mcc (list[str]): Merchant category strings.
                rule_weights (dict[str, float]): Rule ID to weight mapping.
                    Only the keys you provide are overridden; the rest keep
                    their defaults.
                velocity_window_seconds (int): Window size for R2.
                velocity_max_count (int): Max transactions before R2 fires.
                user_home_currency (dict[str, str]): user_id to ISO 4217 code.
                high_amount_threshold (float): Threshold for R1.
                repeated_amount_window_seconds (int): Window size for R6.
                repeated_amount_max_count (int): Max repeats before R6 fires.
        """
        cfg = config or {}

        self._high_risk_countries: frozenset[str] = frozenset(
            cfg.get("high_risk_countries", self.DEFAULT_HIGH_RISK_COUNTRIES)
        )
        self._high_risk_mcc: frozenset[str] = frozenset(
            c.lower() for c in cfg.get("high_risk_mcc", self.DEFAULT_HIGH_RISK_MCC)
        )
        # Merge caller weights on top of defaults so you only need to specify
        # the rules you want to change.
        self._rule_weights: dict[str, float] = {
            **self.DEFAULT_RULE_WEIGHTS,
            **cfg.get("rule_weights", {}),
        }
        self._velocity_window: int = int(
            cfg.get("velocity_window_seconds", self.DEFAULT_VELOCITY_WINDOW_SECONDS)
        )
        self._velocity_max: int = int(
            cfg.get("velocity_max_count", self.DEFAULT_VELOCITY_MAX_COUNT)
        )
        self._user_home_currency: dict[str, str] = cfg.get("user_home_currency", {})
        self._high_amount_threshold: float = float(
            cfg.get("high_amount_threshold", self.DEFAULT_HIGH_AMOUNT_THRESHOLD)
        )
        self._repeated_amount_window: int = int(
            cfg.get("repeated_amount_window_seconds", self.DEFAULT_REPEATED_AMOUNT_WINDOW_SECONDS)
        )
        self._repeated_amount_max: int = int(
            cfg.get("repeated_amount_max_count", self.DEFAULT_REPEATED_AMOUNT_MAX_COUNT)
        )

        # Per-user history: user_id → list of {transaction_id, timestamp, amount}.
        # Updated after evaluation so the current txn doesn't affect its own checks.
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)

        logger.info("FraudDetectionPipeline initialised (version=%s)", PIPELINE_VERSION)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, transaction: dict[str, Any]) -> FraudDecision:
        """Evaluate a transaction and return a fraud decision.

        Validates the input, runs all rules, computes the weighted risk score,
        records the transaction in history, and returns a FraudDecision with
        a full audit log.

        Args:
            transaction: A dict representing a payment transaction. Must
                contain all required fields with the correct types.

        Returns:
            A FraudDecision with decision, risk_score, triggered_rules,
            audit_log, and evaluated_at.

        Raises:
            TransactionValidationError: If the transaction is malformed —
                missing fields, wrong types, negative amount, invalid ISO
                codes, or an unparseable timestamp.
        """
        self._validate_transaction(transaction)

        # Parse timestamp once and reuse across all rules.
        ts: datetime = self._parse_timestamp(transaction["timestamp"])

        all_rule_ids = list(self._rule_weights.keys())
        triggered: list[str] = []
        rule_metadata: dict[str, Any] = {}

        rule_methods: dict[str, Any] = {
            "R1": self._rule_high_amount,
            "R2": self._rule_velocity_check,
            "R3": self._rule_geographic_anomaly,
            "R4": self._rule_unusual_hour,
            "R5": self._rule_merchant_category_risk,
            "R6": self._rule_repeated_amount,
            "R7": self._rule_currency_mismatch,
        }

        for rule_id, rule_fn in rule_methods.items():
            try:
                fired, meta = rule_fn(transaction, ts)
                if fired:
                    triggered.append(rule_id)
                if meta:
                    rule_metadata[rule_id] = meta
            except Exception as exc:  # noqa: BLE001
                # Catch per-rule so one broken rule doesn't kill the pipeline.
                logger.warning(
                    "Rule %s failed on txn %s: %s",
                    rule_id,
                    transaction.get("transaction_id", "unknown"),
                    exc,
                    exc_info=True,
                )

        risk_score = self._compute_risk_score(triggered)
        decision = self._make_decision(risk_score)

        # Record history after evaluation — the current txn must not count
        # toward its own velocity or repeated-amount checks.
        self._record_transaction(transaction, ts)

        evaluated_at = datetime.now(timezone.utc).isoformat()
        audit_log = self._build_audit_log(
            transaction=transaction,
            all_rule_ids=all_rule_ids,
            triggered_rules=triggered,
            risk_score=risk_score,
            decision=decision,
            evaluated_at=evaluated_at,
            metadata=rule_metadata,
        )

        return FraudDecision(
            transaction_id=transaction["transaction_id"],
            decision=decision,
            risk_score=risk_score,
            triggered_rules=triggered,
            audit_log=audit_log,
            evaluated_at=evaluated_at,
        )

    def clear_history(self, user_id: str | None = None) -> None:
        """Clear the in-memory transaction history.

        Useful in tests or when resetting state between processing batches.

        Args:
            user_id: Clear history for just this user. Pass None to clear
                history for all users.
        """
        if user_id is not None:
            self._history.pop(user_id, None)
        else:
            self._history.clear()

    # ------------------------------------------------------------------
    # Fraud rules
    # Each returns (fired: bool, metadata: dict).
    # fired=True → rule triggered, its weight is added to the risk score.
    # metadata → goes into the audit log for context.
    # ------------------------------------------------------------------

    def _rule_high_amount(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R1 — Flag transactions above the configured amount threshold.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime (unused here, kept for consistent signature).

        Returns:
            Tuple of (fired, metadata). metadata has the amount and threshold.
        """
        amount = float(txn["amount"])
        fired = amount > self._high_amount_threshold
        return fired, {"amount": amount, "threshold": self._high_amount_threshold}

    def _rule_velocity_check(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R2 — Flag if the user has too many transactions in the recent window.

        Counts transactions in the user's history that fall within the last
        velocity_window_seconds. The current transaction is not included
        because history is updated after evaluation.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime of this transaction.

        Returns:
            Tuple of (fired, metadata). metadata has the count and window size.
        """
        user_id = txn["user_id"]
        window_start = ts.timestamp() - self._velocity_window
        recent = [
            t for t in self._history[user_id]
            if t["timestamp"].timestamp() >= window_start
        ]
        count = len(recent)
        fired = count >= self._velocity_max
        return fired, {"recent_count": count, "window_seconds": self._velocity_window}

    def _rule_geographic_anomaly(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R3 — Flag transactions from high-risk countries.

        The country list is configurable at init time.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime (unused here).

        Returns:
            Tuple of (fired, metadata). metadata has the country code.
        """
        country = txn["country_code"].upper()
        fired = country in self._high_risk_countries
        return fired, {
            "country_code": country,
            "high_risk_countries": sorted(self._high_risk_countries),
        }

    def _rule_unusual_hour(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R4 — Flag transactions between 01:00 and 05:00 UTC.

        This window catches a lot of card-not-present fraud where stolen
        credentials are used overnight.

        Args:
            txn: Validated transaction dict (unused here).
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata has the UTC hour.
        """
        utc_hour = ts.hour
        fired = self.DEFAULT_UNUSUAL_HOUR_START <= utc_hour < self.DEFAULT_UNUSUAL_HOUR_END
        return fired, {"utc_hour": utc_hour}

    def _rule_merchant_category_risk(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R5 — Flag transactions in high-risk merchant categories.

        The MCC list is configurable. Comparison is case-insensitive.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime (unused here).

        Returns:
            Tuple of (fired, metadata). metadata has the merchant category.
        """
        mcc = txn["merchant_category"].lower()
        fired = mcc in self._high_risk_mcc
        return fired, {"merchant_category": mcc}

    def _rule_repeated_amount(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R6 — Flag if the same amount appears too many times in the window.

        Looks back through the user's history for the same exact amount
        within the last repeated_amount_window_seconds. Catches structuring
        attacks and card-testing patterns.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime of this transaction.

        Returns:
            Tuple of (fired, metadata). metadata has the repeat count.
        """
        user_id = txn["user_id"]
        amount = float(txn["amount"])
        window_start = ts.timestamp() - self._repeated_amount_window

        repeat_count = sum(
            1
            for t in self._history[user_id]
            if t["timestamp"].timestamp() >= window_start and t["amount"] == amount
        )
        fired = repeat_count >= self._repeated_amount_max
        return fired, {
            "amount": amount,
            "repeat_count": repeat_count,
            "window_seconds": self._repeated_amount_window,
        }

    def _rule_currency_mismatch(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R7 — Flag if the transaction currency doesn't match the user's home currency.

        Only fires when a home currency is configured for this user. If we
        don't have one on file, we skip the check rather than flagging
        everything — noise kills the usefulness of a fraud signal.

        Args:
            txn: Validated transaction dict.
            ts: Parsed UTC datetime (unused here).

        Returns:
            Tuple of (fired, metadata). metadata has both currencies.
        """
        user_id = txn["user_id"]
        txn_currency = txn["currency"].upper()
        home_currency: str | None = self._user_home_currency.get(user_id)

        if home_currency is None:
            return False, {"note": "no home currency on file for this user"}

        fired = txn_currency != home_currency.upper()
        return fired, {
            "transaction_currency": txn_currency,
            "home_currency": home_currency.upper(),
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_risk_score(self, triggered_rules: list[str]) -> float:
        """Sum the weights of all triggered rules and cap at 100.

        Args:
            triggered_rules: List of rule IDs that fired.

        Returns:
            A float in [0.0, 100.0].
        """
        raw = sum(self._rule_weights.get(r, 0.0) for r in triggered_rules)
        return min(raw, 100.0)

    def _make_decision(self, risk_score: float) -> str:
        """Map a risk score to a decision string.

        Args:
            risk_score: Score from 0.0 to 100.0.

        Returns:
            "blocked" if score >= 75, "flagged" if >= 40, "approved" otherwise.
        """
        if risk_score >= self.BLOCKED_THRESHOLD:
            return "blocked"
        if risk_score >= self.FLAGGED_THRESHOLD:
            return "flagged"
        return "approved"

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def _build_audit_log(
        self,
        transaction: dict[str, Any],
        all_rule_ids: list[str],
        triggered_rules: list[str],
        risk_score: float,
        decision: str,
        evaluated_at: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the audit log entry for a transaction decision.

        Args:
            transaction: The original transaction dict.
            all_rule_ids: Every rule that was evaluated (not just the ones that fired).
            triggered_rules: Only the rules that fired.
            risk_score: Final computed score.
            decision: Final decision string.
            evaluated_at: ISO 8601 timestamp of evaluation.
            metadata: Per-rule context collected during evaluation.

        Returns:
            A dict with all required audit log fields.
        """
        return {
            "pipeline_version": PIPELINE_VERSION,
            "rules_evaluated": all_rule_ids,
            "rules_triggered": triggered_rules,
            "risk_score": risk_score,
            "decision": decision,
            "user_id": transaction["user_id"],
            "transaction_id": transaction["transaction_id"],
            "timestamp": transaction["timestamp"],
            "evaluated_at": evaluated_at,
            "metadata": {
                "amount": transaction["amount"],
                "currency": transaction["currency"],
                "country_code": transaction["country_code"],
                "merchant_category": transaction["merchant_category"],
                "payment_method": transaction["payment_method"],
                "is_international": transaction["is_international"],
                "rule_details": metadata,
            },
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_transaction(self, txn: dict[str, Any]) -> None:
        """Check that a transaction dict is well-formed before running rules.

        Args:
            txn: The transaction to validate.

        Raises:
            TransactionValidationError: If anything is wrong — missing field,
                wrong type, negative amount, invalid ISO code, bad timestamp.
        """
        if not isinstance(txn, dict):
            raise TransactionValidationError(
                f"expected a dict, got {type(txn).__name__}"
            )

        for field_name, expected_type in _REQUIRED_FIELDS.items():
            if field_name not in txn:
                raise TransactionValidationError(
                    f"missing required field: '{field_name}'"
                )
            if not isinstance(txn[field_name], expected_type):
                raise TransactionValidationError(
                    f"'{field_name}' should be {expected_type}, "
                    f"got {type(txn[field_name]).__name__}"
                )

        amount = float(txn["amount"])
        if amount <= 0:
            raise TransactionValidationError(
                f"'amount' must be positive, got {amount}"
            )

        currency = txn["currency"].upper()
        if currency not in _VALID_CURRENCIES:
            raise TransactionValidationError(
                f"unrecognised currency code: '{txn['currency']}'"
            )

        country = txn["country_code"].upper()
        if len(country) != 2 or not country.isalpha():
            raise TransactionValidationError(
                f"invalid country code: '{txn['country_code']}' "
                f"(expected ISO 3166-1 alpha-2, e.g. 'US')"
            )

        if not txn["transaction_id"].strip():
            raise TransactionValidationError("'transaction_id' must not be empty")

        if not txn["user_id"].strip():
            raise TransactionValidationError("'user_id' must not be empty")

        # Validate timestamp last — raises if unparseable.
        self._parse_timestamp(txn["timestamp"])

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        """Parse an ISO 8601 timestamp string into a UTC-aware datetime.

        Handles the "Z" suffix that Python < 3.11 doesn't support natively
        in fromisoformat().

        Args:
            ts_str: Timestamp string, e.g. "2024-06-01T14:32:00Z".

        Returns:
            A timezone-aware datetime in UTC.

        Raises:
            TransactionValidationError: If the string can't be parsed.
        """
        normalised = ts_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalised)
        except (ValueError, TypeError) as exc:
            raise TransactionValidationError(
                f"can't parse timestamp: '{ts_str}'"
            ) from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _record_transaction(self, txn: dict[str, Any], ts: datetime) -> None:
        """Add a transaction to the user's history after evaluation.

        Args:
            txn: The validated transaction dict.
            ts: Parsed UTC datetime of the transaction.
        """
        self._history[txn["user_id"]].append({
            "transaction_id": txn["transaction_id"],
            "timestamp": ts,
            "amount": float(txn["amount"]),
        })


# ---------------------------------------------------------------------------
# Demo — run this file directly to see the pipeline in action
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pipeline = FraudDetectionPipeline(config={
        "high_risk_countries": ["NG", "RU", "KP"],
        "high_risk_mcc": ["gambling", "crypto", "adult"],
        "rule_weights": {
            "R1": 30.0,
            "R2": 25.0,
            "R3": 40.0,
            "R4": 15.0,
            "R5": 20.0,
            "R6": 20.0,
            "R7": 10.0,
        },
        "velocity_window_seconds": 60,
        "velocity_max_count": 5,
        "user_home_currency": {
            "user_001": "USD",
            "user_002": "GBP",
            "user_003": "EUR",
        },
    })

    demo_transactions = [
        # Large amount at 3am UTC — R1 + R4 fire → score 45 → flagged
        {
            "transaction_id": "txn-001",
            "user_id": "user_001",
            "amount": 12000.0,
            "currency": "USD",
            "merchant_category": "electronics",
            "country_code": "US",
            "timestamp": "2024-06-01T03:15:00Z",
            "payment_method": "card",
            "is_international": False,
        },
        # Transaction from Nigeria — R3 fires → score 40 → flagged
        {
            "transaction_id": "txn-002",
            "user_id": "user_002",
            "amount": 250.0,
            "currency": "GBP",
            "merchant_category": "grocery",
            "country_code": "NG",
            "timestamp": "2024-06-01T14:00:00Z",
            "payment_method": "wallet",
            "is_international": True,
        },
        # Completely normal transaction — nothing fires → approved
        {
            "transaction_id": "txn-003",
            "user_id": "user_003",
            "amount": 45.0,
            "currency": "EUR",
            "merchant_category": "restaurant",
            "country_code": "DE",
            "timestamp": "2024-06-01T12:30:00Z",
            "payment_method": "card",
            "is_international": False,
        },
        # Gambling + wrong currency — R5 + R7 fire → score 30 → approved
        # (shows that not every combination of rules crosses a threshold)
        {
            "transaction_id": "txn-004",
            "user_id": "user_001",
            "amount": 500.0,
            "currency": "EUR",   # user_001 home currency is USD
            "merchant_category": "gambling",
            "country_code": "US",
            "timestamp": "2024-06-01T15:00:00Z",
            "payment_method": "card",
            "is_international": False,
        },
    ]

    print("=" * 70)
    print(f"  Fraud Detection Pipeline v{PIPELINE_VERSION} — Demo")
    print("=" * 70)

    for txn in demo_transactions:
        result = pipeline.evaluate(txn)
        print(f"\nTransaction : {result.transaction_id}")
        print(f"Decision    : {result.decision.upper()}")
        print(f"Risk Score  : {result.risk_score:.1f} / 100.0")
        print(f"Rules Fired : {result.triggered_rules or ['none']}")
        print(f"Evaluated At: {result.evaluated_at}")
        print("-" * 40)

    # Show what happens with a bad input
    print("\n--- Validation Error Demo ---")
    try:
        pipeline.evaluate({
            "transaction_id": "txn-bad",
            "user_id": "user_001",
            "amount": -50.0,   # negative — should raise
            "currency": "USD",
            "merchant_category": "grocery",
            "country_code": "US",
            "timestamp": "2024-06-01T10:00:00Z",
            "payment_method": "card",
            "is_international": False,
        })
    except TransactionValidationError as e:
        print(f"Caught expected error: {e}")

    # Show the velocity rule kicking in after repeated transactions
    print("\n--- Velocity Check Demo (6 transactions, same user, same timestamp) ---")
    velocity_pipeline = FraudDetectionPipeline(config={
        "velocity_max_count": 5,
        "velocity_window_seconds": 60,
    })
    for i in range(6):
        r = velocity_pipeline.evaluate({
            "transaction_id": f"vel-txn-{i:03d}",
            "user_id": "user_vel",
            "amount": 20.0,
            "currency": "USD",
            "merchant_category": "grocery",
            "country_code": "US",
            "timestamp": "2024-06-01T10:00:00Z",
            "payment_method": "card",
            "is_international": False,
        })
        print(f"  txn {i+1}: decision={r.decision}, score={r.risk_score}, rules={r.triggered_rules}")
