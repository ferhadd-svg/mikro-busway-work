from sqlalchemy import String, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # NOT unique at the DB level — matching is exact case-insensitive/trimmed
    # in app.services.customers.get_or_create_customer, not a SQL constraint
    # (same "invariant enforced in Python" style as PriceListVersion.is_active).
    company_name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # archive only, never hard-deleted — Project.customer_id references it
    # A customer isn't owned by one salesperson the way a Project is (several
    # reps can share a client over time), so visibility for a "sales" role
    # account is: they created it, OR they have >=1 project against it — see
    # app/routers/customers.py's _customer_visible_to. created_by_id covers
    # the first half, letting a rep see a customer they just added even
    # before any project exists for it.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
