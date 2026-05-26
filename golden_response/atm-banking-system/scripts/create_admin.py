"""
Interactive script to create an admin user.

Usage:
    python scripts/create_admin.py
"""
import sys
import os
import getpass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal, create_all_tables
from app.services.admin_service import create_admin


def main():
    print("=== Create Admin User ===")
    username = input("Username: ").strip()
    email = input("Email: ").strip()
    full_name = input("Full name: ").strip()
    password = getpass.getpass("Password (min 8 chars): ")
    role = input("Role [superadmin/admin/auditor] (default: admin): ").strip() or "admin"

    if len(password) < 8:
        print("❌ Password must be at least 8 characters")
        sys.exit(1)

    if role not in ("superadmin", "admin", "auditor"):
        print("❌ Invalid role")
        sys.exit(1)

    create_all_tables()
    db = SessionLocal()
    try:
        admin = create_admin(db, username, email, full_name, password, role)
        db.commit()
        print(f"\n✅ Admin user '{admin.username}' created with role '{admin.role}'")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Failed: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
