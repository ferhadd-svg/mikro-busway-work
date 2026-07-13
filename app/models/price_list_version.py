from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class PriceListVersion(Base):
    """One row per uploaded price-list file. Exactly one row has
    is_active=True at a time — enforced in application code
    (app/routers/price_list.py), not a DB constraint."""
    __tablename__ = "price_list_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Unique on-disk name (timestamp-prefixed) — distinct from
    # original_filename so re-uploading a same-named file never overwrites
    # a previous version's bytes.
    stored_filename: Mapped[str] = mapped_column(String(300), unique=True)
    original_filename: Mapped[str] = mapped_column(String(300))

    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    # Total parsed rates (len(_al)+len(_cu)+len(_piu)+len(_bimetal)) at
    # upload time — a sanity-check number surfacing silent parse failures.
    row_count: Mapped[int] = mapped_column(Integer, default=0)
