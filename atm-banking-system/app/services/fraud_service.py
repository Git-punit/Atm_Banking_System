# fraud_service.py
# Rule-based fraud checks run on every withdrawal. Non-blocking —
# suspicious hits are logged for human review rather than auto-rejected.
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

VELOCITY_WINDOW_MINUTES = 10
VELOCITY_MAX_TRANSACTIONS = 5
LARGE_WITHDRAWAL_RATIO = 0.80  # percentage of daily limit that triggers the alert


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

    # rule 1: too many withdrawals in a short window
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

    # rule 2: single withdrawal is suspiciously large relative to daily limit
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

    # rule 3: same card used at two different ATMs within 5 minutes
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
