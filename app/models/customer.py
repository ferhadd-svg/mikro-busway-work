from sqlalchemy import String, Text, Boolean
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
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
