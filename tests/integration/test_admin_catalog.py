"""Admin catalog management through the real HTTP routes."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Category, PhoneBlock, Product, ProductImage, ProductVariant, Size
from app.services import nav_cache
from tests.conftest import Catalog, flash


async def _variants(product_id) -> list[ProductVariant]:  # type: ignore[no-untyped-def]
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(ProductVariant).where(ProductVariant.product_id == product_id)
        )
        return list(rows)


def _jpeg(width: int = 2000, height: int = 2500) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (180, 150, 120)).save(buf, "JPEG")
    return buf.getvalue()


async def test_admin_pages_require_login(client) -> None:  # type: ignore[no-untyped-def]
    for path in [
        "/admin",
        "/admin/orders",
        "/admin/products",
        "/admin/categories",
        "/admin/blocklist",
    ]:
        r = await client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/admin/login", path


async def test_product_lifecycle(admin_client, catalog: Catalog, media_tmp) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    async with SessionLocal() as s:
        sizes = {sz.code: sz.id for sz in await s.scalars(select(Size))}

    # Create
    r = await client.post(
        "/admin/products",
        data={
            "csrf_token": token,
            "name_en": "Linen Shirt",
            "name_ar": "قميص كتان",
            "price_egp": "799.50",
            "compare_at_egp": "999",
            "slug": "",
            "sort_order": "0",
            "is_active": "on",
        },
    )
    assert r.status_code == 303
    product_id = r.headers["location"].rsplit("/", 1)[1]
    async with SessionLocal() as s:
        product = await s.get(Product, product_id)
        assert product and product.slug == "linen-shirt" and product.price_piasters == 79950
        assert product.compare_at_piasters == 99900
    assert len(await _variants(product_id)) == 1  # default variant

    # Invalid price is rejected with a message, nothing saved
    await client.post(
        f"/admin/products/{product_id}",
        data={"csrf_token": token, "name_en": "Linen Shirt", "price_egp": "abc"},
        headers={"Referer": "http://test/admin/products"},
    )
    assert "valid price" in await flash(client)

    # Two colors x two sizes = 4 active variants; the default one is retired
    for name, hex_ in [("Sand", "#D8C8A8"), ("Olive", "#4A5A3F")]:
        await client.post(
            f"/admin/products/{product_id}/colors",
            data={"csrf_token": token, "name_en": name, "name_ar": "", "hex": hex_},
        )
    await client.post(
        f"/admin/products/{product_id}/sizes",
        data={"csrf_token": token, "size_ids": [str(sizes["M"]), str(sizes["L"])]},
    )
    variants = await _variants(product_id)
    active = [v for v in variants if v.is_active]
    assert len(active) == 4 and len(variants) == 4  # retired empty combos are removed

    # Stock grid: set stock, price override, SKU
    first, second = active[0], active[1]
    data = {"csrf_token": token, "variant_id": [str(v.id) for v in active]}
    for v in active:
        data[f"stock_{v.id}"] = "7"
        data[f"active_{v.id}"] = "on"
        data[f"sku_{v.id}"] = v.sku
        data[f"price_{v.id}"] = ""
    data[f"price_{first.id}"] = "850"
    await client.post(f"/admin/products/{product_id}/variants", data=data)
    refreshed = {v.id: v for v in await _variants(product_id)}
    assert refreshed[first.id].stock == 7 and refreshed[first.id].price_override_piasters == 85000

    # Duplicate SKU is rejected and nothing changes
    data[f"sku_{second.id}"] = refreshed[first.id].sku
    data[f"stock_{first.id}"] = "1"
    await client.post(
        f"/admin/products/{product_id}/variants",
        data=data,
        headers={"Referer": f"http://test/admin/products/{product_id}"},
    )
    assert "SKU is already used" in await flash(client)
    assert {v.id: v for v in await _variants(product_id)}[first.id].stock == 7

    # Removing a size deactivates its combinations
    await client.post(
        f"/admin/products/{product_id}/sizes",
        data={"csrf_token": token, "size_ids": [str(sizes["M"])]},
    )
    assert len([v for v in await _variants(product_id) if v.is_active]) == 2

    # Photos: upload (WebP + 480px variant), reorder, link to color, delete
    r = await client.post(
        f"/admin/products/{product_id}/images",
        data={"csrf_token": token, "color_id": "", "image_url": ""},
        files=[
            ("files", ("a.jpg", _jpeg(), "image/jpeg")),
            ("files", ("b.jpg", _jpeg(800, 1000), "image/jpeg")),
        ],
    )
    assert r.status_code == 303
    async with SessionLocal() as s:
        images = list(
            await s.scalars(
                select(ProductImage)
                .where(ProductImage.product_id == product_id)
                .order_by(ProductImage.sort_order)
            )
        )
    assert len(images) == 2 and images[0].width == 1280 and images[0].url.endswith(".webp")
    files = sorted(p.name for p in media_tmp.rglob("*.webp"))
    assert len(files) == 4 and sum(name.endswith("-480.webp") for name in files) == 2

    bad = await client.post(
        f"/admin/products/{product_id}/images",
        data={"csrf_token": token},
        files=[("files", ("x.jpg", b"not an image", "image/jpeg"))],
        headers={"Referer": f"http://test/admin/products/{product_id}"},
    )
    assert bad.status_code == 303 and "readable image" in await flash(client)

    await client.post(
        f"/admin/products/{product_id}/images/{images[1].id}",
        data={"csrf_token": token, "action": "up"},
    )
    async with SessionLocal() as s:
        moved = await s.get(ProductImage, images[1].id)
        assert moved and moved.sort_order == 0
    await client.post(
        f"/admin/products/{product_id}/images/{images[0].id}",
        data={"csrf_token": token, "action": "delete"},
    )
    assert len(list(media_tmp.rglob("*.webp"))) == 2

    # Delete product
    await client.post(f"/admin/products/{product_id}/delete", data={"csrf_token": token})
    async with SessionLocal() as s:
        assert await s.get(Product, product_id) is None
    assert list(media_tmp.rglob("*.webp")) == []


async def test_storefront_hides_inactive_products(admin_client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    await client.post(
        f"/admin/products/{catalog.product.id}",
        data={
            "csrf_token": token,
            "name_en": "Tee",
            "name_ar": "تيشيرت",
            "price_egp": "450",
            "sort_order": "0",
        },
    )
    assert (await client.get("/p/tee")).status_code == 404
    assert "Tee" not in (await client.get("/shop")).text.split("products</p>")[1]


async def test_categories_sizes_and_blocklist(admin_client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    await client.post(
        "/admin/categories",
        data={
            "csrf_token": token,
            "name_en": "Dresses",
            "name_ar": "فساتين",
            "sort_order": "5",
            "is_active": "on",
        },
    )
    assert any(c.slug == "dresses" for c in nav_cache.nav_categories())
    assert (await client.get("/c/dresses")).status_code == 200
    async with SessionLocal() as s:
        dresses = await s.scalar(select(Category).where(Category.slug == "dresses"))
    assert dresses
    await client.post(f"/admin/categories/{dresses.id}/delete", data={"csrf_token": token})
    assert not any(c.slug == "dresses" for c in nav_cache.nav_categories())

    await client.post(
        "/admin/sizes",
        data={"csrf_token": token, "code": "xxl", "size_group": "apparel", "sort_order": "9"},
    )
    await client.post(
        "/admin/sizes",
        data={"csrf_token": token, "code": "XXL", "size_group": "apparel"},
        headers={"Referer": "http://test/admin/categories"},
    )
    assert "already exists" in await flash(client)
    async with SessionLocal() as s:
        m = await s.scalar(select(Size).where(Size.code == "M"))
    assert m
    await client.post(
        f"/admin/sizes/{m.id}/delete",
        data={"csrf_token": token},
        headers={"Referer": "http://test/admin/categories"},
    )
    assert "used by products" in await flash(client)

    await client.post(
        "/admin/blocklist",
        data={"csrf_token": token, "phone": "+20 100 000 0001", "reason": "refused"},
    )
    async with SessionLocal() as s:
        assert await s.get(PhoneBlock, "01000000001")
    await client.post("/admin/blocklist/01000000001/delete", data={"csrf_token": token})
    async with SessionLocal() as s:
        assert await s.get(PhoneBlock, "01000000001") is None


async def test_admin_logout(admin_client) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    await client.post("/admin/logout", data={"csrf_token": token})
    assert (await client.get("/admin")).status_code == 303
