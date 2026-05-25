"""
Tests for cash withdrawal: success, insufficient funds, daily limits,
denomination validation, ATM out-of-cash, frozen account.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.atm_terminal import ATMTerminal
from app.models.cash_cassette import CashCassette


class TestWithdrawal:
    def test_successful_withdrawal(
        self, client: TestClient, auth_headers: dict, account: Account, atm: ATMTerminal, db: Session
    ):
        resp = client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 100
        assert data["balance_after"] == 4900.0
        assert "reference_id" in data

        db.refresh(account)
        assert account.available_balance == 4900.0

    def test_insufficient_funds(
        self, client: TestClient, auth_headers: dict, account: Account, atm: ATMTerminal, db: Session
    ):
        account.available_balance = 50.0
        db.commit()
        resp = client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "INSUFFICIENT_FUNDS"

    def test_invalid_denomination(
        self, client: TestClient, auth_headers: dict, atm: ATMTerminal
    ):
        resp = client.post("/transaction/withdraw", json={
            "amount": 35,   # not a multiple of $20
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_DENOMINATION"

    def test_exceeds_single_transaction_limit(
        self, client: TestClient, auth_headers: dict, atm: ATMTerminal
    ):
        resp = client.post("/transaction/withdraw", json={
            "amount": 600,   # default max is $500
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "TRANSACTION_LIMIT_EXCEEDED"

    def test_daily_limit_exceeded(
        self, client: TestClient, auth_headers: dict, account: Account, atm: ATMTerminal, db: Session
    ):
        account.daily_withdrawal_used = 980.0   # only $20 remaining
        db.commit()
        resp = client.post("/transaction/withdraw", json={
            "amount": 40,
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "DAILY_LIMIT_EXCEEDED"

    def test_frozen_account_cannot_withdraw(
        self, client: TestClient, auth_headers: dict, account: Account, atm: ATMTerminal, db: Session
    ):
        account.account_status = "frozen"
        db.commit()
        resp = client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "ACCOUNT_FROZEN"

    def test_atm_out_of_cash(
        self, client: TestClient, auth_headers: dict, atm: ATMTerminal, db: Session
    ):
        # Drain the cassette
        cassette = db.query(CashCassette).filter(CashCassette.atm_id == atm.id).first()
        cassette.note_count = 0
        atm.total_cash_available = 0.0
        atm.terminal_status = "out_of_cash"
        db.commit()

        resp = client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        }, headers=auth_headers)
        assert resp.status_code == 503

    def test_atm_cassette_decremented(
        self, client: TestClient, auth_headers: dict, atm: ATMTerminal, db: Session
    ):
        cassette = db.query(CashCassette).filter(CashCassette.atm_id == atm.id).first()
        initial_count = cassette.note_count

        client.post("/transaction/withdraw", json={
            "amount": 100,   # 5 × $20 notes
            "atm_id": atm.id,
        }, headers=auth_headers)

        db.refresh(cassette)
        assert cassette.note_count == initial_count - 5

    def test_withdrawal_updates_daily_used(
        self, client: TestClient, auth_headers: dict, account: Account, atm: ATMTerminal, db: Session
    ):
        client.post("/transaction/withdraw", json={
            "amount": 200,
            "atm_id": atm.id,
        }, headers=auth_headers)
        db.refresh(account)
        assert account.daily_withdrawal_used == 200.0

    def test_unauthenticated_withdrawal_rejected(self, client: TestClient, atm: ATMTerminal):
        resp = client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        })
        assert resp.status_code == 401

    def test_low_cash_alert_logged(
        self, client: TestClient, auth_headers: dict, atm: ATMTerminal, db: Session
    ):
        """After withdrawal that drops ATM below threshold, audit log should have low_cash_alert."""
        from app.models.audit_log import AuditLog

        # Set ATM cash just above threshold (default $5000)
        cassette = db.query(CashCassette).filter(CashCassette.atm_id == atm.id).first()
        cassette.note_count = 252   # 252 × $20 = $5,040
        atm.total_cash_available = 5040.0
        db.commit()

        client.post("/transaction/withdraw", json={
            "amount": 100,
            "atm_id": atm.id,
        }, headers=auth_headers)

        alert = db.query(AuditLog).filter(AuditLog.event_type == "low_cash_alert").first()
        assert alert is not None
