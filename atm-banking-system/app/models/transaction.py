"""
Transaction ORM model.

Every financial event (withdrawal, deposit, transfer debit/credit)
is recorded as an immutable transaction row.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Reference ─────────────────────────────────────────────────────────────
    reference_id = Column(String(36), unique=True, nullable=False, index=True,
                          default=lambda: str(uuid.uuid4()))

    # ── Account link ─────────────────────────────────────────────────────────
    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )

    # ── ATM link (nullable — some transactions may be server-side) ────────────
    atm_id = Column(
        String(36), ForeignKey("atm_terminals.id", ondelete="SET NULL"), nullable=True
    )

    # ── Transaction details ───────────────────────────────────────────────────
    transaction_type = Column(
        Enum(
            "withdrawal",
            "deposit",
            "transfer_debit",
            "transfer_credit",
            "balance_inquiry",
            "reversal",
            name="transaction_type_enum",
        ),
        nullable=False,
    )
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")

    # ── Balance snapshot after this transaction ───────────────────────────────
    balance_after = Column(Float, nullable=False)

    # ── Transfer peer (populated for transfer_debit / transfer_credit) ────────
    peer_account_id = Column(String(36), nullable=True)
    peer_reference_id = Column(String(36), nullable=True)   # the other leg's ref

    # ── Status ────────────────────────────────────────────────────────────────
    status = Column(
        Enum("completed", "failed", "reversed", "pending", name="txn_status_enum"),
        nullable=False,
        default="completed",
    )

    # ── Metadata ─────────────────────────────────────────────────────────────
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    account = relationship("Account", back_populates="transactions")
    atm = relationship("ATMTerminal", back_populates="transactions")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_txn_account_created", "account_id", "created_at"),
        Index("ix_txn_type", "transaction_type"),
        Index("ix_txn_atm", "atm_id"),
    )

    @property
    def is_debit(self) -> bool:
        return self.transaction_type in ("withdrawal", "transfer_debit")

    def __repr__(self) -> str:
        return (
            f"<Transaction {self.reference_id} "
            f"type={self.transaction_type} amount={self.amount}>"
        )
