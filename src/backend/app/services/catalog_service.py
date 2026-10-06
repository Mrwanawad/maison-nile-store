"""Read-side catalog logic: listing, product detail view models, variant resolution."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.i18n import get_locale, localized
from app.models import Category, Product, ProductImage, ProductVariant, Size
from app.repositories import catalog_repo
from app.repositories.catalog_repo import SortKey
from app.utils.money import percent_off

PLACEHOLDER_IMAGE = "/static/img/placeholder.svg"
PAGE_SIZE = 24


@dataclass(slots=True)
class ColorSwatch:
    id: str
    name: str
    hex: str


@dataclass(slots=True)
class ProductCard:
    slug: str
    name: str
    price_piasters: int
    compare_at_piasters: int | None
    percent_off: int
    image_url: str
    image_alt: str
    hover_image_url: str | None
    in_stock: bool
    low_stock: bool
    is_new: bool
    colors: list[ColorSwatch] = field(default_factory=list)
    category_name: str | None = None


@dataclass(slots=True)
class CategoryTile:
    slug: str
    name: str
    image_url: str
    count: int


@dataclass(slots=True)
class Listing:
    cards: list[ProductCard]
    total: int
    page: int
    pages: int


def variant_label(variant: ProductVariant, locale: str | None = None) -> str:
    """Human label such as 'Olive / M'. Empty for a default (no color/size) variant."""
    locale = locale or get_locale()
    parts: list[str] = []
    if variant.color:
        parts.append(variant.color.name_ar if locale == "ar" else variant.color.name_en)
    if variant.size:
        parts.append(variant.size.label_ar if locale == "ar" else variant.size.label_en)
    return " / ".join(parts)


def _images_for_color(product: Product, color_id: uuid.UUID | None) -> list[ProductImage]:
    if color_id is None:
        return list(product.images)
    matching = [i for i in product.images if i.color_id in (color_id, None)]
    return matching or list(product.images)


def primary_image(product: Product, color_id: uuid.UUID | None = None) -> ProductImage | None:
    images = _images_for_color(product, color_id)
    return images[0] if images else None


def to_card(product: Product, *, new_ids: set[uuid.UUID] | None = None) -> ProductCard:
    threshold = get_settings().low_stock_threshold
    active = [v for v in product.variants if v.is_active]
    total_stock = sum(v.stock for v in active)
    images = list(product.images)
    first = images[0] if images else None
    hover = images[1].url if len(images) > 1 else None
    return ProductCard(
        slug=product.slug,
        name=localized(product, "name"),
        price_piasters=product.price_piasters,
        compare_at_piasters=product.compare_at_piasters,
        percent_off=percent_off(product.price_piasters, product.compare_at_piasters),
        image_url=first.url if first else PLACEHOLDER_IMAGE,
        image_alt=(localized(first, "alt") if first else "") or localized(product, "name"),
        hover_image_url=hover,
        in_stock=total_stock > 0,
        low_stock=0 < total_stock <= threshold,
        is_new=bool(new_ids and product.id in new_ids),
        colors=[ColorSwatch(str(c.id), localized(c, "name"), c.hex) for c in product.colors],
        category_name=localized(product.category, "name") if product.category else None,
    )


async def listing(
    session: AsyncSession,
    *,
    category: Category | None = None,
    query: str | None = None,
    size_code: str | None = None,
    in_stock_only: bool = False,
    sort: SortKey = "featured",
    page: int = 1,
) -> Listing:
    page = max(page, 1)
    filters: dict[str, Any] = {
        "category_id": category.id if category else None,
        "query": (query or "").strip()[:80] or None,
        "size_code": size_code or None,
        "in_stock_only": in_stock_only,
    }
    total = await catalog_repo.count_products(session, **filters)
    products = await catalog_repo.list_products(
        session, **filters, sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )
    newest = await catalog_repo.list_products(session, sort="newest", limit=4)
    new_ids = {p.id for p in newest}
    return Listing(
        cards=[to_card(p, new_ids=new_ids) for p in products],
        total=total,
        page=page,
        pages=max(1, -(-total // PAGE_SIZE)),
    )


async def featured_cards(session: AsyncSession, limit: int = 8) -> list[ProductCard]:
    products = await catalog_repo.list_products(session, sort="featured", limit=limit)
    newest = await catalog_repo.list_products(session, sort="newest", limit=4)
    new_ids = {p.id for p in newest}
    return [to_card(p, new_ids=new_ids) for p in products]


async def category_tiles(session: AsyncSession) -> list[CategoryTile]:
    """One tile per category that has products: cover = its first featured product photo."""
    tiles = []
    for category in await catalog_repo.list_categories(session):
        products = await catalog_repo.list_products(session, category_id=category.id, limit=1)
        if not products:
            continue
        card = to_card(products[0])
        count = await catalog_repo.count_products(session, category_id=category.id)
        name = localized(category, "name")
        tiles.append(CategoryTile(category.slug, name, card.image_url, count))
    return tiles


async def get_product_or_404(session: AsyncSession, slug: str) -> Product:
    product = await catalog_repo.get_product_by_slug(session, slug)
    if product is None:
        raise NotFound()
    return product


def picker_data(product: Product) -> dict[str, Any]:
    """JSON consumed by the product page script (variant picker + gallery)."""
    threshold = get_settings().low_stock_threshold
    return {
        "variants": [
            {
                "id": str(v.id),
                "color": str(v.color_id) if v.color_id else None,
                "size": str(v.size_id) if v.size_id else None,
                "stock": v.stock if v.is_active else 0,
                "price": v.price_override_piasters or product.price_piasters,
            }
            for v in product.variants
        ],
        "images": [
            {"url": i.url, "color": str(i.color_id) if i.color_id else None} for i in product.images
        ],
        "lowStock": threshold,
    }


def sizes_for(product: Product) -> list[Size]:
    seen: dict[uuid.UUID, Size] = {}
    for v in product.variants:
        if v.size and v.is_active:
            seen.setdefault(v.size.id, v.size)
    return sorted(seen.values(), key=lambda s: s.sort_order)


def size_available(product: Product, size_id: uuid.UUID) -> bool:
    return any(v.size_id == size_id and v.is_active and v.stock > 0 for v in product.variants)


def color_available(product: Product, color_id: uuid.UUID) -> bool:
    return any(v.color_id == color_id and v.is_active and v.stock > 0 for v in product.variants)


def default_variant(product: Product) -> ProductVariant | None:
    """Single-variant products need no picker."""
    active = [v for v in product.variants if v.is_active]
    return active[0] if len(active) == 1 else None


def resolve_variant(
    product: Product, color_id: uuid.UUID | None, size_id: uuid.UUID | None
) -> ProductVariant | None:
    for v in product.variants:
        if v.color_id == color_id and v.size_id == size_id and v.is_active:
            return v
    return None


async def related_cards(
    session: AsyncSession, product: Product, limit: int = 4
) -> Sequence[ProductCard]:
    products = await catalog_repo.list_products(
        session, category_id=product.category_id, limit=limit + 1
    )
    return [to_card(p) for p in products if p.id != product.id][:limit]
