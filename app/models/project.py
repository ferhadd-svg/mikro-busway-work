from sqlalchemy import String, Text, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import datetime


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    our_ref: Mapped[str] = mapped_column(String(50), unique=True)
    client_name: Mapped[str] = mapped_column(String(200))
    attn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    me_consultant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("salespeople.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)

    # Drawing
    drawing_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Status: draft | flags_pending | flags_confirmed | boq_ready | quotation_ready
    status: Mapped[str] = mapped_column(String(30), default="draft")

    # Claude's raw extraction (JSON stored as text)
    drawing_extraction_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Flags answered by user (JSON stored as text)
    flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LME values
    lme_usd_per_mt: Mapped[float | None] = mapped_column(Float, nullable=True)
    usd_to_myr: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Generated file paths
    boq_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quotation_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
