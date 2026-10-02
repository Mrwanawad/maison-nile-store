"""JSON API response models (v1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.checkout import CheckoutData, OrderItemIn


class CategoryOut(BaseModel):
    slug: str
    name_en: str
    name_ar: str


class ColorOut(BaseModel):
    id: uuid.UUID
    name_en: str
    name_ar: str
    hex: str


class SizeOut(BaseModel):
    id: uuid.UUID
    code: str
    label_en: str
    label_ar: str


class VariantOut(BaseModel):
    id: uuid.UUID
    sku: str
    color_id: uuid.UUID | None
    size_id: uuid.UUID | None
    price_piasters: int
    in_stock: bool
    stock: int


class ImageOut(BaseModel):
    url: str
    color_id: uuid.UUID | None
    width: int
    height: int


class ProductSummaryOut(BaseModel):
    slug: str
    name_en: str
    name_ar: str
    price_piasters: int
    compare_at_piasters: int | None
    image_url: str | None
    in_stock: bool
    category: str | None


class ProductOut(ProductSummaryOut):
    description_en: str
    description_ar: str
    colors: list[ColorOut]
    sizes: list[SizeOut]
    variants: list[VariantOut]
    images: list[ImageOut]


class ProductPage(BaseModel):
    items: list[ProductSummaryOut]
    total: int
    page: int
    pages: int


class ShippingRateOut(BaseModel):
    code: str
    name_en: str
    name_ar: str
    fee_piasters: int


class OrderCreateIn(CheckoutData):
    items: list[OrderItemIn] = Field(min_length=1, max_length=30)
    locale: str = Field("en", pattern="^(en|ar)$")


class OrderItemOut(BaseModel):
    product_name_en: str
    product_name_ar: str
    variant_label_en: str
    variant_label_ar: str
    sku: str
    quantity: int
    unit_price_piasters: int


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: int
    token: str
    status: str
    payment_method: str
    payment_status: str
    subtotal_piasters: int
    shipping_piasters: int
    total_piasters: int
    created_at: datetime
    items: list[OrderItemOut]
    payment_url: str | None = None
    tracking_number: str | None = None
