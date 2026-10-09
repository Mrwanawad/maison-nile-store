"""Cart behaviour, language switching, security headers and rate limits."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.rate_limit import limiter
from app.models import Product, ProductVariant
from tests.conftest import Catalog, csrf


async def _add(client, token: str, variant: ProductVariant, qty: int = 1):  # type: ignore[no-untyped-def]
    return await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(variant.product_id),
            "variant_id": str(variant.id),
            "quantity": str(qty),
        },
        headers={"HX-Request": "true"},
    )


def _badge(html: str) -> int:
    match = re.search(r'id="cart-badge".*?</span>\s*(\d+)', html, re.S)
    return int(match.group(1)) if match else 0


async def test_cart_quantity_is_capped_by_stock(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    token = await csrf(client, "/p/tee")
    r = await _add(client, token, catalog.tee_black_m, qty=9)  # stock 5
    assert _badge(r.text) == 5
    r = await _add(client, token, catalog.tee_black_m)
    assert r.status_code == 409 and "up to 5" in r.headers["HX-Trigger"]


async def test_cart_update_and_remove(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    token = await csrf(client, "/p/bag")
    await _add(client, token, catalog.single, 2)
    r = await client.post(
        f"/cart/items/{catalog.single.id}/update",
        data={"csrf_token": token, "quantity": "1"},
        headers={"HX-Request": "true", "HX-Target": "cart-page"},
    )
    assert r.status_code == 200 and 'hx-swap-oob="true"' in r.text and _badge(r.text) == 1
    r = await client.post(f"/cart/items/{catalog.single.id}/remove", data={"csrf_token": token})
    assert r.status_code == 303  # no-JS fallback
    assert "Your bag is empty" in (await client.get("/cart")).text


async def test_cart_heals_when_stock_drops_or_product_is_hidden(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    token = await csrf(client, "/p/tee")
    await _add(client, token, catalog.tee_black_m, 4)
    await _add(client, token, catalog.single, 1)
    async with SessionLocal() as s:
        await s.execute(
            update(ProductVariant)
            .where(ProductVariant.id == catalog.tee_black_m.id)
            .values(stock=2)
        )
        await s.execute(
            update(Product).where(Product.id == catalog.single.product_id).values(is_active=False)
        )
        await s.commit()
    page = (await client.get("/cart")).text
    assert "quantity was lowered" in page and "no longer available" in page
    assert _badge((await client.get("/cart/drawer", headers={"HX-Request": "true"})).text) == 2


async def test_sold_out_variant_cannot_be_added(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    async with SessionLocal() as s:
        await s.execute(
            update(ProductVariant)
            .where(ProductVariant.id == catalog.tee_black_l.id)
            .values(stock=0)
        )
        await s.commit()
    token = await csrf(client, "/p/tee")
    r = await _add(client, token, catalog.tee_black_l)
    assert r.status_code == 409
    page = (await client.get("/p/tee")).text
    assert "data-soldout" in page


async def test_language_switch_keeps_page_and_query(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    html = (await client.get("/shop?size=M")).text
    assert 'href="/ar/shop?size=M"' in html
    html_ar = (await client.get("/ar/shop?size=M")).text
    assert 'href="/shop?size=M"' in html_ar and 'lang="ar"' in html_ar
    # Localized redirects stay in Arabic
    token = await csrf(client, "/ar/p/bag")
    r = await client.post(
        "/ar/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.single.product_id),
            "variant_id": str(catalog.single.id),
        },
    )
    assert r.headers["location"] == "/ar/cart"


async def test_security_headers_and_cookie(client, catalog: Catalog) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/")
    csp = r.headers["content-security-policy"]
    assert (
        "script-src 'self'" in csp
        and "frame-ancestors 'none'" in csp
        and "accept.paymob.com" in csp
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-request-id"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    static = await client.get("/static/js/app.js?v=1")
    assert "immutable" in static.headers["cache-control"]


async def test_errors_are_json_for_the_api(client) -> None:  # type: ignore[no-untyped-def]
    r = await client.get("/api/v1/products/missing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await client.get("/ar/p/missing")
    assert r.status_code == 404 and 'dir="rtl"' in r.text


async def test_rate_limit_on_checkout_and_login(
    client, catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    token = await csrf(client, "/admin/login")
    statuses = [
        (
            await client.post(
                "/admin/login", data={"csrf_token": token, "username": "x", "password": "y"}
            )
        ).status_code
        for _ in range(6)
    ]
    # Admin forms show errors on the page they came from.
    login_page = (await client.get("/admin/login")).text
    limiter.reset()
    assert statuses[:5] == [401] * 5 and statuses[5] == 303
    assert "Too many attempts" in login_page

    limiter.reset()
    codes = [(await client.get("/api/v1/products")).status_code for _ in range(3)]
    assert codes == [200, 200, 200]


async def test_unexpected_errors_render_friendly_500(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from app.main import app
    from app.services import catalog_service

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(catalog_service, "featured_cards", boom)
    monkeypatch.setattr(catalog_service, "get_product_or_404", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        page = await c.get("/ar")
        assert page.status_code == 500 and "حدث خطأ" in page.text and "exploded" not in page.text
        assert page.headers["x-request-id"] in page.text
        api = await c.get("/api/v1/products/tee")
        assert api.status_code == 500 and api.json()["error"]["code"] == "server_error"
        hx = await c.get("/", headers={"HX-Request": "true"})
        assert hx.status_code == 500 and "toast" in hx.headers["HX-Trigger"]
