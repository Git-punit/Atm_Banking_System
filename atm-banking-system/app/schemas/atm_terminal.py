"""
Pydantic schemas for ATM terminal endpoints.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CassetteInfo(BaseModel):
    denomination: int
    note_count: int
    total_value: float
    max_capacity: int

    class Config:
        from_attributes = True


class ATMStatusResponse(BaseModel):
    atm_id: str
    atm_code: str
    branch_code: str
    physical_address: str
    terminal_status: str
    total_cash_available: float
    cassettes: List[CassetteInfo]
    daily_transaction_count: int
    daily_transaction_volume: float
    last_serviced_at: Optional[datetime]
    updated_at: datetime


class ATMCreateRequest(BaseModel):
    atm_code: str = Field(..., min_length=3, max_length=20)
    branch_code: str = Field(..., max_length=20)
    physical_address: str = Field(..., min_length=5)
    connected_backend_endpoint: Optional[str] = None
    initial_cassettes: List[dict] = Field(
        default_factory=list,
        description="List of {denomination: int, note_count: int} dicts",
    )


class ATMRefillRequest(BaseModel):
    denomination: int = Field(..., gt=0)
    notes_added: int = Field(..., gt=0)


class ATMRefillResponse(BaseModel):
    atm_id: str
    denomination: int
    notes_added: int
    new_note_count: int
    new_total_value: float
    timestamp: datetime


class ATMStatusUpdateRequest(BaseModel):
    status: Literal["online", "offline", "maintenance", "out_of_cash"]
    reason: Optional[str] = None
