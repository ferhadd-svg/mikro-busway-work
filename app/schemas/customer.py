from pydantic import BaseModel
import datetime

from app.schemas.project import ProjectOut


class CustomerContactCreate(BaseModel):
    name: str
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False


class CustomerContactUpdate(BaseModel):
    name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool | None = None


class CustomerContactOut(BaseModel):
    id: int
    customer_id: int
    name: str
    title: str | None
    email: str | None
    phone: str | None
    is_primary: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class CustomerNoteCreate(BaseModel):
    body: str


class CustomerNoteOut(BaseModel):
    id: int
    customer_id: int
    author_id: int | None
    author_name: str | None = None
    body: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class CustomerCreate(BaseModel):
    company_name: str
    address: str | None = None


class CustomerUpdate(BaseModel):
    company_name: str | None = None
    address: str | None = None
    is_active: bool | None = None


class CustomerOut(BaseModel):
    id: int
    company_name: str
    address: str | None
    is_active: bool
    created_at: datetime.datetime
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    project_count: int = 0

    model_config = {"from_attributes": True}


class CustomerDetailOut(CustomerOut):
    contacts: list[CustomerContactOut] = []
    notes: list[CustomerNoteOut] = []
    projects: list[ProjectOut] = []
