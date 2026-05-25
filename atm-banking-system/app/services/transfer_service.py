"""
Fund Transfer Service.

Implements peer-to-peer transfers with explicit rollback handling.

Transfer flow:
  1. Validate destination account
  2. Validate limits
  3. DEBIT source account
  4. CREDIT destination account
     → If credit fails: ROLLBACK the debit (restore source balance)
  5. Create two transaction records (debit leg + credit leg)
  6. Audit log both legs

Rollback comments explain exactly what state is restored and why.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import (
    AccountFrozenError,
    AccountNotFoundError,
    DailyLimitExceededError,
    InsufficientFundsError,
    TransactionLimitExceededError,
    TransferRollbackError,
)
from app.core.logging_config import get_logger
from app.core.security import mask_account_number
from app.models.account import Account
from app.models.transaction import Transaction
from app.services.audit_service import log_event

settings = get_settings()
logger = get_logger(__name__)


def process_transfer(
    db: Session,
    source_account: Account,
    destination_account_number: str,
    amount: float,
    description: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict:
    """
    Transfer funds from source_account to destination_account_number.

    Args:
        db:                          Active database session.
        source_account:              The account to debit.
        destination_account_number:  Account number of the recipient.
        amount:                      Transfer amount (positive).
        description:                 Optional transfer note.
        ip_address:                  Client IP for audit logging.

    Returns:
        Dict with reference IDs, amounts, and updated balance.

    Raises:
        AccountNotFoundError, AccountFrozenError, InsufficientFundsError,
        DailyLimitExceededError, TransactionLimitExceededError,
        TransferRollbackError.
    """
    masked_src = mask_account_number(source_account.account_number)

    # ── 1. Source account checks ──────────────────────────────────────────────
    if not source_account.is_active:
        raise AccountFrozenError(f"Source account is {source_account.account_status}")

    # ── 2. Destination account lookup ─────────────────────────────────────────
    dest_account = (
        db.query(Account)
        .filter(Account.account_number == destination_account_number)
        .first()
    )
    if not dest_account:
        raise AccountNotFoundError(
            f"Destination account {destination_account_number} not found"
        )

    if dest_account.id == source_account.id:
        raise AccountNotFoundError("Cannot transfer to the same account")

    masked_dst = mask_account_number(dest_account.account_number)

    # ── 3. Destination account status check ───────────────────────────────────
    if not dest_account.is_active:
        raise AccountFrozenError(
            f"Destination account is {dest_account.account_status} and cannot receive funds"
        )

    # ── 4. Per-transaction limit ──────────────────────────────────────────────
    # (No hard per-transaction limit for transfers in this config,
    #  but daily limit applies)

    # ── 5. Daily transfer limit ───────────────────────────────────────────────
    source_account.reset_daily_limits_if_needed()
    remaining_daily = source_account.daily_transfer_limit - source_account.daily_transfer_used
    if amount > remaining_daily:
        log_event(
            db, "transfer_failed",
            masked_account_ref=masked_src,
            description=f"Daily transfer limit exceeded: requested={amount}, remaining={remaining_daily}",
            severity="warning",
        )
        raise DailyLimitExceededError(
            f"Daily transfer limit exceeded. Remaining today: {remaining_daily:.2f}"
        )

    # ── 6. Sufficient balance check ───────────────────────────────────────────
    if source_account.available_balance < amount:
        log_event(
            db, "transfer_failed",
            masked_account_ref=masked_src,
            description=f"Insufficient funds: balance={source_account.available_balance}, requested={amount}",
            severity="info",
        )
        raise InsufficientFundsError(
            f"Insufficient funds. Available: {source_account.available_balance:.2f}"
        )

    # ── 7. DEBIT source account ───────────────────────────────────────────────
    # Save pre-debit balance for rollback
    pre_debit_balance = source_account.available_balance
    pre_debit_total = source_account.total_balance
    pre_debit_daily_used = source_account.daily_transfer_used

    source_account.available_balance -= amount
    source_account.total_balance -= amount
    source_account.daily_transfer_used += amount

    # ── 8. CREDIT destination account ────────────────────────────────────────
    # If this step fails, we must roll back the debit above.
    try:
        dest_account.available_balance += amount
        dest_account.total_balance += amount
        db.flush()   # surface any DB constraint violations now
    except Exception as exc:
        # ── ROLLBACK: Restore source account to pre-debit state ───────────────
        # WHY: The credit leg failed (DB error, constraint violation, etc.).
        #      The debit has already been applied in memory but not committed.
        #      We restore the source balance so the outer transaction can be
        #      rolled back cleanly, leaving both accounts unchanged.
        source_account.available_balance = pre_debit_balance
        source_account.total_balance = pre_debit_total
        source_account.daily_transfer_used = pre_debit_daily_used

        log_event(
            db, "transfer_rollback",
            masked_account_ref=masked_src,
            description=f"Transfer rollback: credit to {masked_dst} failed — {exc}",
            severity="critical",
        )
        logger.error(
            "transfer_rollback",
            source=masked_src,
            destination=masked_dst,
            amount=amount,
            error=str(exc),
        )
        raise TransferRollbackError(
            "Transfer failed during credit step. Debit has been rolled back. "
            "No funds were moved."
        ) from exc

    # ── 9. Create transaction records ─────────────────────────────────────────
    shared_ref = str(uuid.uuid4())   # links the two legs together
    debit_ref = str(uuid.uuid4())
    credit_ref = str(uuid.uuid4())

    debit_txn = Transaction(
        reference_id=debit_ref,
        account_id=source_account.id,
        transaction_type="transfer_debit",
        amount=amount,
        currency=source_account.currency,
        balance_after=source_account.available_balance,
        peer_account_id=dest_account.id,
        peer_reference_id=credit_ref,
        status="completed",
        description=description or f"Transfer to {masked_dst}",
    )

    credit_txn = Transaction(
        reference_id=credit_ref,
        account_id=dest_account.id,
        transaction_type="transfer_credit",
        amount=amount,
        currency=dest_account.currency,
        balance_after=dest_account.available_balance,
        peer_account_id=source_account.id,
        peer_reference_id=debit_ref,
        status="completed",
        description=description or f"Transfer from {masked_src}",
    )

    db.add(debit_txn)
    db.add(credit_txn)
    db.flush()

    # ── 10. Audit log ─────────────────────────────────────────────────────────
    log_event(
        db, "transfer_success",
        masked_account_ref=masked_src,
        description=(
            f"Transfer of {amount} {source_account.currency} "
            f"to {masked_dst} (ref: {debit_ref})"
        ),
        ip_address=ip_address,
    )

    logger.info(
        "transfer_processed",
        source=masked_src,
        destination=masked_dst,
        amount=amount,
        debit_ref=debit_ref,
        credit_ref=credit_ref,
    )

    return {
        "reference_id": shared_ref,
        "debit_reference_id": debit_ref,
        "credit_reference_id": credit_ref,
        "amount": amount,
        "currency": source_account.currency,
        "destination_account": destination_account_number,
        "balance_after": source_account.available_balance,
        "timestamp": datetime.now(timezone.utc),
    }
