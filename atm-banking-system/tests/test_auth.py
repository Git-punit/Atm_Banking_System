"""
Tests for authentication: login, logout, PIN lockout, session expiry.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.card import Card
from app.models.session import ATMSession


class TestLogin:
    def test_successful_login(self, client: TestClient, card: Card, atm, db: Session):
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["account_holder_name"] == "Test User"
        assert data["masked_card_number"].startswith("****")

    def test_wrong_pin_returns_401(self, client: TestClient, card: Card, atm):
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "9999",
            "atm_id": atm.id,
        })
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PIN"

    def test_wrong_pin_increments_counter(self, client: TestClient, card: Card, atm, db: Session):
        client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "9999",
            "atm_id": atm.id,
        })
        db.refresh(card)
        assert card.failed_attempt_count == 1

    def test_three_wrong_pins_locks_card(self, client: TestClient, card: Card, atm, db: Session):
        for _ in range(3):
            client.post("/auth/login", json={
                "card_number": card.card_number,
                "pin": "9999",
                "atm_id": atm.id,
            })
        db.refresh(card)
        assert card.card_status == "blocked"
        assert card.failed_attempt_count >= 3

    def test_locked_card_cannot_login(self, client: TestClient, card: Card, atm, db: Session):
        card.failed_attempt_count = 3
        card.card_status = "blocked"
        db.commit()

        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code in (401, 403)

    def test_invalid_luhn_card_number_rejected(self, client: TestClient, atm):
        resp = client.post("/auth/login", json={
            "card_number": "1234567890123456",   # fails Luhn
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 422   # Pydantic validation error

    def test_blocked_card_returns_403(self, client: TestClient, card: Card, atm, db: Session):
        card.card_status = "blocked"
        db.commit()
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "CARD_BLOCKED"

    def test_lost_card_returns_403(self, client: TestClient, card: Card, atm, db: Session):
        card.lost_or_stolen_flag = True
        db.commit()
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "CARD_LOST_OR_STOLEN"

    def test_successful_login_resets_failed_attempts(
        self, client: TestClient, card: Card, atm, db: Session
    ):
        card.failed_attempt_count = 2
        db.commit()
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 200
        db.refresh(card)
        assert card.failed_attempt_count == 0

    def test_concurrent_session_rejected(
        self, client: TestClient, card: Card, atm, active_session: ATMSession
    ):
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "CONCURRENT_SESSION"

    def test_offline_atm_rejected(self, client: TestClient, card: Card, atm, db: Session):
        atm.terminal_status = "offline"
        db.commit()
        resp = client.post("/auth/login", json={
            "card_number": card.card_number,
            "pin": "1234",
            "atm_id": atm.id,
        })
        assert resp.status_code == 503


class TestLogout:
    def test_logout_invalidates_session(
        self, client: TestClient, auth_headers: dict, active_session: ATMSession, db: Session
    ):
        resp = client.post("/auth/logout", headers=auth_headers)
        assert resp.status_code == 200
        db.refresh(active_session)
        assert active_session.is_active is False
        assert active_session.end_reason == "logout"

    def test_request_after_logout_returns_401(
        self, client: TestClient, auth_headers: dict
    ):
        client.post("/auth/logout", headers=auth_headers)
        resp = client.get("/account/balance", headers=auth_headers)
        assert resp.status_code == 401

    def test_missing_token_returns_401(self, client: TestClient):
        resp = client.post("/auth/logout")
        assert resp.status_code == 401


class TestSessionExpiry:
    def test_expired_session_returns_401(
        self, client: TestClient, auth_headers: dict, active_session: ATMSession, db: Session
    ):
        # Simulate inactivity by backdating last_activity_at
        active_session.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=200)
        db.commit()

        resp = client.get("/account/balance", headers=auth_headers)
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "SESSION_EXPIRED"
