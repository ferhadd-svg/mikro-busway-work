from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.user import User  # noqa: F401 — registers users table for PriceListVersion's FK
from app.models.customer import Customer
from app.models.customer_contact import CustomerContact
from app.services.customers import get_or_create_customer


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_creates_new_customer_when_no_match_exists():
    db = _db()
    customer = get_or_create_customer(db, "ACME Sdn Bhd")
    assert customer.id is not None
    assert customer.company_name == "ACME Sdn Bhd"
    assert db.query(Customer).count() == 1


def test_reuses_existing_customer_on_case_insensitive_trimmed_match():
    db = _db()
    first = get_or_create_customer(db, "Acme Sdn Bhd")
    second = get_or_create_customer(db, "  ACME SDN BHD  ")
    assert first.id == second.id
    assert db.query(Customer).count() == 1


def test_does_not_reuse_on_genuinely_different_name():
    db = _db()
    get_or_create_customer(db, "ACME Sdn Bhd")
    get_or_create_customer(db, "Rock Link Sdn Bhd")
    assert db.query(Customer).count() == 2


def test_creates_contact_and_marks_it_primary_when_first():
    db = _db()
    customer = get_or_create_customer(db, "ACME Sdn Bhd", "Ir. Lim Wei Ming")
    contacts = db.query(CustomerContact).filter(CustomerContact.customer_id == customer.id).all()
    assert len(contacts) == 1
    assert contacts[0].name == "Ir. Lim Wei Ming"
    assert contacts[0].is_primary is True


def test_reuses_existing_contact_by_case_insensitive_name_match():
    db = _db()
    customer = get_or_create_customer(db, "ACME Sdn Bhd", "Ir. Lim Wei Ming")
    get_or_create_customer(db, "ACME Sdn Bhd", "  IR. LIM WEI MING  ")
    contacts = db.query(CustomerContact).filter(CustomerContact.customer_id == customer.id).all()
    assert len(contacts) == 1


def test_second_contact_is_not_marked_primary():
    db = _db()
    customer = get_or_create_customer(db, "ACME Sdn Bhd", "Ir. Lim Wei Ming")
    get_or_create_customer(db, "ACME Sdn Bhd", "Ms. Tan")
    contacts = db.query(CustomerContact).filter(CustomerContact.customer_id == customer.id).all()
    assert len(contacts) == 2
    primaries = [c for c in contacts if c.is_primary]
    assert len(primaries) == 1
    assert primaries[0].name == "Ir. Lim Wei Ming"
