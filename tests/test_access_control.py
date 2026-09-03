"""
Covers the IDOR fix: a "sales" role account should only reach projects and
customers tied to its own linked salesperson (or ones it created, for
customers), while "admin" always sees everything. See _get_or_404 in
app/routers/projects.py and _customer_visible_to/_get_customer_or_404 in
app/routers/customers.py.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.user import User
from app.models.salesperson import Salesperson
from app.models.project import Project
from app.models.customer import Customer
from app.routers.projects import _get_or_404
from app.routers.customers import _customer_visible_to, _get_customer_or_404


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _salesperson(db, name="Eric Wong"):
    sp = Salesperson(name=name, title="Sales Engineer", mobile="", email="")
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return sp


def _user(db, role, salesperson_id=None, email=None):
    user = User(
        email=email or f"{role}-{salesperson_id}@mikro.local",
        name="Test User",
        hashed_password="x",
        role=role,
        salesperson_id=salesperson_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _project(db, salesperson_id, our_ref="KWA-1"):
    p = Project(our_ref=our_ref, client_name="Client", salesperson_id=salesperson_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ------------------------------------------------------------------ #
#  Projects — _get_or_404                                             #
# ------------------------------------------------------------------ #

def test_admin_can_access_any_project():
    db = _db()
    sp = _salesperson(db)
    project = _project(db, sp.id)
    admin = _user(db, "admin")
    assert _get_or_404(project.id, db, admin) is project


def test_sales_user_can_access_own_project():
    db = _db()
    sp = _salesperson(db)
    project = _project(db, sp.id)
    owner = _user(db, "sales", salesperson_id=sp.id)
    assert _get_or_404(project.id, db, owner) is project


def test_sales_user_cannot_access_colleagues_project():
    db = _db()
    mine = _salesperson(db, "Eric Wong")
    theirs = _salesperson(db, "Gladness Lee")
    project = _project(db, theirs.id)
    outsider = _user(db, "sales", salesperson_id=mine.id)
    with pytest.raises(HTTPException) as exc_info:
        _get_or_404(project.id, db, outsider)
    assert exc_info.value.status_code == 403


def test_unassigned_project_returns_404_for_unknown_id():
    db = _db()
    admin = _user(db, "admin")
    with pytest.raises(HTTPException) as exc_info:
        _get_or_404(999, db, admin)
    assert exc_info.value.status_code == 404


def test_sales_user_with_no_linked_salesperson_cannot_access_assigned_project():
    """An unlinked sales account (salesperson_id=None) must not accidentally
    match projects that also happen to have salesperson_id=None via a naive
    equality check — it should only ever see projects that are also
    genuinely unassigned, never someone else's real assignment."""
    db = _db()
    sp = _salesperson(db)
    project = _project(db, sp.id)
    unlinked = _user(db, "sales", salesperson_id=None)
    with pytest.raises(HTTPException) as exc_info:
        _get_or_404(project.id, db, unlinked)
    assert exc_info.value.status_code == 403


def test_sales_user_with_no_linked_salesperson_can_access_unassigned_project():
    db = _db()
    project = _project(db, salesperson_id=None)
    unlinked = _user(db, "sales", salesperson_id=None)
    assert _get_or_404(project.id, db, unlinked) is project


# ------------------------------------------------------------------ #
#  Customers — _customer_visible_to / _get_customer_or_404           #
# ------------------------------------------------------------------ #

def test_admin_sees_any_customer():
    db = _db()
    customer = Customer(company_name="Acme")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    admin = _user(db, "admin")
    assert _customer_visible_to(customer, admin, db) is True


def test_sales_user_sees_customer_they_created():
    db = _db()
    creator = _user(db, "sales", salesperson_id=None, email="creator@mikro.local")
    customer = Customer(company_name="Acme", created_by_id=creator.id)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    assert _customer_visible_to(customer, creator, db) is True


def test_sales_user_sees_customer_via_own_project():
    db = _db()
    sp = _salesperson(db)
    customer = Customer(company_name="Acme")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    project = Project(our_ref="KWA-1", client_name="Acme", salesperson_id=sp.id, customer_id=customer.id)
    db.add(project)
    db.commit()
    rep = _user(db, "sales", salesperson_id=sp.id)
    assert _customer_visible_to(customer, rep, db) is True


def test_sales_user_cannot_see_unrelated_customer():
    db = _db()
    sp = _salesperson(db)
    customer = Customer(company_name="Acme")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    outsider = _user(db, "sales", salesperson_id=sp.id, email="outsider@mikro.local")
    assert _customer_visible_to(customer, outsider, db) is False
    with pytest.raises(HTTPException) as exc_info:
        _get_customer_or_404(customer.id, db, outsider)
    assert exc_info.value.status_code == 403


def test_get_customer_or_404_raises_404_for_unknown_id():
    db = _db()
    admin = _user(db, "admin")
    with pytest.raises(HTTPException) as exc_info:
        _get_customer_or_404(999, db, admin)
    assert exc_info.value.status_code == 404
