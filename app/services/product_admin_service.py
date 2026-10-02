"""Admin catalog management: products, colors, sizes -> variants, images, categories."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, IntegrationError, NotFound
from app.integrations.storage import get_storage
from app.models import (
    Category,
    PhoneBlock,
    Product,
    ProductColor,
    ProductImage,
    ProductVariant,
    Size,
)
from app.repositories import catalog_repo
from app.utils.images import InvalidImage, to_webp
from app.utils.money import egp_to_piasters
from app.utils.phone import normalize_eg_mobile
from app.utils.text import clean_text, slugify

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(slots=True)
class ProductInput:
    name_en: str
    name_ar: str
    slug: str
    description_en: str
    description_ar: str
    category_id: uuid.UUID | None
    price_egp: str
    compare_at_egp: str
    is_active: bool
    is_featured: bool
    sort_order: int


def _money(value: str, *, required: bool) -> int | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        if required:
            raise AppError("admin.error.price")
        return None
    try:
        piasters = egp_to_piasters(value)
    except Exception:
        raise AppError("admin.error.price") from None
    if piasters <= 0:
        raise AppError("admin.error.price")
    return piasters


async def _unique_slug(db: AsyncSession, base: str, exclude: uuid.UUID | None) -> str:
    base = base or f"product-{secrets.token_hex(3)}"
    slug, n = base, 2
    while await catalog_repo.slug_exists(db, slug, exclude):
        slug, n = f"{base}-{n}", n + 1
    return slug


async def save_product(
    db: AsyncSession, data: ProductInput, product_id: uuid.UUID | None = None
) -> Product:
    name_en = clean_text(data.name_en, 160)
    name_ar = clean_text(data.name_ar, 160) or name_en
    if len(name_en) < 2:
        raise AppError("admin.error.name")
    price = _money(data.price_egp, required=True)
    compare_at = _money(data.compare_at_egp, required=False)
    assert price is not None
    if compare_at is not None and compare_at <= price:
        raise AppError("admin.error.compare_at")

    if product_id:
        product = await db.get(Product, product_id)
        if product is None:
            raise NotFound()
    else:
        product = Product()
        db.add(product)
    product.name_en = name_en
    product.name_ar = name_ar
    product.slug = await _unique_slug(db, slugify(data.slug or name_en), product_id)
    product.description_en = (data.description_en or "").strip()[:5000]
    product.description_ar = (data.description_ar or "").strip()[:5000]
    product.category_id = data.category_id
    product.price_piasters = price
    product.compare_at_piasters = compare_at
    product.is_active = data.is_active
    product.is_featured = data.is_featured
    product.sort_order = data.sort_order
    await db.flush()
    if not product_id:
        # Every product starts with one default (no color/size) variant.
        db.add(ProductVariant(product_id=product.id, sku=_sku(product.slug, None, None), stock=0))
    await db.commit()
    return product


async def delete_product(db: AsyncSession, product_id: uuid.UUID) -> None:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    urls = [i.url for i in product.images]
    await db.delete(product)
    await db.commit()
    for url in urls:
        await _delete_image_files(url)


# --- Colors ------------------------------------------------------------------


async def add_color(
    db: AsyncSession, product_id: uuid.UUID, name_en: str, name_ar: str, hex_value: str
) -> None:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    name_en = clean_text(name_en, 60)
    if not name_en:
        raise AppError("admin.error.color_name")
    if not HEX.match(hex_value or ""):
        raise AppError("admin.error.color_hex")
    color = ProductColor(
        product_id=product_id,
        name_en=name_en,
        name_ar=clean_text(name_ar, 60) or name_en,
        hex=hex_value.upper(),
        sort_order=len(product.colors),
    )
    db.add(color)
    await db.commit()
    await rebuild_variants(db, product_id)


async def delete_color(db: AsyncSession, product_id: uuid.UUID, color_id: uuid.UUID) -> None:
    color = await db.get(ProductColor, color_id)
    if color is None or color.product_id != product_id:
        raise NotFound()
    await db.delete(color)  # variants of this color cascade; order history keeps copies
    await db.commit()
    await rebuild_variants(db, product_id)


# --- Variants ----------------------------------------------------------------


def _sku(slug: str, color: ProductColor | None, size: Size | None) -> str:
    parts = [slug[:24].upper()]
    if color:
        parts.append(slugify(color.name_en)[:10].upper() or "C")
    if size:
        parts.append(size.code.upper())
    return "-".join(parts) + "-" + secrets.token_hex(2).upper()


async def rebuild_variants(
    db: AsyncSession, product_id: uuid.UUID, size_ids: list[uuid.UUID] | None = None
) -> None:
    """Ensure one variant exists per color x size; deactivate combinations no longer offered.

    `size_ids=None` keeps the sizes currently in use.
    """
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    if size_ids is None:
        size_ids = list({v.size_id for v in product.variants if v.size_id and v.is_active})
    sizes = (await db.scalars(select(Size).where(Size.id.in_(size_ids)))).all() if size_ids else []
    colors: list[ProductColor | None] = list(product.colors) or [None]
    size_opts: list[Size | None] = list(sizes) or [None]
    wanted = {(c.id if c else None, s.id if s else None): (c, s) for c in colors for s in size_opts}
    existing = {(v.color_id, v.size_id): v for v in product.variants}

    for key, (color, size) in wanted.items():
        variant = existing.get(key)
        if variant is None:
            db.add(
                ProductVariant(
                    product_id=product.id,
                    color_id=key[0],
                    size_id=key[1],
                    sku=_sku(product.slug, color, size),
                    stock=0,
                )
            )
        elif not variant.is_active:
            variant.is_active = True
    for key, variant in existing.items():
        if key in wanted:
            continue
        if variant.stock == 0:
            # Past orders keep their own copy of the item, so this is safe.
            await db.delete(variant)
        else:
            variant.is_active = False  # keep the stock count in case it comes back
    await db.commit()


@dataclass(slots=True)
class VariantUpdate:
    id: uuid.UUID
    stock: int
    price_override_egp: str
    is_active: bool
    sku: str


async def update_variants(
    db: AsyncSession, product_id: uuid.UUID, rows: list[VariantUpdate]
) -> None:
    for row in rows:
        variant = await db.get(ProductVariant, row.id)
        if variant is None or variant.product_id != product_id:
            continue
        if row.stock < 0:
            raise AppError("admin.error.stock")
        variant.stock = row.stock
        variant.price_override_piasters = _money(row.price_override_egp, required=False)
        variant.is_active = row.is_active
        sku = clean_text(row.sku, 64).upper()
        if sku:
            variant.sku = sku
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("admin.error.sku_taken") from None


# --- Images ------------------------------------------------------------------


async def upload_images(
    db: AsyncSession,
    product_id: uuid.UUID,
    files: list[tuple[bytes, str]],
    color_id: uuid.UUID | None,
) -> int:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    s = get_settings()
    storage = get_storage()
    position = len(product.images)
    added = 0
    for data, _filename in files:
        if not data:
            continue
        try:
            webp, width, height = to_webp(data, s.image_max_size_px, s.image_quality)
        except InvalidImage:
            raise AppError("admin.error.image_invalid") from None
        small, _, _ = to_webp(data, 480, s.image_quality)
        name = uuid.uuid4().hex[:12]
        key = f"products/{product.slug}/{name}.webp"
        try:
            await storage.put(f"products/{product.slug}/{name}-480.webp", small, "image/webp")
            url = await storage.put(key, webp, "image/webp")
        except IntegrationError:
            raise AppError("admin.error.image_upload", status_code=502) from None
        db.add(
            ProductImage(
                product_id=product_id,
                color_id=color_id,
                url=url,
                alt_en=product.name_en,
                alt_ar=product.name_ar,
                width=width,
                height=height,
                sort_order=position,
            )
        )
        position += 1
        added += 1
    await db.commit()
    return added


async def add_image_url(
    db: AsyncSession, product_id: uuid.UUID, url: str, color_id: uuid.UUID | None
) -> None:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    if not url.startswith("https://"):
        raise AppError("admin.error.image_url")
    db.add(
        ProductImage(
            product_id=product_id,
            color_id=color_id,
            url=url.strip(),
            alt_en=product.name_en,
            alt_ar=product.name_ar,
            sort_order=len(product.images),
        )
    )
    await db.commit()


async def update_image(
    db: AsyncSession, product_id: uuid.UUID, image_id: uuid.UUID, color_id: uuid.UUID | None
) -> None:
    image = await db.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        raise NotFound()
    image.color_id = color_id
    await db.commit()


async def move_image(
    db: AsyncSession, product_id: uuid.UUID, image_id: uuid.UUID, direction: int
) -> None:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    images = list(product.images)
    index = next((i for i, img in enumerate(images) if img.id == image_id), None)
    if index is None:
        raise NotFound()
    target = index + direction
    if 0 <= target < len(images):
        images[index], images[target] = images[target], images[index]
        for position, img in enumerate(images):
            img.sort_order = position
        await db.commit()


async def delete_image(db: AsyncSession, product_id: uuid.UUID, image_id: uuid.UUID) -> None:
    image = await db.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        raise NotFound()
    url = image.url
    await db.delete(image)
    await db.commit()
    await _delete_image_files(url)


async def _delete_image_files(url: str) -> None:
    """Remove an uploaded photo and its small variant. External links are ignored."""
    storage = get_storage()
    await storage.delete(url)
    if url.endswith(".webp"):
        await storage.delete(url.removesuffix(".webp") + "-480.webp")


# --- Categories ----------------------------------------------------------------


async def save_category(
    db: AsyncSession,
    *,
    category_id: uuid.UUID | None,
    name_en: str,
    name_ar: str,
    sort_order: int,
    is_active: bool,
) -> None:
    name_en = clean_text(name_en, 120)
    if len(name_en) < 2:
        raise AppError("admin.error.name")
    if category_id:
        category = await db.get(Category, category_id)
        if category is None:
            raise NotFound()
    else:
        category = Category(slug="")
        db.add(category)
    if not category.slug:
        base = slugify(name_en) or f"category-{secrets.token_hex(2)}"
        slug, n = base, 2
        while await db.scalar(select(Category.id).where(Category.slug == slug)):
            slug, n = f"{base}-{n}", n + 1
        category.slug = slug
    category.name_en = name_en
    category.name_ar = clean_text(name_ar, 120) or name_en
    category.sort_order = sort_order
    category.is_active = is_active
    await db.commit()


async def delete_category(db: AsyncSession, category_id: uuid.UUID) -> None:
    await db.execute(delete(Category).where(Category.id == category_id))
    await db.commit()


# --- Sizes ---------------------------------------------------------------------


async def add_size(
    db: AsyncSession, *, code: str, label_en: str, label_ar: str, size_group: str, sort_order: int
) -> None:
    code = clean_text(code, 20).upper()
    if not code:
        raise AppError("admin.error.size_code")
    db.add(
        Size(
            code=code,
            label_en=clean_text(label_en, 40) or code,
            label_ar=clean_text(label_ar, 40) or code,
            size_group=slugify(size_group or "apparel") or "apparel",
            sort_order=sort_order,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("admin.error.size_exists") from None


async def delete_size(db: AsyncSession, size_id: uuid.UUID) -> None:
    try:
        await db.execute(delete(Size).where(Size.id == size_id))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("admin.error.size_in_use") from None


# --- Phone blocklist -------------------------------------------------------------


async def block_phone(db: AsyncSession, raw_phone: str, reason: str, *, actor: str) -> None:
    phone = normalize_eg_mobile(raw_phone)
    if phone is None:
        raise AppError("checkout.error.phone")
    if await db.get(PhoneBlock, phone) is None:
        db.add(PhoneBlock(phone=phone, reason=clean_text(reason, 300) or None, created_by=actor))
        await db.commit()


async def unblock_phone(db: AsyncSession, phone: str) -> None:
    await db.execute(delete(PhoneBlock).where(PhoneBlock.phone == phone))
    await db.commit()
