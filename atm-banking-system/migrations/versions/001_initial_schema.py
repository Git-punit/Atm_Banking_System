"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── accounts ──────────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_number", sa.String(20), nullable=False, unique=True),
        sa.Column("account_holder_name", sa.String(200), nullable=False),
        sa.Column(
            "account_type",
            sa.Enum("savings", "current", "salary", name="account_type_enum"),
            nullable=False,
            server_default="savings",
        ),
        sa.Column("available_balance", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_balance", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_withdrawal_limit", sa.Float, nullable=False, server_default="1000"),
        sa.Column("daily_withdrawal_used", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_withdrawal_reset_date", sa.Date, nullable=True),
        sa.Column("daily_transfer_limit", sa.Float, nullable=False, server_default="5000"),
        sa.Column("daily_transfer_used", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_transfer_reset_date", sa.Date, nullable=True),
        sa.Column(
            "account_status",
            sa.Enum("active", "frozen", "closed", "dormant", name="account_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("is_joint_account", sa.Boolean, nullable=False, server_default="0"),
        sa.Column(
            "kyc_verification_status",
            sa.Enum("pending", "verified", "rejected", name="kyc_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("branch_code", sa.String(20), nullable=False, server_default="HQ001"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("low_balance_threshold", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_accounts_account_number", "accounts", ["account_number"])
    op.create_index("ix_accounts_status", "accounts", ["account_status"])
    op.create_index("ix_accounts_branch", "accounts", ["branch_code"])

    # ── atm_terminals ─────────────────────────────────────────────────────────
    op.create_table(
        "atm_terminals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("atm_code", sa.String(20), nullable=False, unique=True),
        sa.Column("branch_code", sa.String(20), nullable=False),
        sa.Column("physical_address", sa.Text, nullable=False),
        sa.Column(
            "terminal_status",
            sa.Enum("online", "offline", "maintenance", "out_of_cash", name="terminal_status_enum"),
            nullable=False,
            server_default="online",
        ),
        sa.Column("total_cash_available", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_transaction_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("daily_transaction_volume", sa.Float, nullable=False, server_default="0"),
        sa.Column("stats_reset_date", sa.Date, nullable=True),
        sa.Column("last_serviced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_backend_endpoint", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_atm_code", "atm_terminals", ["atm_code"])
    op.create_index("ix_atm_branch", "atm_terminals", ["branch_code"])
    op.create_index("ix_atm_status", "atm_terminals", ["terminal_status"])

    # ── cards ─────────────────────────────────────────────────────────────────
    op.create_table(
        "cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("card_number", sa.String(16), nullable=False, unique=True),
        sa.Column(
            "linked_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pin_hash", sa.String(256), nullable=False),
        sa.Column("failed_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "card_status",
            sa.Enum("active", "blocked", "expired", "lost", "stolen", name="card_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("lost_or_stolen_flag", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("expiry_date", sa.Date, nullable=False),
        sa.Column("daily_withdrawal_limit", sa.Float, nullable=False, server_default="1000"),
        sa.Column("last_used_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cards_card_number", "cards", ["card_number"])
    op.create_index("ix_cards_account", "cards", ["linked_account_id"])
    op.create_index("ix_cards_status", "cards", ["card_status"])

    # ── sessions ──────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "card_id",
            sa.String(36),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "atm_id",
            sa.String(36),
            sa.ForeignKey("atm_terminals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("jti", sa.String(36), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(50), nullable=True),
    )
    op.create_index("ix_sessions_jti", "sessions", ["jti"])
    op.create_index("ix_sessions_card_active", "sessions", ["card_id", "is_active"])
    op.create_index("ix_sessions_account", "sessions", ["account_id"])

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference_id", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "atm_id",
            sa.String(36),
            sa.ForeignKey("atm_terminals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "transaction_type",
            sa.Enum(
                "withdrawal", "deposit", "transfer_debit", "transfer_credit",
                "balance_inquiry", "reversal",
                name="transaction_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("balance_after", sa.Float, nullable=False),
        sa.Column("peer_account_id", sa.String(36), nullable=True),
        sa.Column("peer_reference_id", sa.String(36), nullable=True),
        sa.Column(
            "status",
            sa.Enum("completed", "failed", "reversed", "pending", name="txn_status_enum"),
            nullable=False,
            server_default="completed",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_txn_reference_id", "transactions", ["reference_id"])
    op.create_index("ix_txn_account_created", "transactions", ["account_id", "created_at"])
    op.create_index("ix_txn_type", "transactions", ["transaction_type"])
    op.create_index("ix_txn_atm", "transactions", ["atm_id"])

    # ── cash_cassettes ────────────────────────────────────────────────────────
    op.create_table(
        "cash_cassettes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "atm_id",
            sa.String(36),
            sa.ForeignKey("atm_terminals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("denomination", sa.Integer, nullable=False),
        sa.Column("note_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_capacity", sa.Integer, nullable=False, server_default="2000"),
        sa.Column("last_refilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cassette_atm_denom", "cash_cassettes", ["atm_id", "denomination"], unique=True
    )

    # ── admin_users ───────────────────────────────────────────────────────────
    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column(
            "role",
            sa.Enum("superadmin", "admin", "auditor", name="admin_role_enum"),
            nullable=False,
            server_default="admin",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_username", "admin_users", ["username"])
    op.create_index("ix_admin_role", "admin_users", ["role"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "login_success", "login_failed", "logout", "session_expired",
                "session_forced_end", "card_locked",
                "withdrawal_success", "withdrawal_failed",
                "deposit_success", "deposit_failed",
                "transfer_success", "transfer_failed", "transfer_rollback",
                "admin_login", "account_frozen", "account_unfrozen",
                "card_blocked", "card_unblocked", "atm_refill",
                "admin_report_generated",
                "fraud_alert", "low_cash_alert", "balance_threshold_alert",
                name="audit_event_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("masked_card_ref", sa.String(20), nullable=True),
        sa.Column("masked_account_ref", sa.String(20), nullable=True),
        sa.Column("atm_id", sa.String(36), nullable=True),
        sa.Column("admin_user_id", sa.String(36), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "critical", name="audit_severity_enum"),
            nullable=False,
            server_default="info",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_event_created", "audit_logs", ["event_type", "created_at"])
    op.create_index("ix_audit_atm", "audit_logs", ["atm_id"])
    op.create_index("ix_audit_severity", "audit_logs", ["severity"])
    op.create_index("ix_audit_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("admin_users")
    op.drop_table("cash_cassettes")
    op.drop_table("transactions")
    op.drop_table("sessions")
    op.drop_table("cards")
    op.drop_table("atm_terminals")
    op.drop_table("accounts")
