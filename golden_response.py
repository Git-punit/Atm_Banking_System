"""
fraud_detection.py — Real-Time Fraud Detection Pipeline

Golden reference implementation for the LLM evaluation prompt.
Domain: Fintech — Payment Transaction Fraud Detection

This module provides a self-contained, configurable fraud detection pipeline
that evaluates payment transactions against a rule engine, computes a weighted
risk score, and returns a structured decision with a full audit log.

Usage:
    from fraud_detection import FraudDetectionPipeline
    pipeline = FraudDetectionPipeline(config={...})
    decision = pipeline.evaluate(transaction_dict)

Author: Golden Reference Implementation
Version: 1.0.0
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Module-level logger — no handlers attached; callers configure logging.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PIPELINE_VERSION = "1.0.0"

# Required fields and their expected Python types for input validation.
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

# Valid ISO 4217 currency codes (subset — extend as needed).
_VALID_CURRENCIES: frozenset[str] = frozenset([
    "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY",
    "SEK", "NZD", "MXN", "SGD", "HKD", "NOK", "KRW", "TRY",
    "INR", "BRL", "ZAR", "NGN", "RUB",
])

# Valid ISO 3166-1 alpha-2 country codes (subset — extend as needed).
_VALID_COUNTRY_CODES: frozenset[str] = frozenset([
    "US", "GB", "DE", "FR", "JP", "AU", "CA", "CH", "CN", "SE",
    "NZ", "MX", "SG", "HK", "NO", "KR", "TR", "IN", "BR", "ZA",
    "NG", "RU", "KP", "IR", "SY", "CU", "VE", "MM", "BY", "LY",
])


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class FraudDecision:
    """Structured result returned by FraudDetectionPipeline.evaluate().

    Attributes:
        transaction_id: The unique identifier of the evaluated transaction.
        decision: One of "approved", "flagged", or "blocked".
        risk_score: Weighted risk score in the range [0.0, 100.0].
        triggered_rules: List of rule IDs (e.g. ["R1", "R3"]) that fired.
        audit_log: Full structured audit entry for compliance and tracing.
        evaluated_at: ISO 8601 UTC timestamp of when the decision was made.
    """

    transaction_id: str
    decision: str
    risk_score: float
    triggered_rules: list[str]
    audit_log: dict[str, Any]
    evaluated_at: str


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class TransactionValidationError(ValueError):
    """Raised when a transaction dictionary fails input validation."""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class FraudDetectionPipeline:
    """Real-time fraud detection pipeline for payment transactions.

    Evaluates each transaction against a configurable rule engine, computes
    a weighted risk score, and returns a FraudDecision with a full audit log.

    Rules implemented:
        R1 — High Amount
        R2 — Velocity Check
        R3 — Geographic Anomaly
        R4 — Unusual Hour
        R5 — Merchant Category Risk
        R6 — Repeated Amount
        R7 — Currency Mismatch

    Example:
        pipeline = FraudDetectionPipeline(config={
            "high_risk_countries": ["NG", "RU", "KP"],
            "high_risk_mcc": ["gambling", "crypto"],
            "rule_weights": {"R1": 30.0, "R2": 25.0, "R3": 40.0},
        })
        decision = pipeline.evaluate(transaction)
    """

    # ------------------------------------------------------------------
    # Class-level defaults — overridable via config at instantiation time
    # ------------------------------------------------------------------

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
    DEFAULT_UNUSUAL_HOUR_START: int = 1    # 01:00 UTC (inclusive)
    DEFAULT_UNUSUAL_HOUR_END: int = 5      # 05:00 UTC (exclusive)

    # Decision thresholds
    FLAGGED_THRESHOLD: float = 40.0
    BLOCKED_THRESHOLD: float = 75.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the pipeline with an optional configuration dictionary.

        Args:
            config: Optional dictionary to override default settings. Supported keys:
                - high_risk_countries (list[str]): ISO 3166-1 alpha-2 codes.
                - high_risk_mcc (list[str]): Merchant category strings.
                - rule_weights (dict[str, float]): Rule ID → weight mapping.
                - velocity_window_seconds (int): Time window for velocity check.
                - velocity_max_count (int): Max transactions before velocity fires.
                - user_home_currency (dict[str, str]): user_id → ISO 4217 code.
                - high_amount_threshold (float): Amount above which R1 fires.
                - repeated_amount_window_seconds (int): Window for R6.
                - repeated_amount_max_count (int): Max repeats before R6 fires.
        """
        cfg = config or {}

        self._high_risk_countries: frozenset[str] = frozenset(
            cfg.get("high_risk_countries", self.DEFAULT_HIGH_RISK_COUNTRIES)
        )
        self._high_risk_mcc: frozenset[str] = frozenset(
            c.lower() for c in cfg.get("high_risk_mcc", self.DEFAULT_HIGH_RISK_MCC)
        )
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

        # In-memory transaction history: user_id → list of parsed transactions.
        # Each entry is a dict with "timestamp" (datetime) and "amount" (float).
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)

        logger.info("FraudDetectionPipeline initialised (version=%s)", PIPELINE_VERSION)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, transaction: dict[str, Any]) -> FraudDecision:
        """Evaluate a single payment transaction for fraud risk.

        Validates the transaction, runs all fraud rules, computes a weighted
        risk score, determines the decision, and returns a FraudDecision.

        Args:
            transaction: Dictionary representing a payment transaction.
                Must contain all required fields (see module docstring).

        Returns:
            A FraudDecision dataclass with decision, risk_score,
            triggered_rules, audit_log, and evaluated_at.

        Raises:
            TransactionValidationError: If the transaction is malformed,
                has missing/wrong-type fields, a negative amount, or an
                invalid/unparseable timestamp.
        """
        # Step 1 — Validate input
        self._validate_transaction(transaction)

        # Step 2 — Parse timestamp once; reuse across rules
        ts: datetime = self._parse_timestamp(transaction["timestamp"])

        # Step 3 — Run all rules
        all_rule_ids = list(self._rule_weights.keys())
        triggered: list[str] = []
        rule_metadata: dict[str, Any] = {}

        rule_methods = {
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
                # Rule-level errors are caught and logged; they do not
                # propagate so a single broken rule cannot block evaluation.
                logger.warning(
                    "Rule %s raised an unexpected error for txn %s: %s",
                    rule_id,
                    transaction.get("transaction_id", "unknown"),
                    exc,
                    exc_info=True,
                )

        # Step 4 — Compute risk score
        risk_score = self._compute_risk_score(triggered)

        # Step 5 — Determine decision
        decision = self._make_decision(risk_score)

        # Step 6 — Update history (after evaluation to avoid self-influence)
        self._record_transaction(transaction, ts)

        # Step 7 — Build audit log
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

        Args:
            user_id: If provided, clears history only for that user.
                If None, clears history for all users.
        """
        if user_id is not None:
            self._history.pop(user_id, None)
        else:
            self._history.clear()

    # ------------------------------------------------------------------
    # Fraud rules — each returns (fired: bool, metadata: dict)
    # ------------------------------------------------------------------

    def _rule_high_amount(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R1 — Flag transactions above the configured high-amount threshold.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the amount and threshold.
        """
        amount: float = float(txn["amount"])
        fired = amount > self._high_amount_threshold
        return fired, {"amount": amount, "threshold": self._high_amount_threshold}

    def _rule_velocity_check(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R2 — Flag if the user has exceeded the velocity limit within the time window.

        Counts completed transactions for the same user_id within the last
        `velocity_window_seconds` seconds (not including the current transaction).

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the recent count and window.
        """
        user_id: str = txn["user_id"]
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
        """R3 — Block transactions originating from high-risk countries.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the country code.
        """
        country: str = txn["country_code"].upper()
        fired = country in self._high_risk_countries
        return fired, {"country_code": country, "high_risk_countries": list(self._high_risk_countries)}

    def _rule_unusual_hour(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R4 — Flag transactions occurring between 01:00 and 05:00 UTC.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the UTC hour.
        """
        utc_hour = ts.hour
        fired = self.DEFAULT_UNUSUAL_HOUR_START <= utc_hour < self.DEFAULT_UNUSUAL_HOUR_END
        return fired, {"utc_hour": utc_hour}

    def _rule_merchant_category_risk(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R5 — Flag transactions in high-risk merchant categories.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the MCC string.
        """
        mcc: str = txn["merchant_category"].lower()
        fired = mcc in self._high_risk_mcc
        return fired, {"merchant_category": mcc}

    def _rule_repeated_amount(
        self, txn: dict[str, Any], ts: datetime
    ) -> tuple[bool, dict[str, Any]]:
        """R6 — Flag if the same amount appears more than the allowed count in the window.

        Checks the user's transaction history for the same amount within the
        last `repeated_amount_window_seconds` seconds.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains the repeat count.
        """
        user_id: str = txn["user_id"]
        amount: float = float(txn["amount"])
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
        """R7 — Flag if the transaction currency does not match the user's home currency.

        Only fires if the user's home currency is configured. If no home currency
        is configured for the user, the rule does not fire.

        Args:
            txn: Validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.

        Returns:
            Tuple of (fired, metadata). metadata contains both currencies.
        """
        user_id: str = txn["user_id"]
        txn_currency: str = txn["currency"].upper()
        home_currency: str | None = self._user_home_currency.get(user_id)

        if home_currency is None:
            return False, {"note": "no home currency configured for user"}

        fired = txn_currency != home_currency.upper()
        return fired, {
            "transaction_currency": txn_currency,
            "home_currency": home_currency.upper(),
        }

    # ------------------------------------------------------------------
    # Scoring and decision logic
    # ------------------------------------------------------------------

    def _compute_risk_score(self, triggered_rules: list[str]) -> float:
        """Compute a weighted risk score from the list of triggered rule IDs.

        Args:
            triggered_rules: List of rule IDs that fired during evaluation.

        Returns:
            A float in [0.0, 100.0] representing the aggregate risk score.
        """
        raw_score = sum(
            self._rule_weights.get(rule_id, 0.0) for rule_id in triggered_rules
        )
        return min(raw_score, 100.0)

    def _make_decision(self, risk_score: float) -> str:
        """Map a risk score to a decision string.

        Args:
            risk_score: Computed risk score in [0.0, 100.0].

        Returns:
            One of "approved", "flagged", or "blocked".
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
        """Build a structured audit log entry for a transaction decision.

        Args:
            transaction: The original transaction dictionary.
            all_rule_ids: All rule IDs that were evaluated.
            triggered_rules: Rule IDs that fired.
            risk_score: Final computed risk score.
            decision: Final decision string.
            evaluated_at: ISO 8601 timestamp of evaluation.
            metadata: Per-rule context collected during evaluation.

        Returns:
            A dictionary conforming to the audit log schema defined in the prompt.
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
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_transaction(self, txn: dict[str, Any]) -> None:
        """Validate a transaction dictionary against all input constraints.

        Args:
            txn: The transaction dictionary to validate.

        Raises:
            TransactionValidationError: If any field is missing, has the wrong
                type, has an invalid value, or if the timestamp is unparseable.
        """
        if not isinstance(txn, dict):
            raise TransactionValidationError(
                f"Transaction must be a dict, got {type(txn).__name__}"
            )

        # Check required fields and types
        for field_name, expected_type in _REQUIRED_FIELDS.items():
            if field_name not in txn:
                raise TransactionValidationError(
                    f"Missing required field: '{field_name}'"
                )
            value = txn[field_name]
            if not isinstance(value, expected_type):
                raise TransactionValidationError(
                    f"Field '{field_name}' must be of type "
                    f"{expected_type if isinstance(expected_type, type) else expected_type}, "
                    f"got {type(value).__name__}"
                )

        # Amount must be positive
        amount = float(txn["amount"])
        if amount <= 0:
            raise TransactionValidationError(
                f"Field 'amount' must be positive, got {amount}"
            )

        # Currency must be a valid ISO 4217 code
        currency = txn["currency"].upper()
        if currency not in _VALID_CURRENCIES:
            raise TransactionValidationError(
                f"Invalid ISO 4217 currency code: '{txn['currency']}'"
            )

        # Country code must be a valid ISO 3166-1 alpha-2 code
        country = txn["country_code"].upper()
        if len(country) != 2 or not country.isalpha():
            raise TransactionValidationError(
                f"Invalid ISO 3166-1 alpha-2 country code: '{txn['country_code']}'"
            )

        # Timestamp must be parseable as ISO 8601
        self._parse_timestamp(txn["timestamp"])

        # transaction_id must be non-empty
        if not txn["transaction_id"].strip():
            raise TransactionValidationError("Field 'transaction_id' must not be empty")

        # user_id must be non-empty
        if not txn["user_id"].strip():
            raise TransactionValidationError("Field 'user_id' must not be empty")

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        """Parse an ISO 8601 timestamp string into a timezone-aware datetime.

        Args:
            ts_str: ISO 8601 datetime string, e.g. "2024-06-01T14:32:00Z".

        Returns:
            A timezone-aware datetime object in UTC.

        Raises:
            TransactionValidationError: If the string cannot be parsed as ISO 8601.
        """
        # Normalise "Z" suffix to "+00:00" for Python < 3.11 compatibility
        normalised = ts_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalised)
        except (ValueError, TypeError) as exc:
            raise TransactionValidationError(
                f"Invalid ISO 8601 timestamp: '{ts_str}'"
            ) from exc

        # Ensure timezone-aware; assume UTC if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _record_transaction(self, txn: dict[str, Any], ts: datetime) -> None:
        """Append a transaction to the in-memory history for its user.

        Args:
            txn: The validated transaction dictionary.
            ts: Parsed UTC datetime of the transaction.
        """
        self._history[txn["user_id"]].append({
            "transaction_id": txn["transaction_id"],
            "timestamp": ts,
            "amount": float(txn["amount"]),
        })


# ---------------------------------------------------------------------------
# Demonstration — run directly to see the pipeline in action
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

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
        # ── Transaction 1: Large amount + unusual hour → should be BLOCKED ──
        {
            "transaction_id": "txn-001",
            "user_id": "user_001",
            "amount": 12000.0,
            "currency": "USD",
            "merchant_category": "electronics",
            "country_code": "US",
            "timestamp": "2024-06-01T03:15:00Z",   # 03:15 UTC — unusual hour
            "payment_method": "card",
            "is_international": False,
        },
        # ── Transaction 2: High-risk country → should be BLOCKED ──
        {
            "transaction_id": "txn-002",
            "user_id": "user_002",
            "amount": 250.0,
            "currency": "GBP",
            "merchant_category": "grocery",
            "country_code": "NG",   # high-risk country
            "timestamp": "2024-06-01T14:00:00Z",
            "payment_method": "wallet",
            "is_international": True,
        },
        # ── Transaction 3: Normal transaction → should be APPROVED ──
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
        # ── Transaction 4: Gambling MCC + currency mismatch → should be FLAGGED ──
        {
            "transaction_id": "txn-004",
            "user_id": "user_001",
            "amount": 500.0,
            "currency": "EUR",   # user_001 home currency is USD → mismatch
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

    # ── Edge-case: demonstrate validation error ──────────────────────────────
    print("\n--- Validation Error Demo ---")
    try:
        pipeline.evaluate({
            "transaction_id": "txn-bad",
            "user_id": "user_001",
            "amount": -50.0,   # negative amount
            "currency": "USD",
            "merchant_category": "grocery",
            "country_code": "US",
            "timestamp": "2024-06-01T10:00:00Z",
            "payment_method": "card",
            "is_international": False,
        })
    except TransactionValidationError as e:
        print(f"Caught expected error: {e}")

    # ── Edge-case: demonstrate velocity rule ─────────────────────────────────
    print("\n--- Velocity Check Demo (6 rapid transactions) ---")
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
