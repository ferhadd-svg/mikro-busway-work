from pydantic import BaseModel
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
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
