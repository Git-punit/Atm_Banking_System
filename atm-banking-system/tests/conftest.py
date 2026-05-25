"""
Pytest fixtures shared across all test modules.

Uses an in-memory SQLite database so tests are fast, isolated,
and require no external services.
"""
import random
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.luhn import generate_luhn_check_digit
from app.core.security import create_admin_token, create_access_token, hash_pin
from app.database import Base, get_db
from app.main import create_app
from app.models.account import Account
from app.models.admin import AdminUser
from app.models.atm_terminal import ATMTerminal
from app.models.card import Card
from app.models.cash_cassette import CashCassette
from app.models.session import ATMSession

# ── In-memory test database ───────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

# Deterministic seed
random.seed(42)


def generate_test_card_number(prefix: str = "4532") -> str:
    partial = prefix + "".join([str(random.randint(0, 9)) for _ in range(11)])
    check = generate_luhn_check_digit(partial)
    return partial + str(check)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """
    Provide a fresh database session for each test.
    All tables are created before the test and dropped after.
    """
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """
    Provide a FastAPI TestClient with the test DB injected.
    """
    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Domain fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def atm(db: Session) -> ATMTerminal:
    """A fully stocked, online ATM terminal."""
    terminal = ATMTerminal(
        atm_code="ATM-TEST-001",
        branch_code="HQ001",
        physical_address="1 Test Street",
        terminal_status="online",
        total_cash_available=10000.0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(terminal)
    db.flush()

    cassette = CashCassette(
        atm_id=terminal.id,
        denomination=20,
        note_count=500,   # 500 × $20 = $10,000
        updated_at=datetime.now(timezone.utc),
    )
    db.add(cassette)
    db.commit()
    return terminal


@pytest.fixture
def account(db: Session) -> Account:
    """An active savings account with $5,000 balance."""
    acc = Account(
        account_number="ACC000001",
        account_holder_name="Test User",
        account_type="savings",
        available_balance=5000.0,
        total_balance=5000.0,
        daily_withdrawal_limit=1000.0,
        daily_transfer_limit=5000.0,
        account_status="active",
        kyc_verification_status="verified",
        branch_code="HQ001",
        currency="USD",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def card(db: Session, account: Account) -> Card:
    """An active card linked to the test account with PIN=1234."""
    c = Card(
        card_number=generate_test_card_number(),
        linked_account_id=account.id,
        pin_hash=hash_pin("1234"),
        card_status="active",
        expiry_date=date.today() + timedelta(days=365 * 3),
        daily_withdrawal_limit=1000.0,
        failed_attempt_count=0,
        issued_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def active_session(db: Session, card: Card, account: Account, atm: ATMTerminal) -> ATMSession:
    """An active ATM session for the test card."""
    import uuid
    jti = str(uuid.uuid4())
    session = ATMSession(
        card_id=card.id,
        account_id=account.id,
        atm_id=atm.id,
        jti=jti,
        is_active=True,
        started_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def auth_headers(active_session: ATMSession, card: Card, account: Account, atm: ATMTerminal) -> dict:
    """Authorization headers with a valid JWT for the test session."""
    token = create_access_token(
        card_id=card.id,
        account_id=account.id,
        atm_id=atm.id,
        jti=active_session.jti,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_user(db: Session) -> AdminUser:
    """A superadmin user."""
    admin = AdminUser(
        username="testadmin",
        email="testadmin@bank.com",
        full_name="Test Admin",
        password_hash=hash_pin("Admin@1234"),
        role="superadmin",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    db.commit()
    return admin


@pytest.fixture
def admin_headers(admin_user: AdminUser) -> dict:
    """Authorization headers with a valid admin JWT."""
    token = create_admin_token(admin_id=admin_user.id, role=admin_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_account(db: Session) -> Account:
    """A second active account for transfer tests."""
    acc = Account(
        account_number="ACC000002",
        account_holder_name="Transfer Target",
        account_type="savings",
        available_balance=1000.0,
        total_balance=1000.0,
        daily_withdrawal_limit=1000.0,
        daily_transfer_limit=5000.0,
        account_status="active",
        kyc_verification_status="verified",
        branch_code="HQ001",
        currency="USD",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc)
    db.commit()
    return acc
