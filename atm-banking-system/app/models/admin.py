"""
AdminUser ORM model.

Admin users are stored in a separate table and use a separate
authentication flow from regular card holders.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Index, String
from sqlalchemy.orm import relationship

from app.database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Identity ──────────────────────────────────────────────────────────────
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)

    # ── Security ─────────────────────────────────────────────────────────────
    password_hash = Column(String(256), nullable=False)

    # ── Role ─────────────────────────────────────────────────────────────────
    role = Column(
        Enum("superadmin", "admin", "auditor", name="admin_role_enum"),
        nullable=False,
        default="admin",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, nullable=False, default=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (Index("ix_admin_role", "role"),)

    def __repr__(self) -> str:
        return f"<AdminUser {self.username} role={self.role}>"
