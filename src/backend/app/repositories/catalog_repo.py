"""Catalog SQL access. No business rules here."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, Product, ProductVariant, Size

SortKey = Literal["featured", "newest", "price_asc", "price_desc"]


def _product_load() -> tuple[object, ...]:
    return (
        selectinload(Product.images),
        selectinload(Product.colors),
        selectinload(Product.category),
        selectinload(Product.variants).selectinload(ProductVariant.size),
        selectinload(Product.variants).selectinload(ProductVariant.color),
    )


def _filtered(
    *,
    category_id: uuid.UUID | None,
    query: str | None,
    size_code: str | None,
    in_stock_only: bool,
    active_only: bool,
) -> Select[Product]:
    stmt = select(Product)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(
                Product.name_en.ilike(like),
                Product.name_ar.ilike(like),
                Product.description_en.ilike(like),
                Product.description_ar.ilike(like),
            )
        )
    variant_cond = [ProductVariant.product_id == Product.id, ProductVariant.is_active.is_(True)]
    if size_code:
        variant_cond.append(
            ProductVariant.size_id.in_(select(Size.id).where(Size.code == size_code))
        )
    if in_stock_only:
        variant_cond.append(ProductVariant.stock > 0)
    if size_code or in_stock_only:
        stmt = stmt.where(exists().where(*variant_cond))
    return stmt


async def list_products(
    session: AsyncSession,
    *,
    category_id: uuid.UUID | None = None,
    query: str | None = None,
    size_code: str | None = None,
    in_stock_only: bool = False,
    sort: SortKey = "featured",
    limit: int = 48,
    offset: int = 0,
    active_only: bool = True,
) -> Sequence[Product]:
    stmt = _filtered(
        category_id=category_id,
        query=query,
        size_code=size_code,
        in_stock_only=in_stock_only,
        active_only=active_only,
    )
    order = {
        "featured": (Product.is_featured.desc(), Product.sort_order, Product.created_at.desc()),
        "newest": (Product.created_at.desc(),),
        "price_asc": (Product.price_piasters, Product.created_at.desc()),
        "price_desc": (Product.price_piasters.desc(), Product.created_at.desc()),
    }[sort]
    stmt = stmt.order_by(*order).limit(limit).offset(offset).options(*_product_load())  # type: ignore[arg-type]
    return (await session.scalars(stmt)).unique().all()


async def count_products(
    session: AsyncSession,
    *,
    category_id: uuid.UUID | None = None,
    query: str | None = None,
    size_code: str | None = None,
    in_stock_only: bool = False,
    active_only: bool = True,
) -> int:
    stmt = _filtered(
        category_id=category_id,
        query=query,
        size_code=size_code,
        in_stock_only=in_stock_only,
        active_only=active_only,
    )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    return int(total or 0)


async def get_product_by_slug(
    session: AsyncSession, slug: str, *, active_only: bool = True
) -> Product | None:
    stmt = select(Product).where(Product.slug == slug).options(*_product_load())  # type: ignore[arg-type]
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    return await session.scalar(stmt)


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> Product | None:
    stmt = (
        select(Product)
        .where(Product.id == product_id)
        .options(*_product_load())  # type: ignore[arg-type]
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)


async def slug_exists(
    session: AsyncSession, slug: str, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(Product.id).where(Product.slug == slug)
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    return (await session.scalar(stmt)) is not None


async def get_variants(
    session: AsyncSession, variant_ids: Sequence[uuid.UUID]
) -> Sequence[ProductVariant]:
    if not variant_ids:
        return []
    stmt = (
        select(ProductVariant)
        .where(ProductVariant.id.in_(variant_ids))
        .options(
            selectinload(ProductVariant.product).selectinload(Product.images),
            selectinload(ProductVariant.color),
            selectinload(ProductVariant.size),
        )
    )
    return (await session.scalars(stmt)).all()


async def lock_variants(
    session: AsyncSession, variant_ids: Sequence[uuid.UUID]
) -> Sequence[ProductVariant]:
    """SELECT ... FOR UPDATE in a stable order (prevents deadlocks between orders)."""
    stmt = (
        select(ProductVariant)
        .where(ProductVariant.id.in_(sorted(variant_ids)))
        .order_by(ProductVariant.id)
        .with_for_update(of=ProductVariant)
        .execution_options(populate_existing=True)
        .options(
            selectinload(ProductVariant.product).selectinload(Product.images),
            selectinload(ProductVariant.color),
            selectinload(ProductVariant.size),
        )
    )
    return (await session.scalars(stmt)).all()


async def list_categories(session: AsyncSession, *, active_only: bool = True) -> Sequence[Category]:
    stmt = select(Category).order_by(Category.sort_order, Category.name_en)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    return (await session.scalars(stmt)).all()


async def get_category_by_slug(session: AsyncSession, slug: str) -> Category | None:
    return await session.scalar(
        select(Category).where(Category.slug == slug, Category.is_active.is_(True))
    )


async def list_sizes(session: AsyncSession) -> Sequence[Size]:
    return (await session.scalars(select(Size).order_by(Size.size_group, Size.sort_order))).all()


async def list_sizes_in_use(session: AsyncSession) -> Sequence[Size]:
    stmt = (
        select(Size)
        .where(
            exists().where(
                ProductVariant.size_id == Size.id,
                ProductVariant.is_active.is_(True),
                ProductVariant.product.has(Product.is_active.is_(True)),
            )
        )
        .order_by(Size.size_group, Size.sort_order)
    )
    return (await session.scalars(stmt)).all()


async def low_stock_variants(session: AsyncSession, threshold: int) -> Sequence[ProductVariant]:
    stmt = (
        select(ProductVariant)
        .join(Product)
        .where(
            Product.is_active.is_(True),
            ProductVariant.is_active.is_(True),
            ProductVariant.stock <= threshold,
        )
        .order_by(ProductVariant.stock, Product.name_en)
        .options(
            selectinload(ProductVariant.product),
            selectinload(ProductVariant.color),
            selectinload(ProductVariant.size),
        )
    )
    return (await session.scalars(stmt)).all()
