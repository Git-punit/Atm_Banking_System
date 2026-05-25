"""
Fraud detection service.

Performs lightweight, rule-based fraud checks on transactions.
Suspicious patterns trigger audit log entries with severity="critical".

Rules implemented:
  1. Velocity check — more than 5 withdrawals in the last 10 minutes
  2. Large withdrawal — single withdrawal > 80% of daily limit
  3. Multiple ATM locations — transactions at different ATMs within 5 minutes
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.core.security import mask_account_number
from app.models.account import Account
from app.models.atm_terminal import ATMTerminal
from app.models.transaction import Transaction
from app.services.audit_service import log_event

logger = get_logger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
VELOCITY_WINDOW_MINUTES = 10
VELOCITY_MAX_TRANSACTIONS = 5
LARGE_WITHDRAWAL_RATIO = 0.80   # fraction of daily limit


def check_withdrawal_fraud(
    db: Session,
    account: Account,
    atm: ATMTerminal,
    amount: float,
) -> None:
    """
    Run fraud checks for a withdrawal request.

    Does NOT block the transaction — only logs alerts.
    Blocking decisions are left to human review or a downstream risk engine.
    """
    masked_acc = mask_account_number(account.account_number)
    now = datetime.now(timezone.utc)

    # ── Rule 1: Velocity check ────────────────────────────────────────────────
    window_start = now - timedelta(minutes=VELOCITY_WINDOW_MINUTES)
    recent_count = (
        db.query(Transaction)
        .filter(
            Transaction.account_id == account.id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= window_start,
            Transaction.status == "completed",
        )
        .count()
    )
    if recent_count >= VELOCITY_MAX_TRANSACTIONS:
        log_event(
            db, "fraud_alert",
            masked_account_ref=masked_acc,
            atm_id=atm.id,
            description=(
                f"Velocity alert: {recent_count} withdrawals in "
                f"the last {VELOCITY_WINDOW_MINUTES} minutes"
            ),
            severity="critical",
        )
        logger.warning(
            "fraud_velocity_alert",
            account=masked_acc,
            recent_count=recent_count,
            window_minutes=VELOCITY_WINDOW_MINUTES,
        )

    # ── Rule 2: Large withdrawal ──────────────────────────────────────────────
    threshold = account.daily_withdrawal_limit * LARGE_WITHDRAWAL_RATIO
    if amount >= threshold:
        log_event(
            db, "fraud_alert",
            masked_account_ref=masked_acc,
            atm_id=atm.id,
            description=(
                f"Large withdrawal alert: {amount} is "
                f"{(amount / account.daily_withdrawal_limit * 100):.0f}% of daily limit"
            ),
            severity="warning",
        )

    # ── Rule 3: Multiple ATM locations ────────────────────────────────────────
    five_min_ago = now - timedelta(minutes=5)
    recent_atm_txn = (
        db.query(Transaction)
        .filter(
            Transaction.account_id == account.id,
            Transaction.transaction_type == "withdrawal",
            Transaction.created_at >= five_min_ago,
            Transaction.atm_id != atm.id,
            Transaction.atm_id.isnot(None),
        )
        .first()
    )
    if recent_atm_txn:
        log_event(
            db, "fraud_alert",
            masked_account_ref=masked_acc,
            atm_id=atm.id,
            description=(
                f"Multi-location alert: withdrawal at ATM {atm.atm_code} "
                f"within 5 minutes of transaction at ATM {recent_atm_txn.atm_id}"
            ),
            severity="critical",
        )
        logger.warning(
            "fraud_multi_location_alert",
            account=masked_acc,
            current_atm=atm.atm_code,
            previous_atm=recent_atm_txn.atm_id,
        )
