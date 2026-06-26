"""
Seed the database with default salespeople and verify the setup.
Run with:  python -m app.seed
"""

from app.database import engine, Base, SessionLocal
from app.models.salesperson import Salesperson

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


if __name__ == "__main__":
    seed()
