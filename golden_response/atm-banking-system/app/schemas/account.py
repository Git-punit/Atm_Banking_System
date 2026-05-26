"""
Pydantic schemas for account management endpoints.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class BalanceResponse(BaseModel):
    account_number: str
    account_holder_name: str
    account_type: str
    available_balance: float
    total_balance: float
    currency: str
    account_status: str
    as_of: datetime


class AccountCreateRequest(BaseModel):
    account_holder_name: str = Field(..., min_length=2, max_length=200)
    account_type: Literal["savings", "current", "salary"] = "savings"
    branch_code: str = Field(default="HQ001", max_length=20)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    daily_withdrawal_limit: float = Field(default=1000.0, gt=0)
    daily_transfer_limit: float = Field(default=5000.0, gt=0)
    initial_deposit: float = Field(default=0.0, ge=0)
    is_joint_account: bool = False


class AccountCreateResponse(BaseModel):
    account_id: str
    account_number: str
    account_holder_name: str
    account_type: str
    available_balance: float
    currency: str
    created_at: datetime


class AccountStatusUpdateRequest(BaseModel):
    status: Literal["active", "frozen", "closed", "dormant"]
    reason: Optional[str] = Field(None, max_length=500)


class AccountSummary(BaseModel):
    account_id: str
    account_number: str
    account_holder_name: str
    account_type: str
    account_status: str
    available_balance: float
    currency: str
    branch_code: str
    kyc_verification_status: str
    created_at: datetime
