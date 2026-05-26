"""
Card ORM model.

Represents a physical ATM/debit card linked to a bank account.
PIN is stored as a hash — the plaintext PIN is never persisted.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Card(Base):
    __tablename__ = "cards"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Card identity ─────────────────────────────────────────────────────────
    # Stored as a masked/hashed value in logs; full number only in this column.
    card_number = Column(String(16), unique=True, nullable=False, index=True)

    # ── Account link ─────────────────────────────────────────────────────────
    linked_account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )

    # ── Security ─────────────────────────────────────────────────────────────
    pin_hash = Column(String(256), nullable=False)
    failed_attempt_count = Column(Integer, nullable=False, default=0)

    # ── Status ────────────────────────────────────────────────────────────────
    card_status = Column(
        Enum("active", "blocked", "expired", "lost", "stolen", name="card_status_enum"),
        nullable=False,
        default="active",
    )
    lost_or_stolen_flag = Column(Boolean, nullable=False, default=False)

    # ── Validity ─────────────────────────────────────────────────────────────
    expiry_date = Column(Date, nullable=False)

    # ── Limits ────────────────────────────────────────────────────────────────
    daily_withdrawal_limit = Column(Float, nullable=False, default=1000.0)

    # ── Timestamps ───────────────────────────────────────────────────────────
    last_used_timestamp = Column(DateTime(timezone=True), nullable=True)
    issued_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    account = relationship("Account", back_populates="cards")
    sessions = relationship("ATMSession", back_populates="card", lazy="select")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_cards_account", "linked_account_id"),
        Index("ix_cards_status", "card_status"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_usable(self) -> bool:
        """True only when the card can be used at an ATM."""
        return (
            self.card_status == "active"
            and not self.lost_or_stolen_flag
            and self.expiry_date >= date.today()
        )

    @property
    def is_locked(self) -> bool:
        return self.failed_attempt_count >= 3

    @property
    def masked_number(self) -> str:
        """Return card number with middle digits masked for logging."""
        return f"{'*' * 12}{self.card_number[-4:]}"

    def __repr__(self) -> str:
        return f"<Card {self.masked_number} status={self.card_status}>"
