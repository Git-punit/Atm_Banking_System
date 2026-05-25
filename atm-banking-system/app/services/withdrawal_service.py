"""
Cash Withdrawal Service.

Implements real-world withdrawal processing with strict validation:
  - Sufficient account balance
  - Amount is a multiple of ATM denomination
  - Per-transaction limit
  - Daily withdrawal limit
  - ATM cassette has enough physical notes
  - Account is active and not frozen

All balance and cassette deductions are performed atomically within
the caller's database transaction.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import (
    AccountFrozenError,
    ATMOfflineError,
    ATMOutOfCashError,
    DailyLimitExceededError,
    InsufficientATMCashError,
    InsufficientFundsError,
    InvalidDenominationError,
    TransactionLimitExceededError,
)
from app.core.logging_config import get_logger
from app.core.security import mask_account_number
from app.models.account import Account
from app.models.atm_terminal import ATMTerminal
from app.models.cash_cassette import CashCassette
from app.models.transaction import Transaction
from app.services.audit_service import log_event
from app.services.fraud_service import check_withdrawal_fraud

settings = get_settings()
logger = get_logger(__name__)


def process_withdrawal(
    db: Session,
    account: Account,
    atm: ATMTerminal,
    amount: float,
    ip_address: Optional[str] = None,
) -> Transaction:
    """
    Process a cash withdrawal request.

    Args:
        db:         Active database session (caller owns the transaction).
        account:    The account to debit.
        atm:        The ATM terminal dispensing cash.
        amount:     Requested withdrawal amount (must be a positive integer).
        ip_address: Client IP for audit logging.

    Returns:
        The completed Transaction record.

    Raises:
        AccountFrozenError, InsufficientFundsError, DailyLimitExceededError,
        TransactionLimitExceededError, InvalidDenominationError,
        ATMOutOfCashError, InsufficientATMCashError, ATMOfflineError.
    """
    masked_acc = mask_account_number(account.account_number)

    # ── 1. ATM operational check ──────────────────────────────────────────────
    if not atm.is_operational:
        raise ATMOfflineError(f"ATM {atm.atm_code} is {atm.terminal_status}")

    if atm.total_cash_available <= 0:
        raise ATMOutOfCashError(f"ATM {atm.atm_code} is out of cash")

    # ── 2. Account status check ───────────────────────────────────────────────
    if account.account_status == "frozen":
        log_event(db, "withdrawal_failed", masked_account_ref=masked_acc,
                  atm_id=atm.id, description="Withdrawal on frozen account",
                  severity="warning")
        raise AccountFrozenError("Account is frozen. Contact your bank.")

    if not account.is_active:
        log_event(db, "withdrawal_failed", masked_account_ref=masked_acc,
                  atm_id=atm.id, description=f"Withdrawal on {account.account_status} account",
                  severity="warning")
        raise AccountFrozenError(f"Account is {account.account_status}")

    # ── 3. Denomination check ─────────────────────────────────────────────────
    denom = settings.default_denomination
    if amount % denom != 0:
        raise InvalidDenominationError(
            f"Amount must be a multiple of {denom} (the ATM denomination)"
        )

    # ── 4. Per-transaction limit ──────────────────────────────────────────────
    if amount > settings.max_single_withdrawal:
        raise TransactionLimitExceededError(
            f"Single withdrawal limit is {settings.max_single_withdrawal}. "
            f"Requested: {amount}"
        )

    # ── 5. Daily limit check ──────────────────────────────────────────────────
    account.reset_daily_limits_if_needed()
    remaining_daily = account.daily_withdrawal_limit - account.daily_withdrawal_used
    if amount > remaining_daily:
        log_event(db, "withdrawal_failed", masked_account_ref=masked_acc,
                  atm_id=atm.id,
                  description=f"Daily limit exceeded: requested={amount}, remaining={remaining_daily}",
                  severity="warning")
        raise DailyLimitExceededError(
            f"Daily withdrawal limit exceeded. "
            f"Remaining today: {remaining_daily:.2f}"
        )

    # ── 6. Sufficient account balance ─────────────────────────────────────────
    if account.available_balance < amount:
        log_event(db, "withdrawal_failed", masked_account_ref=masked_acc,
                  atm_id=atm.id,
                  description=f"Insufficient funds: balance={account.available_balance}, requested={amount}",
                  severity="info")
        raise InsufficientFundsError(
            f"Insufficient funds. Available: {account.available_balance:.2f}"
        )

    # ── 7. ATM cassette inventory check ───────────────────────────────────────
    notes_needed = int(amount / denom)
    cassette = (
        db.query(CashCassette)
        .filter(
            CashCassette.atm_id == atm.id,
            CashCassette.denomination == denom,
        )
        .with_for_update()   # row-level lock to prevent race conditions
        .first()
    )

    if not cassette or cassette.note_count <= 0:
        raise ATMOutOfCashError(
            f"ATM {atm.atm_code} has no {denom}-denomination notes"
        )

    if cassette.note_count < notes_needed:
        available_cash = cassette.note_count * denom
        raise InsufficientATMCashError(
            f"ATM can only dispense {available_cash:.2f} in {denom}-denomination notes"
        )

    # ── 8. Fraud check ────────────────────────────────────────────────────────
    check_withdrawal_fraud(db, account, atm, amount)

    # ── 9. Atomic deductions ──────────────────────────────────────────────────
    # Deduct account balance
    account.available_balance -= amount
    account.total_balance -= amount
    account.daily_withdrawal_used += amount

    # Deduct ATM cassette inventory
    cassette.note_count -= notes_needed
    atm.total_cash_available -= amount

    # Update ATM daily stats
    atm.reset_daily_stats_if_needed()
    atm.daily_transaction_count += 1
    atm.daily_transaction_volume += amount

    # Mark ATM out-of-cash if cassette is now empty
    if atm.total_cash_available <= 0:
        atm.terminal_status = "out_of_cash"

    # ── 10. Create transaction record ─────────────────────────────────────────
    ref_id = str(uuid.uuid4())
    txn = Transaction(
        reference_id=ref_id,
        account_id=account.id,
        atm_id=atm.id,
        transaction_type="withdrawal",
        amount=amount,
        currency=account.currency,
        balance_after=account.available_balance,
        status="completed",
        description=f"ATM withdrawal at {atm.atm_code}",
    )
    db.add(txn)
    db.flush()

    # ── 11. Audit log ─────────────────────────────────────────────────────────
    log_event(
        db, "withdrawal_success",
        masked_account_ref=masked_acc,
        atm_id=atm.id,
        description=f"Withdrawal of {amount} {account.currency}",
        ip_address=ip_address,
    )

    # ── 12. Low-cash alert ────────────────────────────────────────────────────
    if atm.total_cash_available < settings.low_cash_threshold:
        log_event(
            db, "low_cash_alert",
            atm_id=atm.id,
            description=(
                f"ATM {atm.atm_code} cash below threshold: "
                f"{atm.total_cash_available:.2f} remaining"
            ),
            severity="warning",
        )
        logger.warning(
            "low_cash_alert",
            atm_code=atm.atm_code,
            cash_remaining=atm.total_cash_available,
            threshold=settings.low_cash_threshold,
        )

    logger.info(
        "withdrawal_processed",
        account=masked_acc,
        amount=amount,
        balance_after=account.available_balance,
        atm=atm.atm_code,
        reference=ref_id,
    )

    return txn
