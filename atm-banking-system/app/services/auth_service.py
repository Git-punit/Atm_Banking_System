"""
Authentication service.

Handles the full ATM login/logout lifecycle:
  1. Validate card number (Luhn)
  2. Look up card and check status
  3. Verify PIN (hashed)
  4. Enforce lockout after MAX_PIN_ATTEMPTS failures
  5. Prevent concurrent sessions
  6. Issue JWT + persist session row
  7. Logout / forced session invalidation
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import (
    AccountLockedError,
    ATMNotFoundError,
    ATMOfflineError,
    CardBlockedError,
    CardExpiredError,
    CardLostOrStolenError,
    CardNotFoundError,
    ConcurrentSessionError,
    InvalidCardNumberError,
    InvalidPINError,
    SessionExpiredError,
    SessionNotFoundError,
)
from app.core.luhn import is_valid_card_number
from app.core.security import (
    create_access_token,
    mask_account_number,
    mask_card_number,
    verify_pin,
)
from app.models.atm_terminal import ATMTerminal
from app.models.card import Card
from app.models.session import ATMSession
from app.services.audit_service import log_event

settings = get_settings()


# ── Login ─────────────────────────────────────────────────────────────────────

def login(
    db: Session,
    card_number: str,
    plain_pin: str,
    atm_id: str,
    ip_address: Optional[str] = None,
) -> dict:
    """
    Authenticate a card holder and open an ATM session.

    Returns a dict with token, session metadata, and account info.
    Raises a specific ATMBaseException subclass on any failure.
    """
    # 1. Luhn validation (belt-and-suspenders; schema also validates)
    if not is_valid_card_number(card_number):
        raise InvalidCardNumberError("Card number failed Luhn validation")

    # 2. Fetch ATM terminal
    atm = db.query(ATMTerminal).filter(ATMTerminal.id == atm_id).first()
    if not atm:
        raise ATMNotFoundError(f"ATM {atm_id} not found")
    if not atm.is_operational:
        raise ATMOfflineError(f"ATM {atm.atm_code} is currently {atm.terminal_status}")

    # 3. Fetch card
    card = db.query(Card).filter(Card.card_number == card_number).first()
    masked = mask_card_number(card_number)

    if not card:
        log_event(
            db, "login_failed",
            masked_card_ref=masked,
            atm_id=atm_id,
            description="Card not found",
            ip_address=ip_address,
            severity="warning",
        )
        raise CardNotFoundError("Card not found")

    masked_acc = mask_account_number(card.account.account_number) if card.account else None

    # 4. Card status checks
    if card.lost_or_stolen_flag:
        log_event(db, "login_failed", masked_card_ref=masked, atm_id=atm_id,
                  description="Lost/stolen card used", severity="critical")
        raise CardLostOrStolenError("This card has been reported lost or stolen")

    if card.card_status == "blocked":
        log_event(db, "login_failed", masked_card_ref=masked, atm_id=atm_id,
                  description="Blocked card used", severity="warning")
        raise CardBlockedError("This card is blocked")

    if card.card_status == "expired":
        log_event(db, "login_failed", masked_card_ref=masked, atm_id=atm_id,
                  description="Expired card used", severity="warning")
        raise CardExpiredError("This card has expired")

    # 5. Lockout check (persists across restarts)
    if card.failed_attempt_count >= settings.max_pin_attempts:
        log_event(db, "login_failed", masked_card_ref=masked, atm_id=atm_id,
                  description="Locked card used", severity="warning")
        raise AccountLockedError(
            f"Card locked after {settings.max_pin_attempts} failed PIN attempts. "
            "Please contact your bank."
        )

    # 6. PIN verification
    if not verify_pin(plain_pin, card.pin_hash):
        card.failed_attempt_count += 1
        remaining = settings.max_pin_attempts - card.failed_attempt_count

        if card.failed_attempt_count >= settings.max_pin_attempts:
            card.card_status = "blocked"
            db.flush()
            log_event(db, "card_locked", masked_card_ref=masked,
                      masked_account_ref=masked_acc, atm_id=atm_id,
                      description="Card locked after max PIN failures",
                      severity="critical")
            raise AccountLockedError(
                "Card locked due to too many incorrect PIN attempts"
            )

        db.flush()
        log_event(db, "login_failed", masked_card_ref=masked,
                  masked_account_ref=masked_acc, atm_id=atm_id,
                  description=f"Wrong PIN, {remaining} attempt(s) remaining",
                  severity="warning", ip_address=ip_address)
        raise InvalidPINError(
            f"Incorrect PIN. {remaining} attempt(s) remaining before card is locked."
        )

    # 7. Prevent concurrent sessions
    existing_session = (
        db.query(ATMSession)
        .filter(ATMSession.card_id == card.id, ATMSession.is_active == True)  # noqa: E712
        .first()
    )
    if existing_session:
        # Check if the existing session has timed out
        elapsed = (
            datetime.now(timezone.utc) - existing_session.last_activity_at
        ).total_seconds()
        if elapsed < settings.session_inactivity_seconds:
            log_event(db, "login_failed", masked_card_ref=masked, atm_id=atm_id,
                      description="Concurrent session attempt", severity="warning")
            raise ConcurrentSessionError(
                "A session is already active for this card. "
                "Please end the existing session first."
            )
        # Expired session — close it silently
        _close_session(db, existing_session, reason="timeout")

    # 8. Reset failed attempts on successful auth
    card.failed_attempt_count = 0
    card.last_used_timestamp = datetime.now(timezone.utc)

    # 9. Create session row
    jti = str(uuid.uuid4())
    session = ATMSession(
        card_id=card.id,
        account_id=card.linked_account_id,
        atm_id=atm_id,
        jti=jti,
        is_active=True,
    )
    db.add(session)
    db.flush()

    # 10. Issue JWT
    token = create_access_token(
        card_id=card.id,
        account_id=card.linked_account_id,
        atm_id=atm_id,
        jti=jti,
    )

    log_event(
        db, "login_success",
        masked_card_ref=masked,
        masked_account_ref=masked_acc,
        atm_id=atm_id,
        description="Successful login",
        ip_address=ip_address,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_seconds": settings.session_inactivity_seconds,
        "account_holder_name": card.account.account_holder_name,
        "masked_card_number": masked,
        "session_id": session.id,
    }


# ── Logout ────────────────────────────────────────────────────────────────────

def logout(
    db: Session,
    jti: str,
    atm_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Invalidate the session identified by the JWT's jti claim.
    """
    session = db.query(ATMSession).filter(ATMSession.jti == jti).first()
    if not session or not session.is_active:
        return   # idempotent — already logged out

    _close_session(db, session, reason="logout")
    db.flush()

    log_event(
        db, "logout",
        atm_id=atm_id or session.atm_id,
        description="User logged out",
        ip_address=ip_address,
    )


