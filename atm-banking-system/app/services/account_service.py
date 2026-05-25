"""
Account management service.

Handles account creation, balance inquiry, and status management.
"""
import random
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import AccountNotFoundError
from app.core.logging_config import get_logger
from app.models.account import Account

logger = get_logger(__name__)


def _generate_account_number() -> str:
    """Generate a unique 12-digit account number."""
    return "".join(random.choices(string.digits, k=12))


def create_account(
    db: Session,
    account_holder_name: str,
    account_type: str = "savings",
    branch_code: str = "HQ001",
    currency: str = "USD",
    daily_withdrawal_limit: float = 1000.0,
    daily_transfer_limit: float = 5000.0,
    initial_deposit: float = 0.0,
    is_joint_account: bool = False,
) -> Account:
    """Create and persist a new bank account."""
    # Ensure unique account number
    while True:
        acc_number = _generate_account_number()
        existing = db.query(Account).filter(Account.account_number == acc_number).first()
        if not existing:
            break

    account = Account(
        account_number=acc_number,
        account_holder_name=account_holder_name,
        account_type=account_type,
        available_balance=initial_deposit,
        total_balance=initial_deposit,
        daily_withdrawal_limit=daily_withdrawal_limit,
        daily_transfer_limit=daily_transfer_limit,
        branch_code=branch_code,
        currency=currency,
        is_joint_account=is_joint_account,
        account_status="active",
        kyc_verification_status="pending",
    )
    db.add(account)
    db.flush()

    logger.info("account_created", account_number=acc_number, holder=account_holder_name)
    return account


def get_account_by_number(db: Session, account_number: str) -> Account:
    """Fetch an account by account number or raise AccountNotFoundError."""
    account = db.query(Account).filter(Account.account_number == account_number).first()
    if not account:
        raise AccountNotFoundError(f"Account {account_number} not found")
    return account


def get_account_by_id(db: Session, account_id: str) -> Account:
    """Fetch an account by UUID or raise AccountNotFoundError."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise AccountNotFoundError(f"Account {account_id} not found")
    return account


def get_balance(db: Session, account_id: str) -> Account:
    """Return the account with current balance information."""
    return get_account_by_id(db, account_id)


def freeze_account(db: Session, account_id: str, reason: Optional[str] = None) -> Account:
    """Freeze an account (admin action)."""
    account = get_account_by_id(db, account_id)
    account.account_status = "frozen"
    db.flush()
    logger.info("account_frozen", account_id=account_id, reason=reason)
    return account


def unfreeze_account(db: Session, account_id: str, reason: Optional[str] = None) -> Account:
    """Unfreeze an account (admin action)."""
    account = get_account_by_id(db, account_id)
    account.account_status = "active"
    db.flush()
    logger.info("account_unfrozen", account_id=account_id, reason=reason)
    return account
