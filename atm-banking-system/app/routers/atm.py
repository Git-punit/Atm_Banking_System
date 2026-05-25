"""
ATM Terminal router.

GET  /atm/status        — status of a specific ATM (authenticated session)
GET  /atm/all           — list all ATMs (admin)
POST /atm/create        — create a new ATM terminal (admin)
POST /atm/{atm_id}/refill  — refill cash cassette (admin)
PUT  /atm/{atm_id}/status  — update ATM status (admin)
"""
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import ATMBaseException
from app.database import get_db
from app.dependencies import get_current_admin, get_current_session, require_role
from app.models.admin import AdminUser
from app.models.session import ATMSession
from app.schemas.atm_terminal import (
    ATMCreateRequest,
    ATMRefillRequest,
    ATMRefillResponse,
    ATMStatusResponse,
    ATMStatusUpdateRequest,
    CassetteInfo,
)
from app.services import atm_service
from app.services.audit_service import log_event

router = APIRouter(prefix="/atm", tags=["ATM Terminals"])


def _build_status_response(atm) -> ATMStatusResponse:
    return ATMStatusResponse(
        atm_id=atm.id,
        atm_code=atm.atm_code,
        branch_code=atm.branch_code,
        physical_address=atm.physical_address,
        terminal_status=atm.terminal_status,
        total_cash_available=atm.total_cash_available,
        cassettes=[
            CassetteInfo(
                denomination=c.denomination,
                note_count=c.note_count,
                total_value=c.total_value,
                max_capacity=c.max_capacity,
            )
            for c in atm.cassettes
        ],
        daily_transaction_count=atm.daily_transaction_count,
        daily_transaction_volume=atm.daily_transaction_volume,
        last_serviced_at=atm.last_serviced_at,
        updated_at=atm.updated_at,
    )


# ── Public (session-authenticated) ───────────────────────────────────────────

@router.get(
    "/status",
    response_model=ATMStatusResponse,
    summary="Get ATM status (requires active session)",
)
def get_atm_status(
    session: Annotated[ATMSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    atm_id: str = Query(..., description="ATM terminal ID"),
) -> ATMStatusResponse:
    try:
        atm = atm_service.get_atm_by_id(db, atm_id)
        return _build_status_response(atm)
    except ATMBaseException as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


# ── Admin-only ────────────────────────────────────────────────────────────────

@router.get(
    "/all",
    response_model=List[ATMStatusResponse],
    summary="List all ATM terminals (admin)",
)
def list_atms(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> List[ATMStatusResponse]:
    atms = atm_service.list_all_atms(db)
    return [_build_status_response(a) for a in atms]


@router.post(
    "/create",
    response_model=ATMStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create ATM terminal (admin)",
)
def create_atm(
    body: ATMCreateRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> ATMStatusResponse:
    try:
        atm = atm_service.create_atm(
            db=db,
            atm_code=body.atm_code,
            branch_code=body.branch_code,
            physical_address=body.physical_address,
            connected_backend_endpoint=body.connected_backend_endpoint,
            initial_cassettes=body.initial_cassettes,
        )
        db.commit()
        return _build_status_response(atm)
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.post(
    "/{atm_id}/refill",
    response_model=ATMRefillResponse,
    summary="Refill ATM cash cassette (admin)",
)
def refill_cassette(
    atm_id: str,
    body: ATMRefillRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> ATMRefillResponse:
    from datetime import datetime, timezone
    try:
        cassette = atm_service.refill_cassette(
            db=db,
            atm_id=atm_id,
            denomination=body.denomination,
            notes_added=body.notes_added,
            admin_user_id=admin.id,
        )
        log_event(
            db, "atm_refill",
            atm_id=atm_id,
            admin_user_id=admin.id,
            description=f"Refilled {body.notes_added} x {body.denomination} notes",
        )
        db.commit()
        return ATMRefillResponse(
            atm_id=atm_id,
            denomination=body.denomination,
            notes_added=body.notes_added,
            new_note_count=cassette.note_count,
            new_total_value=cassette.total_value,
            timestamp=datetime.now(timezone.utc),
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.put(
    "/{atm_id}/status",
    response_model=ATMStatusResponse,
    summary="Update ATM status (admin)",
)
def update_status(
    atm_id: str,
    body: ATMStatusUpdateRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> ATMStatusResponse:
    try:
        atm = atm_service.update_atm_status(db, atm_id, body.status, body.reason)
        db.commit()
        return _build_status_response(atm)
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
