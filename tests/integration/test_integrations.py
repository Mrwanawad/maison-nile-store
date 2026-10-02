"""Online payment, refunds, Bosta and outbound API calls, with third-party HTTP faked."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import order_token
from app.integrations import email, telegram
from app.integrations.storage import SupabaseStorage
from app.models import Order, OrderStatus, PaymentMethod, PaymentStatus, PaymentTransaction
from app.services import order_service, payment_service
from tests.conftest import Catalog, FakeHTTP, csrf, flash
from tests.integration.test_orders import checkout

INTENTION = {"id": "pi_test_1", "client_secret": "csk_test_abc", "intention_order_id": 9001}


async def _paid_order(db, catalog: Catalog) -> Order:  # type: ignore[no-untyped-def]
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    order_id = order.id
    await payment_service.apply_transaction(
        db,
        payment_service.paymob.parse_transaction(
            {
                "id": 4242,
                "success": True,
                "pending": False,
                "amount_cents": order.total_piasters,
                "currency": "EGP",
                "order": {"id": 9001, "merchant_order_id": f"{order_id}~1"},
            }
        ),
    )
    return await order_service.get_order(db, order_id)


async def test_online_checkout_redirects_to_paymob(
    client, catalog: Catalog, fake_http: FakeHTTP
) -> None:  # type: ignore[no-untyped-def]
    fake_http.on("/v1/intention/", json=INTENTION)
    token = await csrf(client, "/p/bag")
    await client.post(
        "/cart/items",
        data={
            "csrf_token": token,
            "product_id": str(catalog.single.product_id),
            "variant_id": str(catalog.single.id),
        },
    )
    r = await client.post(
        "/checkout",
        data={
            "csrf_token": token,
            "full_name": "Mona Ali",
            "phone": "01001234567",
            "email": "mona@example.com",
            "governorate": "giza",
            "address": "10 Pyramids Street, Giza",
            "payment_method": "paymob",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == (
        "https://accept.paymob.com/unifiedcheckout/?publicKey=pk_test&clientSecret=csk_test_abc"
    )
    [sent] = fake_http.sent("/v1/intention/")
    request = fake_http.requests[0]
    assert request.headers["authorization"] == "Token sk_test"
    assert sent["amount"] == 240000 + 10000 and sent["currency"] == "EGP"
    assert sent["payment_methods"] == [12345]
    assert sum(i["amount"] * i["quantity"] for i in sent["items"]) == sent["amount"]
    assert sent["billing_data"]["phone_number"] == "+201001234567"
    assert sent["notification_url"].endswith("/webhooks/paymob")
    assert sent["special_reference"].endswith("~1")
    async with SessionLocal() as s:
        order = await s.scalar(select(Order))
        assert order and order.paymob_order_id == "9001" and order.payment_attempts == 1


async def test_paymob_down_keeps_order_and_offers_retry(
    client, catalog: Catalog, db, fake_http: FakeHTTP
) -> None:  # type: ignore[no-untyped-def]
    fake_http.on("/v1/intention/", status=500, json={"detail": "boom"})
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    order_id, t = order.id, order_token(order.id)
    token = await csrf(client, f"/order/{order_id}?t={t}")
    r = await client.post(f"/order/{order_id}/pay", data={"csrf_token": token, "t": t})
    assert r.status_code == 303 and "pay_error=1" in r.headers["location"]
    page = await client.get(r.headers["location"])
    assert "couldn" in page.text and "Confirming your payment" in page.text

    fake_http.on("/v1/intention/", json=INTENTION)
    r = await client.post(f"/order/{order_id}/pay", data={"csrf_token": token, "t": t})
    assert r.headers["location"].startswith("https://accept.paymob.com/unifiedcheckout/")


async def test_return_page_asks_paymob_when_webhook_is_late(  # type: ignore[no-untyped-def]
    client, catalog: Catalog, db, fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "paymob_api_key", "api_key_test")
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    order_id, total = order.id, order.total_piasters
    fake_http.on("/api/auth/tokens", json={"token": "auth123"})
    fake_http.on(
        "/api/acceptance/transactions/5151",
        json={
            "id": 5151,
            "success": True,
            "pending": False,
            "amount_cents": total,
            "currency": "EGP",
            "order": {"id": 9001, "merchant_order_id": f"{order_id}~1"},
        },
    )
    r = await client.get(
        f"/payments/paymob/return?merchant_order_id={order_id}~1&id=5151&success=true"
    )
    assert r.status_code == 303 and r.headers["location"].startswith(f"/order/{order_id}")
    assert "token=auth123" in str(fake_http.requests[-1].url)
    fresh = await order_service.get_order(db, order_id)
    assert fresh.payment_status == PaymentStatus.paid and fresh.status == OrderStatus.confirmed


async def test_forged_return_params_change_nothing(client, catalog: Catalog, db) -> None:  # type: ignore[no-untyped-def]
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    order_id = order.id
    r = await client.get(
        f"/payments/paymob/return?merchant_order_id={order_id}~1&id=1&success=true"
    )
    assert r.status_code == 303
    fresh = await order_service.get_order(db, order_id)
    assert fresh.payment_status == PaymentStatus.unpaid


async def test_admin_refund(admin_client, catalog: Catalog, db, fake_http: FakeHTTP) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    order = await _paid_order(db, catalog)
    order_id = order.id
    fake_http.on("/api/acceptance/void_refund/refund", json={"id": 777001, "success": True})
    await client.post(
        f"/admin/orders/{order_id}/refund", data={"csrf_token": token, "amount_egp": "500"}
    )
    assert "Refund sent" in await flash(client)
    assert fake_http.sent("void_refund")[0] == {"transaction_id": 4242, "amount_cents": 50000}
    fresh = await order_service.get_order(db, order_id)
    assert (
        fresh.refunded_piasters == 50000
        and fresh.payment_status == PaymentStatus.partially_refunded
    )

    # Can't refund more than what's left
    await client.post(
        f"/admin/orders/{order_id}/refund",
        data={"csrf_token": token, "amount_egp": "99999"},
        headers={"Referer": f"http://test/admin/orders/{order_id}"},
    )
    assert "refundable total" in await flash(client)
    async with SessionLocal() as s:
        refunds = (
            await s.scalars(select(PaymentTransaction).where(PaymentTransaction.is_refund))
        ).all()
    assert len(refunds) == 1


async def test_refund_rejected_by_paymob(
    admin_client, catalog: Catalog, db, fake_http: FakeHTTP
) -> None:  # type: ignore[no-untyped-def]
    client, token = admin_client
    order = await _paid_order(db, catalog)
    order_id = order.id
    fake_http.on("/api/acceptance/void_refund/refund", status=400, json={"detail": "no"})
    await client.post(
        f"/admin/orders/{order_id}/refund",
        data={"csrf_token": token, "amount_egp": "10"},
        headers={"Referer": f"http://test/admin/orders/{order_id}"},
    )
    assert "rejected the refund" in await flash(client)
    assert (await order_service.get_order(db, order_id)).refunded_piasters == 0


async def test_bosta_shipment(  # type: ignore[no-untyped-def]
    admin_client, catalog: Catalog, db, fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = admin_client
    order = await order_service.place_order(
        db, checkout(gov="alexandria"), [(catalog.single.id, 1)]
    )
    order_id = order.id
    await client.post(
        f"/admin/orders/{order_id}/bosta",
        data={"csrf_token": token},
        headers={"Referer": f"http://test/admin/orders/{order_id}"},
    )
    assert "not configured" in await flash(client)

    monkeypatch.setattr(get_settings(), "bosta_enabled", True)
    monkeypatch.setattr(get_settings(), "bosta_api_key", "bosta_key")
    fake_http.on(
        "/deliveries", json={"success": True, "data": {"_id": "d1", "trackingNumber": "TRK123"}}
    )
    await order_service.change_status(db, order_id, OrderStatus.confirmed, actor="test")
    await client.post(f"/admin/orders/{order_id}/bosta", data={"csrf_token": token})
    assert "TRK123" in await flash(client)
    [sent] = fake_http.sent("/deliveries")
    assert fake_http.requests[-1].headers["authorization"] == "bosta_key"
    assert sent["cod"] == 2450.0 and sent["dropOffAddress"]["city"] == "Alexandria"
    assert sent["receiver"]["phone"] == "01012345678" and sent["businessReference"] == "#1001"
    fresh = await order_service.get_order(db, order_id)
    assert fresh.status == OrderStatus.shipped and fresh.bosta_tracking_number == "TRK123"
    page = await client.get(f"/order/{order_id}?t={order_token(order_id)}")
    assert "Track your shipment" in page.text


async def test_telegram_sends_to_every_owner(
    fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "123:abc")
    monkeypatch.setattr(get_settings(), "telegram_chat_ids", "111, 222")
    fake_http.on("api.telegram.org", json={"ok": True})
    await telegram.send("<b>hi</b>")
    sent = fake_http.sent("/bot123:abc/sendMessage")
    assert [m["chat_id"] for m in sent] == ["111", "222"] and sent[0]["parse_mode"] == "HTML"


async def test_telegram_failure_never_raises(
    fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "123:abc")
    monkeypatch.setattr(get_settings(), "telegram_chat_ids", "111")
    fake_http.on("api.telegram.org", status=500)
    await telegram.send("x")  # logged, not raised


@pytest.mark.parametrize(
    ("provider", "url_part"), [("brevo", "api.brevo.com"), ("resend", "api.resend.com")]
)
async def test_email_providers(  # type: ignore[no-untyped-def]
    provider: str, url_part: str, fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "email_provider", provider)
    monkeypatch.setattr(get_settings(), "email_api_key", "key")
    fake_http.on(url_part, json={})
    await email.send(to="a@b.co", subject="Hi", html="<p>x</p>", text="x")
    [sent] = fake_http.sent(url_part)
    assert sent["subject"] == "Hi"


async def test_confirmation_email_renders_in_both_languages(
    catalog: Catalog, db, fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from app.services import notification_service

    monkeypatch.setattr(get_settings(), "email_provider", "brevo")
    monkeypatch.setattr(get_settings(), "email_api_key", "key")
    fake_http.on("api.brevo.com", json={})
    data = checkout().model_copy(update={"email": "mona@example.com"})
    for locale in ("en", "ar"):
        order = await order_service.place_order(db, data, [(catalog.single.id, 1)], locale=locale)
        await notification_service.customer_confirmation(notification_service.snapshot(order))
    en, ar = fake_http.sent("api.brevo.com")
    assert (
        "#1001" in en["subject"] and "Bag" in en["htmlContent"] and "/order/" in en["textContent"]
    )
    assert (
        "تم تأكيد طلبك" in ar["subject"]
        and 'dir="rtl"' in ar["htmlContent"]
        and "/ar/order/" in ar["htmlContent"]
    )


async def test_supabase_storage(fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(get_settings(), "supabase_service_key", "service")
    fake_http.on("/storage/v1/object", json={})
    storage = SupabaseStorage()
    url = await storage.put("products/x/a.webp", b"data", "image/webp")
    assert url == "https://proj.supabase.co/storage/v1/object/public/products/products/x/a.webp"
    assert fake_http.requests[0].headers["x-upsert"] == "true"
    await storage.delete(url)
    assert fake_http.sent("/storage/v1/object/products")[-1] == {"prefixes": ["products/x/a.webp"]}


async def test_cleanup_reconciles_before_cancelling(  # type: ignore[no-untyped-def]
    client, catalog: Catalog, db, fake_http: FakeHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    monkeypatch.setattr(get_settings(), "paymob_api_key", "api_key_test")
    paid_late = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    abandoned = await order_service.place_order(
        db, checkout(PaymentMethod.paymob, phone="01111111111"), [(catalog.single.id, 1)]
    )
    paid_id, paid_total, abandoned_id = paid_late.id, paid_late.total_piasters, abandoned.id
    async with SessionLocal() as s:
        await s.execute(
            update(Order).values(
                created_at=datetime.now(UTC) - timedelta(hours=2), paymob_order_id="9001"
            )
        )
        await s.execute(
            update(Order).where(Order.id == abandoned_id).values(paymob_order_id="9002")
        )
        await s.commit()
    fake_http.on("/api/auth/tokens", json={"token": "t"})
    fake_http.on(
        "/api/ecommerce/orders/9001",
        json={
            "transactions": [
                {
                    "id": 8080,
                    "success": True,
                    "pending": False,
                    "amount_cents": paid_total,
                    "currency": "EGP",
                    "order": 9001,
                }
            ]
        },
    )
    fake_http.on("/api/ecommerce/orders/9002", json={"transactions": []})

    r = await client.post("/internal/cleanup", headers={"Authorization": "Bearer test-cron-token"})
    assert r.status_code == 200 and r.json() == {"cancelled": 1, "reconciled": 1}
    assert (await order_service.get_order(db, paid_id)).status == OrderStatus.confirmed
    assert (await order_service.get_order(db, abandoned_id)).status == OrderStatus.cancelled
