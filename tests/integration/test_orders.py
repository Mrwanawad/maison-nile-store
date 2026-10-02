"""Order placement, stock safety, COD rules, payments and cleanup against real Postgres."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.errors import AppError, OutOfStock
from app.integrations import paymob
from app.models import (
    Order,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PhoneBlock,
    ProductVariant,
)
from app.schemas.checkout import CheckoutData
from app.services import order_service, payment_service
from app.services.payment_service import Outcome
from tests.conftest import Catalog


def checkout(
    method: PaymentMethod = PaymentMethod.cod, phone: str = "01012345678", gov: str = "cairo"
) -> CheckoutData:
    return CheckoutData(
        full_name="Test Customer",
        phone=phone,
        email=None,
        governorate=gov,
        address="12 Some Street, Building 4",
        notes=None,
        payment_method=method,
    )


async def stock_of(variant: ProductVariant) -> int:
    async with SessionLocal() as s:
        v = await s.get(ProductVariant, variant.id)
        assert v is not None
        return v.stock


async def test_place_order_uses_db_prices_and_decrements_stock(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(gov="alexandria"), [(catalog.tee_black_m.id, 2), (catalog.single.id, 1)]
    )
    assert order.order_number == 1001
    assert order.subtotal_piasters == 2 * 45000 + 240000
    assert order.shipping_piasters == 5000
    assert order.total_piasters == order.subtotal_piasters + 5000
    assert order.status == OrderStatus.pending
    assert [i.variant_label_en for i in order.items] == ["Black / M", ""]
    assert order.items[0].variant_label_ar == "أسود / M"
    assert await stock_of(catalog.tee_black_m) == 3
    assert await stock_of(catalog.single) == 2


async def test_duplicate_lines_are_merged(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(), [(catalog.tee_black_m.id, 1), (catalog.tee_black_m.id, 2)]
    )
    assert len(order.items) == 1 and order.items[0].quantity == 3


async def test_insufficient_stock_rolls_back_everything(db, catalog: Catalog) -> None:
    with pytest.raises(OutOfStock):
        await order_service.place_order(
            db, checkout(), [(catalog.tee_black_m.id, 1), (catalog.tee_black_l.id, 2)]
        )
    assert await stock_of(catalog.tee_black_m) == 5  # first line not taken either
    assert await stock_of(catalog.tee_black_l) == 1


async def test_concurrent_orders_for_last_unit_do_not_oversell(catalog: Catalog) -> None:
    async def attempt(phone: str) -> bool:
        async with SessionLocal() as s:
            try:
                await order_service.place_order(
                    s, checkout(phone=phone), [(catalog.tee_black_l.id, 1)]
                )
                return True
            except OutOfStock:
                return False

    results = await asyncio.gather(*(attempt(f"0101234567{i}") for i in range(5)))
    assert sum(results) == 1
    assert await stock_of(catalog.tee_black_l) == 0


async def test_cod_open_orders_limit(db, catalog: Catalog) -> None:
    # COD_MAX_OPEN_ORDERS_PER_PHONE=2
    for _ in range(2):
        await order_service.place_order(db, checkout(), [(catalog.single.id, 1)])
    with pytest.raises(AppError) as exc:
        await order_service.place_order(db, checkout(), [(catalog.tee_black_m.id, 1)])
    assert exc.value.key == "checkout.error.cod_open_orders"
    # Another phone is unaffected
    await order_service.place_order(
        db, checkout(phone="01099999999"), [(catalog.tee_black_m.id, 1)]
    )


async def test_cod_total_limit(db, catalog: Catalog) -> None:
    # COD_MAX_ORDER_EGP=5000; 3 bags = 7,200 EGP
    async with SessionLocal() as s:
        await s.execute(
            update(ProductVariant).where(ProductVariant.id == catalog.single.id).values(stock=10)
        )
        await s.commit()
    with pytest.raises(AppError) as exc:
        await order_service.place_order(db, checkout(), [(catalog.single.id, 3)])
    assert exc.value.key == "checkout.error.cod_limit"
    assert await stock_of(catalog.single) == 10


async def test_blocked_phone_cannot_use_cod_but_can_pay_online(db, catalog: Catalog) -> None:
    db.add(PhoneBlock(phone="01012345678", reason="refused", created_by="test"))
    await db.commit()
    with pytest.raises(AppError) as exc:
        await order_service.place_order(db, checkout(), [(catalog.single.id, 1)])
    assert exc.value.key == "checkout.error.cod_blocked"
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    assert order.payment_method == PaymentMethod.paymob


async def test_admin_cancel_restores_stock_once(db, catalog: Catalog) -> None:
    order = await order_service.place_order(db, checkout(), [(catalog.tee_black_m.id, 2)])
    assert await stock_of(catalog.tee_black_m) == 3
    order = await order_service.change_status(
        db, order.id, OrderStatus.cancelled, actor="admin:test"
    )
    assert order.stock_restored
    assert await stock_of(catalog.tee_black_m) == 5
    with pytest.raises(AppError):  # cancelled is final
        await order_service.change_status(db, order.id, OrderStatus.confirmed, actor="admin:test")
    assert await stock_of(catalog.tee_black_m) == 5
    assert [e.kind for e in order.events] == ["created", "status"]


def _txn(order: Order, txn_id: str, success: bool, amount: int | None = None) -> paymob.Transaction:
    obj = {
        "id": int(txn_id),
        "success": success,
        "pending": False,
        "amount_cents": amount if amount is not None else order.total_piasters,
        "currency": "EGP",
        "order": {"id": 999, "merchant_order_id": f"{order.id}~1"},
    }
    return paymob.parse_transaction(obj)


async def test_payment_success_is_idempotent(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    order_id, txn = order.id, _txn(order, "111", True)
    first = await payment_service.apply_transaction(db, txn)
    second = await payment_service.apply_transaction(db, txn)
    assert first.outcome == Outcome.paid
    assert second.outcome == Outcome.ignored
    order = await order_service.get_order(db, order_id)
    assert order.payment_status == PaymentStatus.paid
    assert order.status == OrderStatus.confirmed
    assert order.paymob_txn_id == "111"


async def test_failed_then_successful_attempt(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    assert (
        await payment_service.apply_transaction(db, _txn(order, "201", False))
    ).outcome == Outcome.failed
    order = await order_service.get_order(db, order.id)
    assert order.payment_status == PaymentStatus.failed and order.status == OrderStatus.pending
    assert await stock_of(catalog.single) == 2  # still reserved for a retry
    assert (
        await payment_service.apply_transaction(db, _txn(order, "202", True))
    ).outcome == Outcome.paid


async def test_amount_mismatch_is_not_marked_paid(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    result = await payment_service.apply_transaction(db, _txn(order, "301", True, amount=100))
    assert result.outcome == Outcome.needs_refund
    order = await order_service.get_order(db, order.id)
    assert order.payment_status == PaymentStatus.unpaid


async def test_cleanup_cancels_stale_unpaid_orders_and_late_payment_recovers(
    db, catalog: Catalog
) -> None:
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.single.id, 1)]
    )
    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=2))
        )
        await s.commit()
    assert await order_service.cancel_stale_online_orders(db) == 1
    assert await stock_of(catalog.single) == 3
    # A late successful payment re-reserves stock and confirms the order.
    result = await payment_service.apply_transaction(db, _txn(order, "401", True))
    assert result.outcome == Outcome.paid
    order = await order_service.get_order(db, order.id)
    assert order.status == OrderStatus.confirmed and not order.stock_restored
    assert await stock_of(catalog.single) == 2


async def test_late_payment_without_stock_needs_refund(db, catalog: Catalog) -> None:
    order = await order_service.place_order(
        db, checkout(PaymentMethod.paymob), [(catalog.tee_black_l.id, 1)]
    )
    await order_service.change_status(db, order.id, OrderStatus.cancelled, actor="system")
    # Someone else buys the last unit meanwhile.
    await order_service.place_order(
        db, checkout(phone="01111111111"), [(catalog.tee_black_l.id, 1)]
    )
    result = await payment_service.apply_transaction(db, _txn(order, "501", True))
    assert result.outcome == Outcome.needs_refund
    order = await order_service.get_order(db, order.id)
    assert order.payment_status == PaymentStatus.paid and order.status == OrderStatus.cancelled
    assert await stock_of(catalog.tee_black_l) == 0
