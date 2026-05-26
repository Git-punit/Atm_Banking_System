"""
Account router.

GET  /account/balance  — balance inquiry for the authenticated card holder
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_account, get_current_session
from app.models.account import Account
from app.models.session import ATMSession
from app.schemas.account import BalanceResponse

router = APIRouter(prefix="/account", tags=["Account"])


@router.get(
    "/balance",
    response_model=BalanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Balance inquiry",
    description="Returns available and total balance for the authenticated account.",
)
def get_balance(
    session: Annotated[ATMSession, Depends(get_current_session)],
    account: Annotated[Account, Depends(get_current_account)],
    db: Annotated[Session, Depends(get_db)],
) -> BalanceResponse:
    # Log a balance inquiry transaction
    from app.models.transaction import Transaction
    txn = Transaction(
        account_id=account.id,
        atm_id=session.atm_id,
        transaction_type="balance_inquiry",
        amount=0.0,
        currency=account.currency,
        balance_after=account.available_balance,
        status="completed",
        description="Balance inquiry",
    )
    db.add(txn)
    db.commit()

    return BalanceResponse(
        account_number=account.account_number,
        account_holder_name=account.account_holder_name,
        account_type=account.account_type,
        available_balance=account.available_balance,
        total_balance=account.total_balance,
        currency=account.currency,
        account_status=account.account_status,
        as_of=datetime.now(timezone.utc),
    )
