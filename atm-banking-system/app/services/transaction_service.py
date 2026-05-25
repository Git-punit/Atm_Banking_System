"""
Transaction history and mini-statement service.

Provides paginated, filterable transaction history and
the last-10-transactions mini-statement used on ATM receipts.
"""
import csv
import io
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction


def get_mini_statement(
    db: Session,
    account: Account,
    limit: int = 10,
) -> List[Transaction]:
    """
    Return the last `limit` transactions for an account,
    sorted newest-first (reverse chronological order).
    """
    return (
        db.query(Transaction)
        .filter(Transaction.account_id == account.id)
        .order_by(desc(Transaction.created_at))
        .limit(limit)
        .all()
    )


def get_transaction_history(
    db: Session,
    account: Account,
    page: int = 1,
    page_size: int = 20,
    transaction_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Tuple[List[Transaction], int]:
    """
    Return a paginated, optionally filtered transaction history.

    Args:
        db:               Active database session.
        account:          The account whose history to retrieve.
        page:             1-based page number.
        page_size:        Records per page (max 100).
        transaction_type: Filter by type (withdrawal, deposit, etc.).
        date_from:        Inclusive start datetime filter.
        date_to:          Inclusive end datetime filter.

    Returns:
        Tuple of (list of Transaction records, total record count).
    """
    query = db.query(Transaction).filter(Transaction.account_id == account.id)

    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)

    if date_from:
        query = query.filter(Transaction.created_at >= date_from)

    if date_to:
        query = query.filter(Transaction.created_at <= date_to)

    total = query.count()

    transactions = (
        query.order_by(desc(Transaction.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return transactions, total


def export_transactions_csv(transactions: List[Transaction]) -> str:
    """
    Serialize a list of Transaction records to a CSV string.

    Returns the CSV content as a UTF-8 string.
    """
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "reference_id",
            "transaction_type",
            "amount",
            "currency",
            "balance_after",
            "description",
            "status",
            "created_at",
        ],
    )
    writer.writeheader()
    for txn in transactions:
        writer.writerow(
            {
                "reference_id": txn.reference_id,
                "transaction_type": txn.transaction_type,
                "amount": txn.amount,
                "currency": txn.currency,
                "balance_after": txn.balance_after,
                "description": txn.description or "",
                "status": txn.status,
                "created_at": txn.created_at.isoformat(),
            }
        )
    return output.getvalue()
