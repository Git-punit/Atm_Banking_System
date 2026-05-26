# security.py
# PIN hashing (Argon2 preferred, bcrypt fallback), JWT helpers, and masking utilities.
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

# hashing context — Argon2 won the PHC competition, use bcrypt as fallback
# for environments where argon2-cffi can't be installed
_schemes = (
    ["argon2", "bcrypt"]
    if settings.pin_hash_algorithm == "argon2"
    else ["bcrypt"]
)

pwd_context = CryptContext(
    schemes=_schemes,
    deprecated="auto",
    # Argon2 tuning (OWASP recommended minimums)
    argon2__memory_cost=65536,   # 64 MiB
    argon2__time_cost=3,
    argon2__parallelism=4,
)


def hash_pin(plain_pin: str) -> str:
    """Hash a plaintext PIN."""
    return pwd_context.hash(plain_pin)


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verify a PIN against its hash."""
    try:
        return pwd_context.verify(plain_pin, hashed_pin)
    except Exception:
        return False




def create_access_token(
    card_id: str,
    account_id: str,
    atm_id: Optional[str],
    jti: Optional[str] = None,
) -> str:
    """
    Create a signed JWT for an ATM session.

    Claims:
        sub   — card_id (subject)
        acc   — account_id
        atm   — atm_id (may be None)
        jti   — unique token ID (maps to sessions.jti for invalidation)
        iat   — issued-at
        exp   — expiry (access_token_expire_minutes from config)
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    token_jti = jti or str(uuid.uuid4())

    payload = {
        "sub": card_id,
        "acc": account_id,
        "atm": atm_id,
        "jti": token_jti,
        "iat": now,
        "exp": expire,
        "type": "atm_session",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_admin_token(admin_id: str, role: str, jti: Optional[str] = None) -> str:
    """Create a signed JWT for an admin session."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=30)   # admin tokens last 30 minutes
    token_jti = jti or str(uuid.uuid4())

    payload = {
        "sub": admin_id,
        "role": role,
        "jti": token_jti,
        "iat": now,
        "exp": expire,
        "type": "admin_session",
    }
    return jwt.encode(payload, settings.admin_secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Returns the payload dict on success.
    Raises JWTError on any validation failure (expired, bad signature, etc.).
    """
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": True},
    )


def decode_admin_token(token: str) -> dict:
    """Decode and validate an admin JWT token."""
    return jwt.decode(
        token,
        settings.admin_secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": True},
    )


def mask_card_number(card_number: str) -> str:
    """Return a masked card number safe for logging: ************1234."""
    if len(card_number) < 4:
        return "****"
    return f"{'*' * 12}{card_number[-4:]}"


def mask_account_number(account_number: str) -> str:
    """Return a masked account number safe for logging."""
    if len(account_number) < 4:
        return "****"
    return f"{'*' * (len(account_number) - 4)}{account_number[-4:]}"
