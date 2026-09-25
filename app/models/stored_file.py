from sqlalchemy import String, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class StoredFile(Base):
    """Database copy of a file the app writes to disk (generated BOQs and
    quotations, uploaded price lists and templates). Render's free plan has
    no persistent disk, so the data/ folder is wiped on every deploy; with a
    hosted database these rows survive and the file is written back to disk
    the next time it's needed (see app/services/file_store.py)."""
    __tablename__ = "stored_files"
    __table_args__ = (UniqueConstraint("kind", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # "projects" | "price_list" | "templates" — which settings.*_dir it lives in
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
