from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.customer import Customer
from app.models.customer_contact import CustomerContact
from app.models.customer_note import CustomerNote
from app.models.project import Project
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate, CustomerUpdate, CustomerOut, CustomerDetailOut,
    CustomerContactCreate, CustomerContactUpdate, CustomerContactOut,
    CustomerNoteCreate, CustomerNoteOut,
)
from app.services.auth import get_current_user

router = APIRouter(prefix="/customers", tags=["Customers"], dependencies=[Depends(get_current_user)])


# ------------------------------------------------------------------ #
#  Access control                                                     #
# ------------------------------------------------------------------ #
# A Customer isn't owned by one salesperson the way a Project is —
# several reps can share a client over time — so a "sales" account can
# see a customer if either they created it, or they have >=1 project
# against it. Importing _enrich_projects from projects.py keeps the
# project-summary shape in sync with that router instead of drifting
# into a second implementation.
from app.routers.projects import _enrich_projects


def _customer_visible_to(customer: Customer, current_user: User, db: Session) -> bool:
    if current_user.role == "admin":
        return True
    if customer.created_by_id == current_user.id:
        return True
    if current_user.salesperson_id is None:
        return False
    has_project = db.query(Project.id).filter(
        Project.customer_id == customer.id,
        Project.salesperson_id == current_user.salesperson_id,
    ).first()
    return has_project is not None


def _get_customer_or_404(customer_id: int, db: Session, current_user: User) -> Customer:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found.")
    if not _customer_visible_to(customer, current_user, db):
        raise HTTPException(403, "You don't have access to this customer.")
    return customer


# ------------------------------------------------------------------ #
#  Customers                                                          #
# ------------------------------------------------------------------ #

@router.get("/", response_model=list[CustomerOut])
def list_customers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    customers = db.query(Customer).order_by(Customer.company_name).all()
    if current_user.role != "admin":
        customers = [c for c in customers if _customer_visible_to(c, current_user, db)]

    primary_contacts = dict(
        (c.customer_id, c)
        for c in db.query(CustomerContact).filter(CustomerContact.is_primary == True).all()
    )
    project_counts = dict(
        db.query(Project.customer_id, func.count(Project.id))
        .group_by(Project.customer_id).all()
    )

    out = []
    for c in customers:
        co = CustomerOut.model_validate(c)
        primary = primary_contacts.get(c.id)
        if primary:
            co.primary_contact_name = primary.name
            co.primary_contact_email = primary.email
        co.project_count = project_counts.get(c.id, 0)
        out.append(co)
    return out


@router.post("/", response_model=CustomerOut, status_code=201)
def create_customer(data: CustomerCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    customer = Customer(**data.model_dump(), created_by_id=current_user.id)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerDetailOut)
def get_customer(customer_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    customer = _get_customer_or_404(customer_id, db, current_user)

    contacts = (
        db.query(CustomerContact)
        .filter(CustomerContact.customer_id == customer_id)
        .order_by(CustomerContact.is_primary.desc(), CustomerContact.created_at)
        .all()
    )
    notes = (
        db.query(CustomerNote)
        .filter(CustomerNote.customer_id == customer_id)
        .order_by(CustomerNote.created_at.desc())
        .all()
    )
    user_names = dict(db.query(User.id, User.name).all())
    note_outs = []
    for n in notes:
        no = CustomerNoteOut.model_validate(n)
        no.author_name = user_names.get(n.author_id)
        note_outs.append(no)

    projects = db.query(Project).filter(Project.customer_id == customer_id).order_by(Project.created_at.desc()).all()

    detail = CustomerDetailOut.model_validate(customer)
    detail.contacts = [CustomerContactOut.model_validate(c) for c in contacts]
    detail.notes = note_outs
    detail.projects = _enrich_projects(projects, db)
    primary = next((c for c in contacts if c.is_primary), None)
    if primary:
        detail.primary_contact_name = primary.name
        detail.primary_contact_email = primary.email
    detail.project_count = len(projects)
    return detail


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    customer = _get_customer_or_404(customer_id, db, current_user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer


# ------------------------------------------------------------------ #
#  Contacts                                                            #
# ------------------------------------------------------------------ #

@router.post("/{customer_id}/contacts", response_model=CustomerContactOut, status_code=201)
def add_contact(customer_id: int, data: CustomerContactCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_customer_or_404(customer_id, db, current_user)

    existing_contacts = db.query(CustomerContact).filter(CustomerContact.customer_id == customer_id).all()
    is_first_contact = len(existing_contacts) == 0
    make_primary = data.is_primary or is_first_contact

    if make_primary:
        db.query(CustomerContact).filter(
            CustomerContact.customer_id == customer_id, CustomerContact.is_primary == True
        ).update({"is_primary": False})

    contact = CustomerContact(customer_id=customer_id, **{**data.model_dump(), "is_primary": make_primary})
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.patch("/{customer_id}/contacts/{contact_id}", response_model=CustomerContactOut)
def update_contact(customer_id: int, contact_id: int, data: CustomerContactUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_customer_or_404(customer_id, db, current_user)
    contact = db.get(CustomerContact, contact_id)
    if not contact or contact.customer_id != customer_id:
        raise HTTPException(404, "Contact not found.")

    updates = data.model_dump(exclude_none=True)
    if updates.get("is_primary") is True:
        db.query(CustomerContact).filter(
            CustomerContact.customer_id == customer_id, CustomerContact.is_primary == True
        ).update({"is_primary": False})

    for field, value in updates.items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{customer_id}/contacts/{contact_id}", status_code=204)
def delete_contact(customer_id: int, contact_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_customer_or_404(customer_id, db, current_user)
    contact = db.get(CustomerContact, contact_id)
    if not contact or contact.customer_id != customer_id:
        raise HTTPException(404, "Contact not found.")
    db.delete(contact)
    db.commit()


# ------------------------------------------------------------------ #
#  Notes (communication log — append-only)                            #
# ------------------------------------------------------------------ #

@router.post("/{customer_id}/notes", response_model=CustomerNoteOut, status_code=201)
def add_note(
    customer_id: int,
    data: CustomerNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_customer_or_404(customer_id, db, current_user)
    note = CustomerNote(customer_id=customer_id, author_id=current_user.id, body=data.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    out = CustomerNoteOut.model_validate(note)
    out.author_name = current_user.name
    return out
