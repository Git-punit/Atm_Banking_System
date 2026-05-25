"""
Pydantic schemas for authentication endpoints.
"""
from pydantic import BaseModel, Field, field_validator

from app.core.luhn import is_valid_card_number


class LoginRequest(BaseModel):
    card_number: str = Field(..., min_length=16, max_length=16, examples=["4532015112830366"])
    pin: str = Field(..., min_length=4, max_length=6, examples=["1234"])
    atm_id: str = Field(..., description="ATM terminal ID where the card is inserted")

    @field_validator("card_number")
    @classmethod
    def validate_card_number(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("Card number must contain only digits")
        if not is_valid_card_number(v):
            raise ValueError("Invalid card number (Luhn check failed)")
        return v

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN must contain only digits")
        return v


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    account_holder_name: str
    masked_card_number: str
    session_id: str


class LogoutRequest(BaseModel):
    pass   # token is taken from Authorization header


class LogoutResponse(BaseModel):
    message: str = "Session ended successfully"


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = 1800
    admin_id: str
    role: str
