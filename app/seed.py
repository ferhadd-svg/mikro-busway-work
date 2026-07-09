"""
Seed the database with default salespeople and verify the setup.
Run with:  python -m app.seed
"""

import secrets

from app.database import engine, Base, SessionLocal
from app.models.salesperson import Salesperson
from app.models.user import User
from app.services.auth import hash_password

DEFAULT_SALESPEOPLE = [
    {
        "name": "Eric Wong",
        "title": "Sales Engineer",
        "mobile": "",
        "email": "",
    },
    {
        "name": "Gladness Lee",
        "title": "Sales Engineer",
        "mobile": "",
        "email": "",
    },
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        added = []
        for sp_data in DEFAULT_SALESPEOPLE:
            exists = db.query(Salesperson).filter(Salesperson.name == sp_data["name"]).first()
            if not exists:
                sp = Salesperson(**sp_data)
                db.add(sp)
                added.append(sp_data["name"])
        db.commit()
        if added:
            print(f"[seed] Added salespeople: {', '.join(added)}")
        else:
            print("[seed] All default salespeople already present.")

        all_sp = db.query(Salesperson).all()
        print("\nCurrent salespeople:")
        for sp in all_sp:
            status = "active" if sp.is_active else "inactive"
            print(f"  [{sp.id}] {sp.name} — {sp.title} ({status})")
    finally:
        db.close()

    seed_admin_user()


def seed_admin_user():
    """Bootstrap a single admin login account if no users exist yet.
    The password is generated here and printed once — it is never stored
    in plaintext anywhere else, and never returned via any API."""
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        password = secrets.token_urlsafe(12)
        admin = User(
            email="admin@itmikro.com",
            name="Administrator",
            hashed_password=hash_password(password),
            role="admin",
        )
        db.add(admin)
        db.commit()
        print("=" * 60)
        print("[seed] No users found — created default admin account:")
        print(f"[seed]   email:    {admin.email}")
        print(f"[seed]   password: {password}")
        print("[seed] This password is shown ONLY ONCE. Log in and change it")
        print("[seed] immediately via the account menu (Change Password).")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
