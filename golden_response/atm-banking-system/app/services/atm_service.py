"""
ATM Terminal management service.

Handles ATM creation, status updates, cash cassette refills,
and status monitoring.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ATMNotFoundError
from app.core.logging_config import get_logger
from app.models.atm_terminal import ATMTerminal
from app.models.cash_cassette import CashCassette

logger = get_logger(__name__)


def get_atm_by_id(db: Session, atm_id: str) -> ATMTerminal:
    """Fetch an ATM terminal by UUID or raise ATMNotFoundError."""
    atm = db.query(ATMTerminal).filter(ATMTerminal.id == atm_id).first()
    if not atm:
        raise ATMNotFoundError(f"ATM {atm_id} not found")
    return atm


def get_atm_by_code(db: Session, atm_code: str) -> ATMTerminal:
    """Fetch an ATM terminal by its human-readable code."""
    atm = db.query(ATMTerminal).filter(ATMTerminal.atm_code == atm_code).first()
    if not atm:
        raise ATMNotFoundError(f"ATM {atm_code} not found")
    return atm


def create_atm(
    db: Session,
    atm_code: str,
    branch_code: str,
    physical_address: str,
    connected_backend_endpoint: Optional[str] = None,
    initial_cassettes: Optional[List[dict]] = None,
) -> ATMTerminal:
    """
    Create a new ATM terminal with optional initial cassette configuration.

    Args:
        initial_cassettes: List of dicts with keys 'denomination' and 'note_count'.
    """
    atm = ATMTerminal(
        atm_code=atm_code,
        branch_code=branch_code,
        physical_address=physical_address,
        connected_backend_endpoint=connected_backend_endpoint,
        terminal_status="online",
        total_cash_available=0.0,
    )
    db.add(atm)
    db.flush()   # get the ATM id

    total_cash = 0.0
    for cassette_data in (initial_cassettes or []):
        denom = cassette_data["denomination"]
        count = cassette_data.get("note_count", 0)
        cassette = CashCassette(
            atm_id=atm.id,
            denomination=denom,
            note_count=count,
        )
        db.add(cassette)
        total_cash += denom * count

    atm.total_cash_available = total_cash
    db.flush()

    logger.info("atm_created", atm_code=atm_code, total_cash=total_cash)
    return atm


def refill_cassette(
    db: Session,
    atm_id: str,
    denomination: int,
    notes_added: int,
    admin_user_id: Optional[str] = None,
) -> CashCassette:
    """
    Add notes to an ATM cassette (admin/engineer action).

    Creates the cassette row if it doesn't exist yet.
    """
    atm = get_atm_by_id(db, atm_id)

    cassette = (
        db.query(CashCassette)
        .filter(
            CashCassette.atm_id == atm_id,
            CashCassette.denomination == denomination,
        )
        .first()
    )

    if not cassette:
        cassette = CashCassette(
            atm_id=atm_id,
            denomination=denomination,
            note_count=0,
        )
        db.add(cassette)

    # Cap at max capacity
    space = cassette.max_capacity - cassette.note_count
    actual_added = min(notes_added, space)
    cassette.note_count += actual_added
    cassette.last_refilled_at = datetime.now(timezone.utc)

    # Update ATM total
    atm.total_cash_available += denomination * actual_added

    # If ATM was out of cash, bring it back online
    if atm.terminal_status == "out_of_cash" and atm.total_cash_available > 0:
        atm.terminal_status = "online"

    atm.last_serviced_at = datetime.now(timezone.utc)
    db.flush()

    logger.info(
        "cassette_refilled",
        atm_code=atm.atm_code,
        denomination=denomination,
        notes_added=actual_added,
        new_count=cassette.note_count,
        admin=admin_user_id,
    )
    return cassette


def update_atm_status(
    db: Session,
    atm_id: str,
    status: str,
    reason: Optional[str] = None,
) -> ATMTerminal:
    """Update the operational status of an ATM terminal."""
    atm = get_atm_by_id(db, atm_id)
    atm.terminal_status = status
    db.flush()
    logger.info("atm_status_updated", atm_code=atm.atm_code, status=status, reason=reason)
    return atm


def list_all_atms(db: Session) -> List[ATMTerminal]:
    """Return all ATM terminals."""
    return db.query(ATMTerminal).all()
