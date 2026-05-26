# dependencies.py
# FastAPI injectable dependencies for session/auth validation.
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ATMBaseException,
    SessionExpiredError,
    SessionNotFoundError,
    UnauthorizedError,
)
from app.core.security import decode_access_token, decode_admin_token
from app.database import get_db
from app.models.account import Account
from app.models.admin import AdminUser
from app.models.session import ATMSession
from app.services.auth_service import validate_session

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_session(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> ATMSession:
    """
    Validate the Bearer JWT and return the active ATMSession.

    Raises HTTP 401 on any auth failure.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "MISSING_TOKEN", "message": "Authorization token required"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_TOKEN", "message": "Token is invalid or expired"},
        ) from exc

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_TOKEN", "message": "Token missing jti claim"},
        )

    try:
        session = validate_session(db, jti)
    except (SessionExpiredError, SessionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.to_dict(),
        ) from exc

    return session


def get_current_account(
    session: Annotated[ATMSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> Account:
    """Return the Account associated with the current session."""
    account = db.query(Account).filter(Account.id == session.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "ACCOUNT_NOT_FOUND", "message": "Account not found"},
        )
    return account


def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUser:
    """
    Validate the admin Bearer JWT and return the AdminUser.

    Raises HTTP 401/403 on any auth failure.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "MISSING_TOKEN", "message": "Admin token required"},
        )

    try:
        payload = decode_admin_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_ADMIN_TOKEN", "message": "Admin token invalid or expired"},
        ) from exc

    admin_id = payload.get("sub")
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id, AdminUser.is_active == True).first()  # noqa: E712
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "ADMIN_NOT_FOUND", "message": "Admin account not found or inactive"},
        )
    return admin


def require_role(*roles: str):
    """
    Dependency factory that enforces admin role requirements.

    Usage:
        @router.post("/sensitive", dependencies=[Depends(require_role("superadmin"))])
    """
    def _check(admin: Annotated[AdminUser, Depends(get_current_admin)]) -> AdminUser:
        if admin.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "INSUFFICIENT_PERMISSIONS",
                    "message": f"Required role(s): {', '.join(roles)}",
                },
            )
        return admin
    return _check


def atm_exception_handler(request: Request, exc: ATMBaseException):
    """Convert domain exceptions to structured JSON HTTP responses."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_dict(),
    )
