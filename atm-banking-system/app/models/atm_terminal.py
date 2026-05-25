"""
ATM Terminal ORM model.

Each physical ATM machine is represented as a first-class entity.
Tracks cash levels, operational status, and daily statistics.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ATMTerminal(Base):
    __tablename__ = "atm_terminals"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Identity ──────────────────────────────────────────────────────────────
    atm_code = Column(String(20), unique=True, nullable=False, index=True)
    branch_code = Column(String(20), nullable=False)
    physical_address = Column(Text, nullable=False)

    # ── Status ────────────────────────────────────────────────────────────────
    terminal_status = Column(
        Enum(
            "online",
            "offline",
            "maintenance",
            "out_of_cash",
            name="terminal_status_enum",
        ),
        nullable=False,
        default="online",
    )

    # ── Cash cassette ─────────────────────────────────────────────────────────
    # Denormalised total for quick checks; detail is in cash_cassettes table
    total_cash_available = Column(Float, nullable=False, default=0.0)

    # ── Daily statistics (reset each calendar day) ────────────────────────────
    daily_transaction_count = Column(Integer, nullable=False, default=0)
    daily_transaction_volume = Column(Float, nullable=False, default=0.0)
    stats_reset_date = Column(Date, nullable=True)

    # ── Maintenance ───────────────────────────────────────────────────────────
    last_serviced_at = Column(DateTime(timezone=True), nullable=True)
    connected_backend_endpoint = Column(String(500), nullable=True)

    # ── Metadata ─────────────────────────────────────────────────────────────
    created_at = Column(
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
    cassettes = relationship(
        "CashCassette", back_populates="atm", lazy="select", cascade="all, delete-orphan"
    )
    sessions = relationship("ATMSession", back_populates="atm", lazy="dynamic")
    transactions = relationship("Transaction", back_populates="atm", lazy="dynamic")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_atm_branch", "branch_code"),
        Index("ix_atm_status", "terminal_status"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def reset_daily_stats_if_needed(self) -> None:
        today = date.today()
        if self.stats_reset_date != today:
            self.daily_transaction_count = 0
            self.daily_transaction_volume = 0.0
            self.stats_reset_date = today

    @property
    def is_operational(self) -> bool:
        return self.terminal_status == "online"

    def __repr__(self) -> str:
        return f"<ATMTerminal {self.atm_code} status={self.terminal_status}>"
