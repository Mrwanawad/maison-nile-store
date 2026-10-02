"""End-to-end HTTP flows through the real app: cart, checkout, webhook, admin, API."""

from __future__ import annotations

import httpx

from app.core.security import hash_password, order_token
from app.integrations import paymob
from app.models import AdminUser, Order, OrderStatus, PaymentStatus
from app.services import order_service
from tests.conftest import Catalog, csrf


async def test_pages_render(client: httpx.AsyncClient, catalog: Catalog) -> None:
    for path in [
        "/",
        "/ar",
        "/shop",
        "/shop?size=M&in_stock=true&sort=price_asc",
        "/c/tops",
        "/p/tee",
        "/ar/p/tee",
        "/cart",
        "/track",
        "/pages/faq",
        "/ar/pages/about",
        "/health",
    ]:
        response = await client.get(path)
        assert response.status_code == 200, path
    assert (await client.get("/p/nope")).status_code == 404
    ar = await client.get("/ar/p/tee")
    assert 'dir="rtl"' in ar.text and "تيشيرت" in ar.text
    assert "Content-Security-Policy" in ar.headers


async def test_cart_checkout_cod_flow(client: httpx.AsyncClient, catalog: Catalog, db) -> None:
    token = await csrf(client, "/p/tee")
    # Choosing options resolves the variant server-side
    r = await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.product.id),
            "color_id": str(catalog.tee_black_m.color_id),
            "size_id": str(catalog.tee_black_m.size_id),
            "quantity": "2",
        },
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and "Black / M" in r.text and "cart:open" in r.headers["HX-Trigger"]

    # Missing size is rejected with a toast
    r = await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.product.id),
            "color_id": str(catalog.tee_black_m.color_id),
        },
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 400 and "toast" in r.headers["HX-Trigger"]

    # Validation errors re-render the form with inline messages
    r = await client.post(
        "/checkout",
        data={
            "csrf_token": token,
            "full_name": "A",
            "phone": "123",
            "governorate": "cairo",
            "address": "short",
            "payment_method": "cod",
        },
    )
    assert r.status_code == 422 and "valid Egyptian mobile" in r.text

    r = await client.post(
        "/checkout",
        data={
            "csrf_token": token,
            "full_name": "Mona Ali",
            "phone": "+20 100 123 4567",
            "email": "",
            "governorate": "alexandria",
            "address": "5 Sea Road, Building 2, Floor 3",
            "notes": "",
            "payment_method": "cod",
        },
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/order/")
    page = await client.get(r.headers["location"])
    assert "#1001" in page.text and "call you to confirm" in page.text

    # Cart was cleared
    assert "Your bag is empty" in (await client.get("/cart")).text


async def test_checkout_rejects_missing_csrf(client: httpx.AsyncClient, catalog: Catalog) -> None:
    await csrf(client)
    r = await client.post("/checkout", data={"full_name": "x"})
    assert r.status_code == 403


async def test_order_page_requires_valid_token(
    client: httpx.AsyncClient, catalog: Catalog, db
) -> None:
    from tests.integration.test_orders import checkout

    order = await order_service.place_order(db, checkout(), [(catalog.single.id, 1)])
    assert (await client.get(f"/order/{order.id}")).status_code == 404
    assert (await client.get(f"/order/{order.id}?t=wrong")).status_code == 404
    assert (await client.get(f"/order/{order.id}?t={order_token(order.id)}")).status_code == 200


async def test_paymob_webhook(client: httpx.AsyncClient, catalog: Catalog, db) -> None:
    from app.models import PaymentMethod
    from tests.integration.test_orders import checkout

    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    obj = {
        "id": 777,
        "pending": False,
        "amount_cents": order.total_piasters,
        "success": True,
        "is_auth": False,
        "is_capture": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "is_refunded": False,
        "is_3d_secure": True,
        "integration_id": 12345,
        "has_parent_transaction": False,
        "error_occured": False,
        "currency": "EGP",
        "created_at": "2026-10-02T12:00:00.000000",
        "owner": 1,
        "order": {"id": 555, "merchant_order_id": f"{order.id}~1"},
        "source_data": {"pan": "1234", "sub_type": "Visa", "type": "card"},
    }
    body = {"type": "TRANSACTION", "obj": obj}
    bad = await client.post("/webhooks/paymob?hmac=deadbeef", json=body)
    assert bad.status_code == 401

    sig = paymob.compute_hmac(obj, "hmac_test_secret")
    for _ in range(2):  # duplicate delivery is harmless
        ok = await client.post(f"/webhooks/paymob?hmac={sig}", json=body)
        assert ok.status_code == 200
    await db.refresh(order)
    fresh = await db.get(Order, order.id, populate_existing=True)
    assert fresh is not None
    assert fresh.payment_status == PaymentStatus.paid and fresh.status == OrderStatus.confirmed


async def test_cleanup_endpoint_requires_token(client: httpx.AsyncClient) -> None:
    assert (await client.post("/internal/cleanup")).status_code == 401
    r = await client.post("/internal/cleanup", headers={"Authorization": "Bearer test-cron-token"})
    assert r.status_code == 200 and r.json()["cancelled"] == 0


async def test_admin_login_and_cancel(client: httpx.AsyncClient, catalog: Catalog, db) -> None:
    from tests.integration.test_orders import checkout

    db.add(
        AdminUser(username="owner", display_name="Owner", password_hash=hash_password("pass-12345"))
    )
    await db.commit()
    order = await order_service.place_order(db, checkout(), [(catalog.tee_black_m.id, 2)])

    assert (await client.get("/admin")).status_code == 303
    token = await csrf(client, "/admin/login")
    bad = await client.post(
        "/admin/login", data={"csrf_token": token, "username": "owner", "password": "nope"}
    )
    assert bad.status_code == 401
    r = await client.post(
        "/admin/login", data={"csrf_token": token, "username": "owner", "password": "pass-12345"}
    )
    assert r.status_code == 303
    token = await csrf(client, "/admin/blocklist")
    assert (await client.get(f"/admin/orders/{order.id}")).status_code == 200
    r = await client.post(
        f"/admin/orders/{order.id}/status",
        data={"csrf_token": token, "status": "cancelled", "note": ""},
    )
    assert r.status_code == 303
    fresh = await db.get(Order, order.id, populate_existing=True)
    assert fresh is not None and fresh.status == OrderStatus.cancelled and fresh.stock_restored


async def test_api(client: httpx.AsyncClient, catalog: Catalog) -> None:
    products = (await client.get("/api/v1/products")).json()
    assert products["total"] == 2
    detail = (await client.get("/api/v1/products/tee")).json()
    assert {v["sku"] for v in detail["variants"]} == {"TEE-BLK-M", "TEE-BLK-L"}
    assert len((await client.get("/api/v1/shipping/rates")).json()) == 27

    r = await client.post(
        "/api/v1/orders",
        json={
            "full_name": "API Buyer",
            "phone": "01212345678",
            "governorate": "giza",
            "address": "10 Pyramids Street, Giza",
            "payment_method": "cod",
            "items": [{"variant_id": str(catalog.single.id), "quantity": 1}],
        },
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["total_piasters"] == 240000 + 10000
    got = await client.get(f"/api/v1/orders/{order['id']}?token={order['token']}")
    assert got.status_code == 200
    bad = await client.post("/api/v1/orders", json={"full_name": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation"


async def test_checkout_stock_runs_out_before_submit(
    client: httpx.AsyncClient, catalog: Catalog, db
) -> None:
    from sqlalchemy import update

    from app.models import ProductVariant

    token = await csrf(client, "/p/bag")
    await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.single.product_id),
            "quantity": "2",
            "variant_id": str(catalog.single.id),
        },
    )
    # Another customer buys most of the stock in the meantime.
    await db.execute(
        update(ProductVariant).where(ProductVariant.id == catalog.single.id).values(stock=1)
    )
    await db.commit()
    r = await client.post(
        "/checkout",
        data={
            "csrf_token": token,
            "full_name": "Mona Ali",
            "phone": "01001234567",
            "governorate": "cairo",
            "address": "5 Sea Road, Building 2",
            "payment_method": "cod",
        },
    )
    # The cart clamps to what's left; the order goes through for the remaining unit
    # or the form is shown again with a clear message — never a server error.
    assert r.status_code in (303, 409, 400), r.status_code


async def test_checkout_business_error_rerenders_form(
    client: httpx.AsyncClient, catalog: Catalog, db
) -> None:
    from sqlalchemy import update

    from app.models import ProductVariant

    await db.execute(
        update(ProductVariant).where(ProductVariant.id == catalog.single.id).values(stock=10)
    )
    await db.commit()
    token = await csrf(client, "/p/bag")
    await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.single.product_id),
            "quantity": "3",
            "variant_id": str(catalog.single.id),
        },
    )
    r = await client.post(
        "/checkout",
        data={
            "csrf_token": token,
            "full_name": "Mona Ali",
            "phone": "01001234567",
            "governorate": "cairo",
            "address": "5 Sea Road, Building 2",
            "payment_method": "cod",
        },
    )
    # 3 x 2,400 EGP exceeds COD_MAX_ORDER_EGP=5000: form shown again with the message, cart intact.
    assert r.status_code == 400
    assert "Cash on delivery is available for orders up to 5000 EGP" in r.text
    assert "Mona Ali" in r.text and "Bag" in r.text
