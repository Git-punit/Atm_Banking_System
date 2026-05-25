"""
CashCassette ORM model.

Each ATM terminal has one or more cassettes, each holding a specific
denomination of notes. Inventory is tracked per denomination.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class CashCassette(Base):
    __tablename__ = "cash_cassettes"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── ATM link ─────────────────────────────────────────────────────────────
    atm_id = Column(
        String(36),
        ForeignKey("atm_terminals.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Denomination ─────────────────────────────────────────────────────────
    denomination = Column(Integer, nullable=False)   # e.g. 20, 50, 100
    note_count = Column(Integer, nullable=False, default=0)

    # ── Derived (stored for quick reads) ─────────────────────────────────────
    @property
    def total_value(self) -> float:
        return float(self.denomination * self.note_count)

    # ── Capacity ─────────────────────────────────────────────────────────────
    max_capacity = Column(Integer, nullable=False, default=2000)   # notes

    # ── Timestamps ───────────────────────────────────────────────────────────
    last_refilled_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    atm = relationship("ATMTerminal", back_populates="cassettes")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_cassette_atm_denom", "atm_id", "denomination", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<CashCassette atm={self.atm_id[:8]} "
            f"denom={self.denomination} count={self.note_count}>"
        )
