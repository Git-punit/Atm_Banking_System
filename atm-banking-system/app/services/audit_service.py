"""
Audit logging service.

All security-sensitive events are written to the audit_logs table.
Logs are append-only — this service never updates or deletes rows.
Sensitive data (full card numbers, PINs) is never written.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.models.audit_log import AuditLog

logger = get_logger(__name__)


def log_event(
    db: Session,
    event_type: str,
    *,
    masked_card_ref: Optional[str] = None,
    masked_account_ref: Optional[str] = None,
    atm_id: Optional[str] = None,
    admin_user_id: Optional[str] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None,
    severity: str = "info",
    flush: bool = True,
) -> AuditLog:
    """
    Write a single audit log entry.

    Args:
        db:                  Active database session.
        event_type:          One of the AuditLog.event_type enum values.
        masked_card_ref:     Masked card number (e.g. ************1234).
        masked_account_ref:  Masked account number.
        atm_id:              ATM terminal UUID.
        admin_user_id:       Admin user UUID (for admin-initiated events).
        description:         Human-readable event description.
        ip_address:          Client IP address.
        severity:            info | warning | critical.
        flush:               If True, flush to DB immediately (default).

    Returns:
        The persisted AuditLog instance.
    """
    entry = AuditLog(
        event_type=event_type,
        masked_card_ref=masked_card_ref,
        masked_account_ref=masked_account_ref,
        atm_id=atm_id,
        admin_user_id=admin_user_id,
        description=description,
        ip_address=ip_address,
        severity=severity,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    if flush:
        db.flush()   # assign PK without committing the outer transaction

    logger.info(
        "audit_event",
        event_type=event_type,
        severity=severity,
        masked_card=masked_card_ref,
        masked_account=masked_account_ref,
        atm_id=atm_id,
    )
    return entry
