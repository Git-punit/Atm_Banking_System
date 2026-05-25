"""
Transaction router.

POST /transaction/withdraw  — cash withdrawal
POST /transaction/deposit   — cash deposit
POST /transaction/transfer  — fund transfer
GET  /transaction/history   — paginated transaction history
GET  /transaction/statement — mini-statement (last 10 transactions)
"""
import math
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.exceptions import ATMBaseException
from app.database import get_db
from app.dependencies import get_current_account, get_current_session
from app.models.account import Account
from app.models.atm_terminal import ATMTerminal
from app.models.session import ATMSession
from app.schemas.transaction import (
    DepositRequest,
    DepositResponse,
    MiniStatementResponse,
    TransactionHistoryResponse,
    TransactionRecord,
    TransferRequest,
    TransferResponse,
    WithdrawalRequest,
    WithdrawalResponse,
)
from app.services import deposit_service, transaction_service, transfer_service, withdrawal_service

router = APIRouter(prefix="/transaction", tags=["Transactions"])


def _get_atm(db: Session, atm_id: str) -> ATMTerminal:
    atm = db.query(ATMTerminal).filter(ATMTerminal.id == atm_id).first()
    if not atm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "ATM_NOT_FOUND", "message": f"ATM {atm_id} not found"},
        )
    return atm


# ── Withdrawal ────────────────────────────────────────────────────────────────

@router.post(
    "/withdraw",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_200_OK,
    summary="Cash withdrawal",
)
def withdraw(
    request: Request,
    body: WithdrawalRequest,
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
) -> WithdrawalResponse:
    atm = _get_atm(db, body.atm_id)
    try:
        txn = withdrawal_service.process_withdrawal(
            db=db,
            account=account,
            atm=atm,
            amount=body.amount,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        return WithdrawalResponse(
            reference_id=txn.reference_id,
            amount=txn.amount,
            currency=txn.currency,
            balance_after=txn.balance_after,
            atm_id=body.atm_id,
            timestamp=txn.created_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Withdrawal failed"},
        ) from exc


# ── Deposit ───────────────────────────────────────────────────────────────────

@router.post(
    "/deposit",
    response_model=DepositResponse,
    status_code=status.HTTP_200_OK,
    summary="Cash deposit",
)
def deposit(
    request: Request,
    body: DepositRequest,
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
) -> DepositResponse:
    atm = _get_atm(db, body.atm_id)
    try:
        result = deposit_service.process_deposit(
            db=db,
            account=account,
            atm=atm,
            amount=body.amount,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        txn = result["transaction"]
        hold_date = result["hold_release_date"]
        return DepositResponse(
            reference_id=txn.reference_id,
            amount=txn.amount,
            currency=txn.currency,
            available_balance=account.available_balance,
            total_balance=account.total_balance,
            hold_release_date=str(hold_date) if hold_date else None,
            timestamp=txn.created_at,
        )
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Deposit failed"},
        ) from exc


# ── Transfer ──────────────────────────────────────────────────────────────────

@router.post(
    "/transfer",
    response_model=TransferResponse,
    status_code=status.HTTP_200_OK,
    summary="Fund transfer",
)
def transfer(
    request: Request,
    body: TransferRequest,
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
) -> TransferResponse:
    try:
        result = transfer_service.process_transfer(
            db=db,
            source_account=account,
            destination_account_number=body.destination_account_number,
            amount=body.amount,
            description=body.description,
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        return TransferResponse(**result)
    except ATMBaseException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INTERNAL_ERROR", "message": "Transfer failed"},
        ) from exc


# ── Mini-statement ────────────────────────────────────────────────────────────

@router.get(
    "/statement",
    response_model=MiniStatementResponse,
    status_code=status.HTTP_200_OK,
    summary="Mini-statement (last 10 transactions)",
)
def mini_statement(
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
) -> MiniStatementResponse:
    transactions = transaction_service.get_mini_statement(db, account, limit=10)
    return MiniStatementResponse(
        account_number=account.account_number,
        account_holder_name=account.account_holder_name,
        transactions=[
            TransactionRecord(
                reference_id=t.reference_id,
                transaction_type=t.transaction_type,
                amount=t.amount,
                currency=t.currency,
                balance_after=t.balance_after,
                description=t.description,
                timestamp=t.created_at,
                status=t.status,
            )
            for t in transactions
        ],
        total_records=len(transactions),
        generated_at=datetime.now(timezone.utc),
    )


# ── Transaction history ───────────────────────────────────────────────────────

@router.get(
    "/history",
    response_model=TransactionHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Paginated transaction history",
)
def transaction_history(
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    transaction_type: str = Query(default=None),
    date_from: datetime = Query(default=None),
    date_to: datetime = Query(default=None),
    export_format: str = Query(default=None, pattern="^(json|csv)$"),
):
    transactions, total = transaction_service.get_transaction_history(
        db=db,
        account=account,
        page=page,
        page_size=page_size,
        transaction_type=transaction_type,
        date_from=date_from,
        date_to=date_to,
    )

    if export_format == "csv":
        csv_content = transaction_service.export_transactions_csv(transactions)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=transactions_{account.account_number}.csv"
                )
            },
        )

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return TransactionHistoryResponse(
        account_number=account.account_number,
        transactions=[
            TransactionRecord(
                reference_id=t.reference_id,
                transaction_type=t.transaction_type,
                amount=t.amount,
                currency=t.currency,
                balance_after=t.balance_after,
                description=t.description,
                timestamp=t.created_at,
                status=t.status,
            )
            for t in transactions
        ],
        page=page,
        page_size=page_size,
        total_records=total,
        total_pages=total_pages,
    )
