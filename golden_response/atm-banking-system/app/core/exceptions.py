
from typing import Optional


class ATMBaseException(Exception):
    """Root exception for all application-level errors."""

    http_status: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or message

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "message": self.message,
        }


# --- card / auth errors ---

class InvalidCardNumberError(ATMBaseException):
    http_status = 400
    error_code = "INVALID_CARD_NUMBER"


class CardNotFoundError(ATMBaseException):
    http_status = 404
    error_code = "CARD_NOT_FOUND"


class CardExpiredError(ATMBaseException):
    http_status = 403
    error_code = "CARD_EXPIRED"


class CardBlockedError(ATMBaseException):
    http_status = 403
    error_code = "CARD_BLOCKED"


class CardLostOrStolenError(ATMBaseException):
    http_status = 403
    error_code = "CARD_LOST_OR_STOLEN"


class InvalidPINError(ATMBaseException):
    http_status = 401
    error_code = "INVALID_PIN"


class AccountLockedError(ATMBaseException):
    """Raised after MAX_PIN_ATTEMPTS consecutive failures."""
    http_status = 403
    error_code = "ACCOUNT_LOCKED"


class SessionExpiredError(ATMBaseException):
    http_status = 401
    error_code = "SESSION_EXPIRED"


class SessionNotFoundError(ATMBaseException):
    http_status = 401
    error_code = "SESSION_NOT_FOUND"


class ConcurrentSessionError(ATMBaseException):
    """Raised when a second session is attempted for the same card."""
    http_status = 409
    error_code = "CONCURRENT_SESSION"


class UnauthorizedError(ATMBaseException):
    http_status = 403
    error_code = "UNAUTHORIZED"


# --- account errors ---

class AccountNotFoundError(ATMBaseException):
    http_status = 404
    error_code = "ACCOUNT_NOT_FOUND"


class AccountFrozenError(ATMBaseException):
    http_status = 403
    error_code = "ACCOUNT_FROZEN"


class AccountClosedError(ATMBaseException):
    http_status = 403
    error_code = "ACCOUNT_CLOSED"


class KYCNotVerifiedError(ATMBaseException):
    http_status = 403
    error_code = "KYC_NOT_VERIFIED"


# --- transaction errors ---

class InsufficientFundsError(ATMBaseException):
    http_status = 422
    error_code = "INSUFFICIENT_FUNDS"


class DailyLimitExceededError(ATMBaseException):
    http_status = 422
    error_code = "DAILY_LIMIT_EXCEEDED"


class InvalidAmountError(ATMBaseException):
    http_status = 400
    error_code = "INVALID_AMOUNT"


class InvalidDenominationError(ATMBaseException):
    http_status = 400
    error_code = "INVALID_DENOMINATION"


class TransactionLimitExceededError(ATMBaseException):
    http_status = 422
    error_code = "TRANSACTION_LIMIT_EXCEEDED"


class DepositCeilingExceededError(ATMBaseException):
    http_status = 422
    error_code = "DEPOSIT_CEILING_EXCEEDED"


class TransferRollbackError(ATMBaseException):
    """Raised when a transfer's credit leg fails and the debit is rolled back."""
    http_status = 500
    error_code = "TRANSFER_ROLLBACK"


# --- ATM hardware/status errors ---

class ATMNotFoundError(ATMBaseException):
    http_status = 404
    error_code = "ATM_NOT_FOUND"


class ATMOfflineError(ATMBaseException):
    http_status = 503
    error_code = "ATM_OFFLINE"


class ATMOutOfCashError(ATMBaseException):
    http_status = 503
    error_code = "ATM_OUT_OF_CASH"


class InsufficientATMCashError(ATMBaseException):
    """ATM has cash but not enough for this specific withdrawal."""
    http_status = 503
    error_code = "INSUFFICIENT_ATM_CASH"


# --- admin errors ---

class AdminNotFoundError(ATMBaseException):
    http_status = 404
    error_code = "ADMIN_NOT_FOUND"


class AdminAuthError(ATMBaseException):
    http_status = 401
    error_code = "ADMIN_AUTH_FAILED"


class InsufficientPermissionsError(ATMBaseException):
    http_status = 403
    error_code = "INSUFFICIENT_PERMISSIONS"


# --- infrastructure errors ---

class DatabaseError(ATMBaseException):
    http_status = 500
    error_code = "DATABASE_ERROR"


class ConcurrencyError(ATMBaseException):
    """Raised when an optimistic lock or row-level lock fails."""
    http_status = 409
    error_code = "CONCURRENCY_ERROR"
