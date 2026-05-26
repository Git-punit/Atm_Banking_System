
import math
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.exceptions import ATMBaseException
from app.database import get_db
from app.dependencies import get_current_admin, require_role
from app.models.admin import AdminUser
from app.schemas.account import AccountCreateRequest, AccountCreateResponse, AccountSummary
from app.schemas.admin import (
    AccountFreezeRequest,
    AccountUnfreezeRequest,
    AdminCreateRequest,
    AdminUserResponse,
    CardBlockRequest,
    CardUnblockRequest,
    FailedLoginReportResponse,
    SuspiciousActivityAlert,
    TransactionReportRequest,
)
from app.schemas.transaction import TransactionHistoryResponse, TransactionRecord
from app.services import account_service, admin_service
from app.services.transaction_service import export_transactions_csv

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post(
    "/accounts/create",
    response_model=AccountCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new bank account",
)
def create_account(
    body: AccountCreateRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> AccountCreateResponse:
    try:
        account = account_service.create_account(
            db=db,
            account_holder_name=body.account_holder_name,
            account_type=body.account_type,
            branch_code=body.branch_code,
            currency=body.currency,
            daily_withdrawal_limit=body.daily_withdrawal_limit,
            daily_transfer_limit=body.daily_transfer_limit,
            initial_deposit=body.initial_deposit,
            is_joint_account=body.is_joint_account,
        )
        db.commit()
        return AccountCreateResponse(
            account_id=account.id,
            account_number=account.account_number,
            account_holder_name=account.account_holder_name,
            account_type=account.account_type,
            available_balance=account.available_balance,
            currency=account.currency,
            created_at=account.created_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.get(
    "/accounts",
    response_model=List[AccountSummary],
    summary="List all accounts",
)
def list_accounts(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> List[AccountSummary]:
    from app.models.account import Account
    accounts = (
        db.query(Account)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [
        AccountSummary(
            account_id=a.id,
            account_number=a.account_number,
            account_holder_name=a.account_holder_name,
            account_type=a.account_type,
            account_status=a.account_status,
            available_balance=a.available_balance,
            currency=a.currency,
            branch_code=a.branch_code,
            kyc_verification_status=a.kyc_verification_status,
            created_at=a.created_at,
        )
        for a in accounts
    ]


@router.put(
    "/accounts/{account_id}/freeze",
    response_model=AccountSummary,
    summary="Freeze an account",
)
def freeze_account(
    account_id: str,
    body: AccountFreezeRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> AccountSummary:
    try:
        account = admin_service.freeze_account(db, account_id, body.reason, admin.id)
        db.commit()
        return AccountSummary(
            account_id=account.id,
            account_number=account.account_number,
            account_holder_name=account.account_holder_name,
            account_type=account.account_type,
            account_status=account.account_status,
            available_balance=account.available_balance,
            currency=account.currency,
            branch_code=account.branch_code,
            kyc_verification_status=account.kyc_verification_status,
            created_at=account.created_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.put(
    "/accounts/{account_id}/unfreeze",
    response_model=AccountSummary,
    summary="Unfreeze an account",
)
def unfreeze_account(
    account_id: str,
    body: AccountUnfreezeRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin", "admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> AccountSummary:
    try:
        account = admin_service.unfreeze_account(db, account_id, body.reason, admin.id)
        db.commit()
        return AccountSummary(
            account_id=account.id,
            account_number=account.account_number,
            account_holder_name=account.account_holder_name,
            account_type=account.account_type,
            account_status=account.account_status,
            available_balance=account.available_balance,
            currency=account.currency,
            branch_code=account.branch_code,
            kyc_verification_status=account.kyc_verification_status,
            created_at=account.created_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.post(
    "/cards/block",
    status_code=status.HTTP_200_OK,
    summary="Block a card",
)
def block_card(
    body: CardBlockRequest,
    card_number: str = Query(..., min_length=16, max_length=16),
    admin: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    try:
        card = admin_service.block_card(
            db, card_number, body.reason, body.mark_lost_stolen, admin.id
        )
        db.commit()
        return {"message": f"Card {card.masked_number} blocked successfully"}
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.post(
    "/cards/unblock",
    status_code=status.HTTP_200_OK,
    summary="Unblock a card",
)
def unblock_card(
    body: CardUnblockRequest,
    card_number: str = Query(..., min_length=16, max_length=16),
    admin: AdminUser = Depends(require_role("superadmin", "admin")),
    db: Session = Depends(get_db),
):
    try:
        card = admin_service.unblock_card(db, card_number, body.reason, admin.id)
        db.commit()
        return {"message": f"Card {card.masked_number} unblocked successfully"}
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.get(
    "/reports/transactions",
    summary="Transaction volume report",
)
def transaction_report(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    atm_id: Optional[str] = Query(default=None),
    transaction_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    export_format: Optional[str] = Query(default=None, pattern="^(json|csv)$"),
):
    transactions, total = admin_service.get_transaction_report(
        db=db,
        date_from=date_from,
        date_to=date_to,
        atm_id=atm_id,
        transaction_type=transaction_type,
        page=page,
        page_size=page_size,
    )

    if export_format == "csv":
        csv_content = export_transactions_csv(transactions)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transaction_report.csv"},
        )

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "transactions": [
            {
                "reference_id": t.reference_id,
                "account_id": t.account_id,
                "atm_id": t.atm_id,
                "transaction_type": t.transaction_type,
                "amount": t.amount,
                "currency": t.currency,
                "balance_after": t.balance_after,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
            }
            for t in transactions
        ],
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "total_pages": total_pages,
    }


@router.get(
    "/reports/failed-logins",
    response_model=List[FailedLoginReportResponse],
    summary="Cards with failed login attempts",
)
def failed_login_report(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> List[FailedLoginReportResponse]:
    cards = admin_service.get_failed_login_summary(db)
    return [
        FailedLoginReportResponse(
            card_number_masked=c.masked_number,
            failed_attempts=c.failed_attempt_count,
            last_attempt_at=c.last_used_timestamp,
            card_status=c.card_status,
            account_id=c.linked_account_id,
        )
        for c in cards
    ]


@router.get(
    "/reports/suspicious",
    response_model=List[SuspiciousActivityAlert],
    summary="Suspicious activity alerts",
)
def suspicious_activity(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> List[SuspiciousActivityAlert]:
    logs = admin_service.get_suspicious_activity(db, limit=limit)
    return [
        SuspiciousActivityAlert(
            alert_id=log.id,
            event_type=log.event_type,
            severity=log.severity,
            masked_card_ref=log.masked_card_ref,
            masked_account_ref=log.masked_account_ref,
            atm_id=log.atm_id,
            description=log.description or "",
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.post(
    "/users/create",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create admin user (superadmin only)",
)
def create_admin_user(
    body: AdminCreateRequest,
    admin: Annotated[AdminUser, Depends(require_role("superadmin"))],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserResponse:
    try:
        new_admin = admin_service.create_admin(
            db=db,
            username=body.username,
            email=body.email,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
        )
        db.commit()
        return AdminUserResponse(
            admin_id=new_admin.id,
            username=new_admin.username,
            email=new_admin.email,
            full_name=new_admin.full_name,
            role=new_admin.role,
            is_active=new_admin.is_active,
            created_at=new_admin.created_at,
            last_login_at=new_admin.last_login_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
