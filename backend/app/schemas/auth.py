"""Pydantic schemas for auth endpoints."""

import uuid

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.rm
