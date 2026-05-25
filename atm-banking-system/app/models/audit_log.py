"""
AuditLog ORM model.

Append-only audit trail for every security-sensitive event.
Rows are never updated or deleted — only inserted.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, Index, String, Text

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Event classification ──────────────────────────────────────────────────
    event_type = Column(
        Enum(
            # Auth events
            "login_success",
            "login_failed",
            "logout",
            "session_expired",
            "session_forced_end",
            "card_locked",
            # Transaction events
            "withdrawal_success",
            "withdrawal_failed",
            "deposit_success",
            "deposit_failed",
            "transfer_success",
            "transfer_failed",
            "transfer_rollback",
            # Admin events
            "admin_login",
            "account_frozen",
            "account_unfrozen",
            "card_blocked",
            "card_unblocked",
            "atm_refill",
            "admin_report_generated",
            # Fraud / alerts
            "fraud_alert",
            "low_cash_alert",
            "balance_threshold_alert",
            name="audit_event_type_enum",
        ),
        nullable=False,
        index=True,
    )

    # ── Context ───────────────────────────────────────────────────────────────
    # Masked references — never store full card numbers or PINs here
    masked_card_ref = Column(String(20), nullable=True)
    masked_account_ref = Column(String(20), nullable=True)
    atm_id = Column(String(36), nullable=True)
    admin_user_id = Column(String(36), nullable=True)

    # ── Detail ────────────────────────────────────────────────────────────────
    description = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)   # supports IPv6

    # ── Severity ─────────────────────────────────────────────────────────────
    severity = Column(
        Enum("info", "warning", "critical", name="audit_severity_enum"),
        nullable=False,
        default="info",
    )

    # ── Timestamp (immutable) ─────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_audit_event_created", "event_type", "created_at"),
        Index("ix_audit_atm", "atm_id"),
        Index("ix_audit_severity", "severity"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.event_type} at {self.created_at}>"
