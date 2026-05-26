"""
ATM Session ORM model.

Tracks active and historical ATM sessions.
Only one active session per card is allowed at any time.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ATMSession(Base):
    __tablename__ = "sessions"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Links ─────────────────────────────────────────────────────────────────
    card_id = Column(
        String(36), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    atm_id = Column(
        String(36), ForeignKey("atm_terminals.id", ondelete="SET NULL"), nullable=True
    )

    # ── Token ─────────────────────────────────────────────────────────────────
    # The JWT jti (JWT ID) is stored here so we can invalidate individual tokens
    jti = Column(String(36), unique=True, nullable=False, index=True,
                 default=lambda: str(uuid.uuid4()))

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    is_active = Column(Boolean, nullable=False, default=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(50), nullable=True)   # logout | timeout | forced

    # ── Relationships ─────────────────────────────────────────────────────────
    card = relationship("Card", back_populates="sessions")
    atm = relationship("ATMTerminal", back_populates="sessions")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_sessions_card_active", "card_id", "is_active"),
        Index("ix_sessions_account", "account_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ATMSession {self.id[:8]} "
            f"card={self.card_id[:8]} active={self.is_active}>"
        )
