"""Catalog: categories, products, colors, sizes, variants, images."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk


class Category(UUIDPk, Timestamps, Base):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Size(UUIDPk, Base):
    """Global size scale shared by all products (keeps filters consistent)."""

    __tablename__ = "sizes"
    __table_args__ = (UniqueConstraint("size_group", "code", name="uq_sizes_group_code"),)

    code: Mapped[str] = mapped_column(String(20))
    label_en: Mapped[str] = mapped_column(String(40))
    label_ar: Mapped[str] = mapped_column(String(40))
    # apparel | shoes | one_size | ...
    size_group: Mapped[str] = mapped_column(String(30), default="apparel")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Product(UUIDPk, Timestamps, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_piasters > 0", name="price_positive"),
        CheckConstraint(
            "compare_at_piasters IS NULL OR compare_at_piasters > price_piasters",
            name="compare_at_gt_price",
        ),
        Index("ix_products_active_sort", "is_active", "sort_order"),
    )

    slug: Mapped[str] = mapped_column(String(160), unique=True)
    name_en: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[str] = mapped_column(String(160))
    description_en: Mapped[str] = mapped_column(Text, default="", server_default="")
    description_ar: Mapped[str] = mapped_column(Text, default="", server_default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL")
    )
    price_piasters: Mapped[int] = mapped_column(Integer)
    compare_at_piasters: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    category: Mapped[Category | None] = relationship(back_populates="products")
    colors: Mapped[list[ProductColor]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductColor.sort_order"
    )
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order"
    )


class ProductColor(UUIDPk, Base):
    __tablename__ = "product_colors"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    name_en: Mapped[str] = mapped_column(String(60))
    name_ar: Mapped[str] = mapped_column(String(60))
    hex: Mapped[str] = mapped_column(String(7), default="#000000")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    product: Mapped[Product] = relationship(back_populates="colors")


class ProductVariant(UUIDPk, Timestamps, Base):
    """A sellable unit: product x color x size. Stock lives here."""

    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        CheckConstraint(
            "price_override_piasters IS NULL OR price_override_piasters > 0",
            name="override_positive",
        ),
        UniqueConstraint(
            "product_id",
            "color_id",
            "size_id",
            name="uq_variant_combo",
            postgresql_nulls_not_distinct=True,
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    color_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_colors.id", ondelete="CASCADE")
    )
    size_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sizes.id", ondelete="RESTRICT")
    )
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    price_override_piasters: Mapped[int | None] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    product: Mapped[Product] = relationship(back_populates="variants")
    color: Mapped[ProductColor | None] = relationship()
    size: Mapped[Size | None] = relationship()

    @property
    def unit_price_piasters(self) -> int:
        return self.price_override_piasters or self.product.price_piasters


class ProductImage(UUIDPk, Base):
    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    # Null = shown for every color
    color_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_colors.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text)
    alt_en: Mapped[str] = mapped_column(String(200), default="", server_default="")
    alt_ar: Mapped[str] = mapped_column(String(200), default="", server_default="")
    width: Mapped[int] = mapped_column(Integer, default=1200, server_default="1200")
    height: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    product: Mapped[Product] = relationship(back_populates="images")
