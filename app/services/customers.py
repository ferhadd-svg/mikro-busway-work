"""
Customer/contact matching used when a project is created (and by the
one-time seed backfill) so a client name typed on a new project links to
a real Customer record instead of staying a loose string.
"""

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_contact import CustomerContact


def get_or_create_customer(db: Session, company_name: str, contact_name: str | None = None) -> Customer:
    """Exact case-insensitive/trimmed match only — NOT fuzzy. "Acme Sdn. Bhd."
    and "ACME SDN BHD" will NOT be recognized as the same company and will
    create a duplicate Customer row. Deliberate, simple default for a small
    team; mitigated at the UX layer by a <datalist> autocomplete on the
    client-name input, not by fuzzier server-side matching.

    Used by both create_project() and the idempotent seed.py backfill, so
    this matching logic exists exactly once."""
    normalized = company_name.strip()
    customer = next(
        (c for c in db.query(Customer).all() if c.company_name.strip().lower() == normalized.lower()),
        None,
    )
    if customer is None:
        customer = Customer(company_name=normalized)
        db.add(customer)
        db.commit()
        db.refresh(customer)

    if contact_name and contact_name.strip():
        cname = contact_name.strip()
        contacts = db.query(CustomerContact).filter(CustomerContact.customer_id == customer.id).all()
        existing = next((c for c in contacts if c.name.strip().lower() == cname.lower()), None)
        if existing is None:
            db.add(CustomerContact(
                customer_id=customer.id, name=cname,
                is_primary=(len(contacts) == 0),
            ))
            db.commit()

    return customer
