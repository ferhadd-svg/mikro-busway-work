from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class UserSession(Base):
    """Server-side session. The id IS the session cookie value (a
    secrets.token_urlsafe(32) random string) — looked up against this table
    on every request, so there's nothing to forge by tampering with it."""
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
