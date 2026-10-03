"""Session cart. The cookie only holds {variant_id: quantity}; prices always come from the DB."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, OutOfStock
from app.core.i18n import localized
from app.models import ProductVariant
from app.repositories import catalog_repo
from app.services.catalog_service import PLACEHOLDER_IMAGE, primary_image, variant_label

CART_KEY = "cart"
MAX_LINES = 30


@dataclass(slots=True)
class CartLine:
    variant: ProductVariant
    quantity: int
    max_quantity: int

    @property
    def product_name(self) -> str:
        return localized(self.variant.product, "name")

    @property
    def label(self) -> str:
        return variant_label(self.variant)

    @property
    def unit_price(self) -> int:
        return self.variant.unit_price_piasters

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity

    @property
    def image_url(self) -> str:
        image = primary_image(self.variant.product, self.variant.color_id)
        return image.url if image else PLACEHOLDER_IMAGE

    @property
    def slug(self) -> str:
        return self.variant.product.slug


@dataclass(slots=True)
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    # i18n keys describing automatic adjustments (item removed, quantity reduced)
    notices: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def subtotal(self) -> int:
        return sum(line.line_total for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines


def _raw(session_data: dict[str, Any]) -> dict[str, int]:
    raw = session_data.get(CART_KEY)
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, int] = {}
    for key, qty in raw.items():
        try:
            uuid.UUID(str(key))
        except ValueError:
            continue
        if isinstance(qty, int) and qty > 0:
            clean[str(key)] = qty
    return clean


def _save(session_data: dict[str, Any], raw: dict[str, int]) -> None:
    session_data[CART_KEY] = raw


def max_for(variant: ProductVariant) -> int:
    return max(0, min(variant.stock, get_settings().max_qty_per_line))


async def load(db: AsyncSession, session_data: dict[str, Any]) -> Cart:
    """Build the cart from the DB, fixing lines whose product vanished or ran out."""
    raw = _raw(session_data)
    cart = Cart()
    if not raw:
        return cart
    variants = {
        str(v.id): v for v in await catalog_repo.get_variants(db, [uuid.UUID(k) for k in raw])
    }
    changed = False
    for key, qty in list(raw.items()):
        variant = variants.get(key)
        if variant is None or not variant.is_active or not variant.product.is_active:
            raw.pop(key)
            cart.notices.append("cart.notice.removed")
            changed = True
            continue
        limit = max_for(variant)
        if limit == 0:
            raw.pop(key)
            cart.notices.append("cart.notice.sold_out")
            changed = True
            continue
        if qty > limit:
            qty = raw[key] = limit
            cart.notices.append("cart.notice.reduced")
            changed = True
        cart.lines.append(CartLine(variant, qty, limit))
    if changed:
        _save(session_data, raw)
    return cart


async def add(
    db: AsyncSession, session_data: dict[str, Any], variant_id: uuid.UUID, quantity: int
) -> ProductVariant:
    variants = await catalog_repo.get_variants(db, [variant_id])
    if not variants or not variants[0].is_active or not variants[0].product.is_active:
        raise AppError("cart.error.unavailable", status_code=404)
    variant = variants[0]
    raw = _raw(session_data)
    key = str(variant_id)
    if key not in raw and len(raw) >= MAX_LINES:
        raise AppError("cart.error.too_many_lines")
    limit = max_for(variant)
    if limit == 0:
        raise OutOfStock("cart.error.sold_out")
    current = raw.get(key, 0)
    if current >= limit:
        raise OutOfStock("cart.error.max_qty", max=limit)
    raw[key] = min(current + max(quantity, 1), limit)
    _save(session_data, raw)
    return variant


async def set_quantity(
    db: AsyncSession, session_data: dict[str, Any], variant_id: uuid.UUID, quantity: int
) -> None:
    raw = _raw(session_data)
    key = str(variant_id)
    if key not in raw:
        return
    if quantity <= 0:
        raw.pop(key)
    else:
        variants = await catalog_repo.get_variants(db, [variant_id])
        limit = max_for(variants[0]) if variants else 0
        if limit == 0:
            raw.pop(key)
        else:
            raw[key] = min(quantity, limit)
    _save(session_data, raw)


def remove(session_data: dict[str, Any], variant_id: uuid.UUID) -> None:
    raw = _raw(session_data)
    raw.pop(str(variant_id), None)
    _save(session_data, raw)


def clear(session_data: dict[str, Any]) -> None:
    session_data.pop(CART_KEY, None)


def items_for_order(cart: Cart) -> list[tuple[uuid.UUID, int]]:
    return [(line.variant.id, line.quantity) for line in cart.lines]
