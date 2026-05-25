"""
Central application configuration loaded from environment variables.
All settings are validated by Pydantic at startup.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "ATM Banking System"
    app_env: Literal["development", "production", "testing"] = "development"
    debug: bool = False
    secret_key: str = Field(default="dev-secret-key-change-in-production")
    algorithm: str = "HS256"

    # ── Session / Token ──────────────────────────────────────────────────────
    access_token_expire_minutes: int = 2          # generous upper bound
    session_inactivity_seconds: int = 90          # real ATM timeout

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./atm_banking.db"

    # ── Security ─────────────────────────────────────────────────────────────
    pin_hash_algorithm: Literal["argon2", "bcrypt"] = "argon2"
    max_pin_attempts: int = 3
    card_number_encryption_key: str = Field(default="")

    # ── ATM Defaults ─────────────────────────────────────────────────────────
    default_denomination: int = 20
    low_cash_threshold: int = 5000
    default_daily_withdrawal_limit: float = 1000.0
    default_daily_transfer_limit: float = 5000.0
    max_single_withdrawal: float = 500.0
    max_single_deposit: float = 10000.0
    deposit_hold_days: int = 1

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 60

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_secret_key: str = Field(default="dev-admin-secret-key")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
