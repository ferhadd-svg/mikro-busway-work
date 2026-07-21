from pydantic import BaseModel, EmailStr
from typing import Literal
import datetime


class ProjectCreate(BaseModel):
    our_ref: str
    client_name: str
    attn: str | None = None
    me_consultant: str | None = None
    salesperson_id: int | None = None


class ProjectOut(BaseModel):
    id: int
    our_ref: str
    client_name: str
    attn: str | None
    me_consultant: str | None
    salesperson_id: int | None
    salesperson_name: str | None = None
    customer_id: int | None = None
    status: str
    drawing_filename: str | None
    boq_filename: str | None
    quotation_filename: str | None
    quoted_value_myr: float | None = None
    outcome: str | None = None
    outcome_value_myr: float | None = None
    outcome_notes: str | None = None
    outcome_recorded_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class ProjectOutcomeUpdate(BaseModel):
    outcome: Literal["won", "lost"] | None
    outcome_value_myr: float | None = None
    outcome_notes: str | None = None


class EmailQuotationRequest(BaseModel):
    to: list[EmailStr]              # at least one required (enforced in router)
    cc: list[EmailStr] = []
    subject: str | None = None      # server builds a default from our_ref
    message: str | None = None      # server builds a default body
