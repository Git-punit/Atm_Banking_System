"""
Seed script — populates the database with realistic sample data.

Creates:
  - 1 superadmin user
  - 3 ATM terminals with cash cassettes
  - 5 bank accounts
  - 5 ATM cards (one per account)
  - Sample transactions for each account

Usage:
    python scripts/seed_data.py
"""
import random
import sys
import os
from datetime import date, datetime, timedelta, timezone

# Make the project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.luhn import generate_luhn_check_digit
from app.core.security import hash_pin
from app.database import SessionLocal, create_all_tables
from app.models.account import Account
from app.models.admin import AdminUser
from app.models.atm_terminal import ATMTerminal
from app.models.card import Card
from app.models.cash_cassette import CashCassette
from app.models.transaction import Transaction

# Deterministic seed for reproducibility
random.seed(42)


def generate_card_number(prefix: str = "4532") -> str:
    """Generate a valid 16-digit Luhn card number."""
    partial = prefix + "".join([str(random.randint(0, 9)) for _ in range(11)])
    check = generate_luhn_check_digit(partial)
    return partial + str(check)


def seed():
    create_all_tables()
    db = SessionLocal()

    try:
        print("🌱 Seeding database...")

        # ── Admin user ────────────────────────────────────────────────────────
        existing_admin = db.query(AdminUser).filter(AdminUser.username == "superadmin").first()
        if not existing_admin:
            admin = AdminUser(
                username="superadmin",
                email="admin@atmbank.com",
                full_name="System Administrator",
                password_hash=hash_pin("Admin@1234"),
                role="superadmin",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db.add(admin)
            print("  ✓ Created superadmin (password: Admin@1234)")

        # ── ATM Terminals ─────────────────────────────────────────────────────
        atm_data = [
            {
                "atm_code": "ATM-HQ-001",
                "branch_code": "HQ001",
                "physical_address": "123 Main Street, Downtown, NY 10001",
                "cassettes": [
                    {"denomination": 20, "note_count": 500},
                    {"denomination": 50, "note_count": 300},
                    {"denomination": 100, "note_count": 200},
                ],
            },
            {
                "atm_code": "ATM-BR-002",
                "branch_code": "BR002",
                "physical_address": "456 Oak Avenue, Midtown, NY 10002",
                "cassettes": [
                    {"denomination": 20, "note_count": 400},
                    {"denomination": 50, "note_count": 200},
                ],
            },
            {
                "atm_code": "ATM-BR-003",
                "branch_code": "BR003",
                "physical_address": "789 Pine Road, Uptown, NY 10003",
                "cassettes": [
                    {"denomination": 20, "note_count": 100},   # low cash for testing
                    {"denomination": 50, "note_count": 50},
                ],
            },
        ]

        atms = []
        for data in atm_data:
            existing = db.query(ATMTerminal).filter(ATMTerminal.atm_code == data["atm_code"]).first()
            if existing:
                atms.append(existing)
                continue

            total_cash = sum(c["denomination"] * c["note_count"] for c in data["cassettes"])
            atm = ATMTerminal(
                atm_code=data["atm_code"],
                branch_code=data["branch_code"],
                physical_address=data["physical_address"],
                terminal_status="online",
                total_cash_available=float(total_cash),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(atm)
            db.flush()

            for c in data["cassettes"]:
                cassette = CashCassette(
                    atm_id=atm.id,
                    denomination=c["denomination"],
                    note_count=c["note_count"],
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(cassette)

            atms.append(atm)
            print(f"  ✓ Created ATM {data['atm_code']} (cash: ${total_cash:,})")

        db.flush()

        # ── Accounts & Cards ──────────────────────────────────────────────────
        customers = [
            {"name": "Alice Johnson",   "type": "savings",  "balance": 5000.0,  "pin": "1234"},
            {"name": "Bob Smith",       "type": "current",  "balance": 12000.0, "pin": "5678"},
            {"name": "Carol Williams",  "type": "salary",   "balance": 3500.0,  "pin": "9012"},
            {"name": "David Brown",     "type": "savings",  "balance": 800.0,   "pin": "3456"},
            {"name": "Eve Davis",       "type": "current",  "balance": 25000.0, "pin": "7890"},
        ]

        for i, customer in enumerate(customers):
            acc_number = f"ACC{100000 + i + 1:06d}"
            existing_acc = db.query(Account).filter(Account.account_number == acc_number).first()
            if existing_acc:
                print(f"  ⏭  Account {acc_number} already exists, skipping")
                continue

            account = Account(
                account_number=acc_number,
                account_holder_name=customer["name"],
                account_type=customer["type"],
                available_balance=customer["balance"],
                total_balance=customer["balance"],
                daily_withdrawal_limit=1000.0,
                daily_transfer_limit=5000.0,
                account_status="active",
                kyc_verification_status="verified",
                branch_code="HQ001",
                currency="USD",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(account)
            db.flush()

            card_number = generate_card_number()
            card = Card(
                card_number=card_number,
                linked_account_id=account.id,
                pin_hash=hash_pin(customer["pin"]),
                card_status="active",
                expiry_date=date.today() + timedelta(days=365 * 3),
                daily_withdrawal_limit=1000.0,
                failed_attempt_count=0,
                issued_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(card)
            db.flush()

            # Add some historical transactions
            atm = atms[i % len(atms)]
            for j in range(5):
                txn_type = random.choice(["withdrawal", "deposit"])
                amount = random.choice([20, 40, 60, 80, 100, 200])
                balance_snap = customer["balance"] + (j * 50)
                txn = Transaction(
                    account_id=account.id,
                    atm_id=atm.id,
                    transaction_type=txn_type,
                    amount=float(amount),
                    currency="USD",
                    balance_after=float(balance_snap),
                    status="completed",
                    description=f"Sample {txn_type}",
                    created_at=datetime.now(timezone.utc) - timedelta(days=j + 1),
                )
                db.add(txn)

            print(
                f"  ✓ Created account {acc_number} ({customer['name']}) "
                f"| card: ****{card_number[-4:]} | PIN: {customer['pin']}"
            )

        db.commit()
        print("\n✅ Seed complete!")
        print("\n📋 Login credentials:")
        print("   Admin:    username=superadmin  password=Admin@1234")
        print("   Card 1:   Alice Johnson        PIN=1234")
        print("   Card 2:   Bob Smith            PIN=5678")
        print("   Card 3:   Carol Williams       PIN=9012")
        print("   Card 4:   David Brown          PIN=3456")
        print("   Card 5:   Eve Davis            PIN=7890")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
