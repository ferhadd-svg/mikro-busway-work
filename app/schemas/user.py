from typing import Literal
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["admin", "sales"] = "sales"


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role: Literal["admin", "sales"] | None = None
    is_active: bool | None = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8)
