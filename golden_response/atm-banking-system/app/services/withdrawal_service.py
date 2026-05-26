# withdrawal_service.py
#
# All the balance and cassette changes happen in the caller's DB transaction,
# so if anything goes wrong it all rolls back cleanly.
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
    masked_acc = mask_account_number(account.account_number)

    # fail fast if ATM is down or empty
    if not atm.is_operational:
        raise ATMOfflineError(f"ATM {atm.atm_code} is {atm.terminal_status}")

    if atm.total_cash_available <= 0:
        raise ATMOutOfCashError(f"ATM {atm.atm_code} is out of cash")

    # check account can actually transact
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

    # amount must be a whole multiple of the note denomination
    denom = settings.default_denomination
    if amount % denom != 0:
        raise InvalidDenominationError(
            f"Amount must be a multiple of {denom} (the ATM denomination)"
        )

    # single-transaction cap
    if amount > settings.max_single_withdrawal:
        raise TransactionLimitExceededError(
            f"Single withdrawal limit is {settings.max_single_withdrawal}. "
            f"Requested: {amount}"
        )

    # rolling daily limit (resets at midnight)
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

    # finally, does the account actually have the money?
    if account.available_balance < amount:
        log_event(db, "withdrawal_failed", masked_account_ref=masked_acc,
                  atm_id=atm.id,
                  description=f"Insufficient funds: balance={account.available_balance}, requested={amount}",
                  severity="info")
        raise InsufficientFundsError(
            f"Insufficient funds. Available: {account.available_balance:.2f}"
        )

    # lock the cassette row to prevent a race where two withdrawals
    # both see enough notes but together over-dispense
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

    # quick rule-based fraud scan (non-blocking)
    check_withdrawal_fraud(db, account, atm, amount)

    # deduct everything atomically
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

    # write the transaction record
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

    # audit trail
    log_event(
        db, "withdrawal_success",
        masked_account_ref=masked_acc,
        atm_id=atm.id,
        description=f"Withdrawal of {amount} {account.currency}",
        ip_address=ip_address,
    )

    # warn ops if cash is getting low
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
