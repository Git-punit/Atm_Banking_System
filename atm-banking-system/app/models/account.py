"""
Account ORM model.

Represents a bank account that can be linked to one or more ATM cards.
Supports savings, current, and salary account types.
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
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Identity ──────────────────────────────────────────────────────────────
    account_number = Column(String(20), unique=True, nullable=False, index=True)
    account_holder_name = Column(String(200), nullable=False)
    account_type = Column(
        Enum("savings", "current", "salary", name="account_type_enum"),
        nullable=False,
        default="savings",
    )

    # ── Balance ───────────────────────────────────────────────────────────────
    available_balance = Column(Float, nullable=False, default=0.0)
    total_balance = Column(Float, nullable=False, default=0.0)   # includes holds

    # ── Limits ────────────────────────────────────────────────────────────────
    daily_withdrawal_limit = Column(Float, nullable=False, default=1000.0)
    daily_withdrawal_used = Column(Float, nullable=False, default=0.0)
    daily_withdrawal_reset_date = Column(Date, nullable=True)

    daily_transfer_limit = Column(Float, nullable=False, default=5000.0)
    daily_transfer_used = Column(Float, nullable=False, default=0.0)
    daily_transfer_reset_date = Column(Date, nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    account_status = Column(
        Enum("active", "frozen", "closed", "dormant", name="account_status_enum"),
        nullable=False,
        default="active",
    )
    is_joint_account = Column(Boolean, nullable=False, default=False)

    # ── KYC / Compliance ──────────────────────────────────────────────────────
    kyc_verification_status = Column(
        Enum("pending", "verified", "rejected", name="kyc_status_enum"),
        nullable=False,
        default="pending",
    )

    # ── Organisation ─────────────────────────────────────────────────────────
    branch_code = Column(String(20), nullable=False, default="HQ001")
    currency = Column(String(3), nullable=False, default="USD")

    # ── Alerts ────────────────────────────────────────────────────────────────
    low_balance_threshold = Column(Float, nullable=True)

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
    notes = Column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    cards = relationship("Card", back_populates="account", lazy="select")
    transactions = relationship(
        "Transaction", back_populates="account", lazy="dynamic"
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_accounts_status", "account_status"),
        Index("ix_accounts_branch", "branch_code"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def reset_daily_limits_if_needed(self) -> None:
        """Reset daily counters when the calendar date has rolled over."""
        today = date.today()
        if self.daily_withdrawal_reset_date != today:
            self.daily_withdrawal_used = 0.0
            self.daily_withdrawal_reset_date = today
        if self.daily_transfer_reset_date != today:
            self.daily_transfer_used = 0.0
            self.daily_transfer_reset_date = today

    @property
    def is_active(self) -> bool:
        return self.account_status == "active"

    def __repr__(self) -> str:
        return (
            f"<Account {self.account_number} "
            f"({self.account_type}) balance={self.available_balance}>"
        )
