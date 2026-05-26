"""
Rate limiting middleware using slowapi (Starlette-compatible).

Limits are applied per IP address to prevent brute-force attacks.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

# Global limiter instance — imported by routers that need rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)
