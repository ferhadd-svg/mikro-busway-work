from pydantic import BaseModel, EmailStr


class SalespersonCreate(BaseModel):
    name: str
    title: str
    mobile: str
    email: str


class SalespersonUpdate(BaseModel):
    name: str | None = None
    title: str | None = None
    mobile: str | None = None
    email: str | None = None
    is_active: bool | None = None


class SalespersonOut(BaseModel):
    id: int
    name: str
    title: str
    mobile: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}
