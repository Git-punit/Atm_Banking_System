"""
Pydantic schemas for transaction endpoints.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class WithdrawalRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to withdraw (must be a multiple of ATM denomination)")
    atm_id: str = Field(..., description="ATM terminal processing this withdrawal")

    @field_validator("amount")
    @classmethod
    def must_be_positive_integer(cls, v: float) -> float:
        if v != int(v):
            raise ValueError("Withdrawal amount must be a whole number")
        if v <= 0:
            raise ValueError("Withdrawal amount must be positive")
        return v


class WithdrawalResponse(BaseModel):
    reference_id: str
    amount: float
    currency: str
    balance_after: float
    atm_id: str
    timestamp: datetime
    message: str = "Withdrawal successful"


class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0)
    atm_id: str

    @field_validator("amount")
    @classmethod
    def must_be_positive_integer(cls, v: float) -> float:
        if v != int(v):
            raise ValueError("Deposit amount must be a whole number")
        return v


class DepositResponse(BaseModel):
    reference_id: str
    amount: float
    currency: str
    available_balance: float
    total_balance: float
    hold_release_date: Optional[str]
    timestamp: datetime
    message: str = "Deposit successful"


class TransferRequest(BaseModel):
    destination_account_number: str = Field(..., min_length=5, max_length=20)
    amount: float = Field(..., gt=0)
    description: Optional[str] = Field(None, max_length=200)

    @field_validator("amount")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Transfer amount must be positive")
        return round(v, 2)


class TransferResponse(BaseModel):
    reference_id: str
    debit_reference_id: str
    credit_reference_id: str
    amount: float
    currency: str
    destination_account: str
    balance_after: float
    timestamp: datetime
    message: str = "Transfer successful"


class TransactionRecord(BaseModel):
    reference_id: str
    transaction_type: str
    amount: float
    currency: str
    balance_after: float
    description: Optional[str]
    timestamp: datetime
    status: str

    class Config:
        from_attributes = True


class MiniStatementResponse(BaseModel):
    account_number: str
    account_holder_name: str
    transactions: List[TransactionRecord]
    total_records: int
    generated_at: datetime


class TransactionHistoryRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    transaction_type: Optional[
        Literal[
            "withdrawal", "deposit", "transfer_debit",
            "transfer_credit", "balance_inquiry", "reversal"
        ]
    ] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    export_format: Optional[Literal["json", "csv"]] = None


class TransactionHistoryResponse(BaseModel):
    account_number: str
    transactions: List[TransactionRecord]
    page: int
    page_size: int
    total_records: int
    total_pages: int
