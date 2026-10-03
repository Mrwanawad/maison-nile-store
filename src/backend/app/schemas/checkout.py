"""Checkout input, shared by the HTML form and the JSON API."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import PaymentMethod
from app.utils import governorates
from app.utils.phone import normalize_eg_mobile
from app.utils.text import clean_text


class CheckoutData(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    phone: str
    email: EmailStr | None = None
    governorate: str
    address: str = Field(min_length=10, max_length=500)
    notes: str | None = Field(default=None, max_length=500)
    payment_method: PaymentMethod

    @field_validator("full_name", "address", mode="before")
    @classmethod
    def _clean(cls, v: object) -> object:
        return clean_text(v) if isinstance(v, str) else v

    @field_validator("notes", mode="before")
    @classmethod
    def _clean_notes(cls, v: object) -> object:
        if isinstance(v, str):
            return clean_text(v, 500) or None
        return v

    @field_validator("email", mode="before")
    @classmethod
    def _empty_email(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        normalized = normalize_eg_mobile(v)
        if normalized is None:
            raise ValueError("checkout.error.phone")
        return normalized

    @field_validator("governorate")
    @classmethod
    def _governorate(cls, v: str) -> str:
        if v not in governorates.BY_CODE:
            raise ValueError("checkout.error.governorate")
        return v


class OrderItemIn(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(ge=1, le=100)


# Maps pydantic field names to i18n keys for inline form errors.
FIELD_ERROR_KEYS: dict[str, str] = {
    "full_name": "checkout.error.full_name",
    "phone": "checkout.error.phone",
    "email": "checkout.error.email",
    "governorate": "checkout.error.governorate",
    "address": "checkout.error.address",
    "notes": "checkout.error.notes",
    "payment_method": "checkout.error.payment_method",
}
