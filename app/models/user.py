from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class User(Base):
    """A login account. Separate from Salesperson, which is business data
    (who a quotation gets assigned to) — a User may or may not correspond
    to a Salesperson. salesperson_id is that link: for a "sales" role
    account it's what scopes which projects/customers this login can see
    (see app/routers/projects.py's _get_or_404 and
    app/routers/customers.py's _customer_visible_to). Admin accounts don't
    need it set — admins see everything regardless."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    hashed_password: Mapped[str] = mapped_column(String(255))
    # role: "admin" | "sales" — validated in the schema layer, not a DB constraint
    role: Mapped[str] = mapped_column(String(20), default="sales")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("salespeople.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
