"""
Authentication router.

POST /auth/login   — card + PIN authentication, returns JWT
POST /auth/logout  — invalidates the current session
POST /admin/auth/login — admin authentication
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.exceptions import ATMBaseException
from app.core.security import create_admin_token
from app.database import get_db
from app.dependencies import get_current_session
from app.middleware.rate_limiter import limiter
from app.models.session import ATMSession
from app.schemas.auth import (
    AdminLoginRequest,
    AdminLoginResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from app.services import admin_service, auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])
admin_auth_router = APIRouter(prefix="/admin/auth", tags=["Admin Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="ATM card login",
    description=(
        "Authenticate with a 16-digit card number and PIN. "
        "Returns a JWT session token valid for the configured inactivity timeout."
    ),
)
@limiter.limit("10/minute")   # strict limit on login attempts
def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    try:
        result = auth_service.login(
            db=db,
            card_number=body.card_number,
            plain_pin=body.pin,
            atm_id=body.atm_id,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        return LoginResponse(**result)
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        ) from exc


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="End ATM session",
)
def logout(
    request: Request,
    session: Annotated[ATMSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> LogoutResponse:
    try:
        auth_service.logout(
            db=db,
            jti=session.jti,
            atm_id=session.atm_id,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        return LogoutResponse()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Logout failed"},
        ) from exc


# ── Admin auth ────────────────────────────────────────────────────────────────

@admin_auth_router.post(
    "/login",
    response_model=AdminLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin login",
)
@limiter.limit("5/minute")
def admin_login(
    request: Request,
    body: AdminLoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AdminLoginResponse:
    try:
        admin = admin_service.authenticate_admin(db, body.username, body.password)
        token = create_admin_token(admin_id=admin.id, role=admin.role)
        db.commit()
        return AdminLoginResponse(
            access_token=token,
            admin_id=admin.id,
            role=admin.role,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
