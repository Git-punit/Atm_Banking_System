
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AdminAuthError,
    AdminNotFoundError,
    CardNotFoundError,
)
from app.core.logging_config import get_logger
from app.core.security import hash_pin, mask_account_number, mask_card_number, verify_pin
from app.models.account import Account
from app.models.admin import AdminUser
from app.models.audit_log import AuditLog
from app.models.card import Card
from app.models.transaction import Transaction
from app.services.audit_service import log_event

logger = get_logger(__name__)


def create_admin(
    db: Session,
    username: str,
    email: str,
    full_name: str,
    password: str,
    role: str = "admin",
) -> AdminUser:
    """Create a new admin user with a hashed password."""
    admin = AdminUser(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=hash_pin(password),
        role=role,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    logger.info("admin_created", username=username, role=role)
    return admin


def authenticate_admin(db: Session, username: str, password: str) -> AdminUser:
    """Verify admin credentials and return the AdminUser on success."""
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not admin or not admin.is_active:
        raise AdminAuthError("Invalid credentials")

    if not verify_pin(password, admin.password_hash):
        log_event(db, "admin_login", admin_user_id=admin.id,
                  description=f"Failed admin login for {username}", severity="warning")
        raise AdminAuthError("Invalid credentials")

    admin.last_login_at = datetime.now(timezone.utc)
    db.flush()

    log_event(db, "admin_login", admin_user_id=admin.id,
              description=f"Admin {username} logged in")
    return admin


def get_admin_by_id(db: Session, admin_id: str) -> AdminUser:
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise AdminNotFoundError(f"Admin {admin_id} not found")
    return admin


def block_card(
    db: Session,
    card_number: str,
    reason: str,
    mark_lost_stolen: bool = False,
    admin_user_id: Optional[str] = None,
) -> Card:
    """Block a card (admin action)."""
    card = db.query(Card).filter(Card.card_number == card_number).first()
    if not card:
        raise CardNotFoundError(f"Card {mask_card_number(card_number)} not found")

    card.card_status = "blocked"
    if mark_lost_stolen:
        card.lost_or_stolen_flag = True
    db.flush()

    log_event(
        db, "card_blocked",
        masked_card_ref=mask_card_number(card_number),
        admin_user_id=admin_user_id,
        description=f"Card blocked: {reason}",
        severity="warning",
    )
    return card


def unblock_card(
    db: Session,
    card_number: str,
    reason: str,
    admin_user_id: Optional[str] = None,
) -> Card:
    """Unblock a card (admin action)."""
    card = db.query(Card).filter(Card.card_number == card_number).first()
    if not card:
        raise CardNotFoundError(f"Card {mask_card_number(card_number)} not found")

    card.card_status = "active"
    card.failed_attempt_count = 0
    card.lost_or_stolen_flag = False
    db.flush()

    log_event(
        db, "card_unblocked",
        masked_card_ref=mask_card_number(card_number),
        admin_user_id=admin_user_id,
        description=f"Card unblocked: {reason}",
    )
    return card


def freeze_account(
    db: Session,
    account_id: str,
    reason: str,
    admin_user_id: Optional[str] = None,
) -> Account:
    """Freeze an account (admin action)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        from app.core.exceptions import AccountNotFoundError
        raise AccountNotFoundError(f"Account {account_id} not found")

    account.account_status = "frozen"
    db.flush()

    log_event(
        db, "account_frozen",
        masked_account_ref=mask_account_number(account.account_number),
        admin_user_id=admin_user_id,
        description=f"Account frozen: {reason}",
        severity="warning",
    )
    return account


def unfreeze_account(
    db: Session,
    account_id: str,
    reason: str,
    admin_user_id: Optional[str] = None,
) -> Account:
    """Unfreeze an account (admin action)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        from app.core.exceptions import AccountNotFoundError
        raise AccountNotFoundError(f"Account {account_id} not found")

    account.account_status = "active"
    db.flush()

    log_event(
        db, "account_unfrozen",
        masked_account_ref=mask_account_number(account.account_number),
        admin_user_id=admin_user_id,
        description=f"Account unfrozen: {reason}",
    )
    return account


def get_transaction_report(
    db: Session,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    atm_id: Optional[str] = None,
    transaction_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[Transaction], int]:
    """Return a paginated, filtered transaction report for admins."""
    query = db.query(Transaction)

    if date_from:
        query = query.filter(Transaction.created_at >= date_from)
    if date_to:
        query = query.filter(Transaction.created_at <= date_to)
    if atm_id:
        query = query.filter(Transaction.atm_id == atm_id)
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)

    total = query.count()
    transactions = (
        query.order_by(desc(Transaction.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return transactions, total


def get_suspicious_activity(
    db: Session,
    limit: int = 50,
) -> List[AuditLog]:
    """Return recent fraud alerts and critical audit events."""
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type.in_(["fraud_alert", "card_locked", "login_failed"]),
        )
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
        .all()
    )


def get_failed_login_summary(db: Session) -> List[Card]:
    """Return cards with failed login attempts > 0."""
    return (
        db.query(Card)
        .filter(Card.failed_attempt_count > 0)
        .order_by(desc(Card.failed_attempt_count))
        .all()
    )
