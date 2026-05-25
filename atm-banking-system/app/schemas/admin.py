"""
Pydantic schemas for admin control panel endpoints.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class AdminCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=200)
    password: str = Field(..., min_length=8)
    role: Literal["superadmin", "admin", "auditor"] = "admin"


class AdminUserResponse(BaseModel):
    admin_id: str
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class CardBlockRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)
    mark_lost_stolen: bool = False


class CardUnblockRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class AccountFreezeRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class AccountUnfreezeRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class TransactionReportRequest(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    atm_id: Optional[str] = None
    transaction_type: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    export_format: Optional[Literal["json", "csv"]] = None


class FailedLoginReportResponse(BaseModel):
    card_number_masked: str
    failed_attempts: int
    last_attempt_at: Optional[datetime]
    card_status: str
    account_id: str


class SuspiciousActivityAlert(BaseModel):
    alert_id: str
    event_type: str
    severity: str
    masked_card_ref: Optional[str]
    masked_account_ref: Optional[str]
    atm_id: Optional[str]
    description: str
    created_at: datetime


class SystemAnnouncementRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000)
    severity: Literal["info", "warning", "critical"] = "info"