# ── Session validation ────────────────────────────────────────────────────────

def validate_session(db: Session, jti: str) -> ATMSession:
    """
    Validate that a session is active and not timed out.

    Updates last_activity_at on success.
    Raises SessionNotFoundError or SessionExpiredError on failure.
    """
    session = db.query(ATMSession).filter(ATMSession.jti == jti).first()

    if not session or not session.is_active:
        raise SessionNotFoundError("Session not found or already ended")

    elapsed = (
        datetime.now(timezone.utc) - session.last_activity_at
    ).total_seconds()

    if elapsed >= settings.session_inactivity_seconds:
        _close_session(db, session, reason="timeout")
        db.flush()
        log_event(
            db, "session_expired",
            atm_id=session.atm_id,
            description=f"Session timed out after {elapsed:.0f}s of inactivity",
            severity="info",
        )
        raise SessionExpiredError(
            f"Session expired after {settings.session_inactivity_seconds}s of inactivity"
        )

    # Refresh activity timestamp
    session.last_activity_at = datetime.now(timezone.utc)
    db.flush()
    return session


# ── Internal helpers ──────────────────────────────────────────────────────────

def _close_session(db: Session, session: ATMSession, reason: str) -> None:
    session.is_active = False
    session.ended_at = datetime.now(timezone.utc)
    session.end_reason = reason
    db.flush()
