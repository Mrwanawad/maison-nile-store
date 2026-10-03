"""Order lifecycle: atomic placement, status transitions, stock restoration."""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFound, OutOfStock
from app.core.i18n import localized
from app.models import (
    Order,
    OrderEvent,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.repositories import catalog_repo, order_repo
from app.schemas.checkout import CheckoutData
from app.services import fraud_service, shipping_service
from app.services.catalog_service import primary_image, variant_label
from app.utils.money import egp_to_piasters

log = logging.getLogger("app.orders")

# Allowed manual status changes (admin). Cancelling restores stock.
TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.pending: {OrderStatus.confirmed, OrderStatus.cancelled},
    OrderStatus.confirmed: {OrderStatus.pending, OrderStatus.shipped, OrderStatus.cancelled},
    OrderStatus.shipped: {OrderStatus.delivered, OrderStatus.cancelled},
    OrderStatus.delivered: set(),
    OrderStatus.cancelled: set(),
}


def _merge(items: Sequence[tuple[uuid.UUID, int]]) -> OrderedDict[uuid.UUID, int]:
    merged: OrderedDict[uuid.UUID, int] = OrderedDict()
    for variant_id, qty in items:
        merged[variant_id] = merged.get(variant_id, 0) + qty
    return merged


def _event(
    order: Order,
    kind: str,
    actor: str,
    *,
    note: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
) -> None:
    order.events.append(
        OrderEvent(kind=kind, actor=actor, note=note, from_status=from_status, to_status=to_status)
    )


async def place_order(
    db: AsyncSession,
    data: CheckoutData,
    items: Sequence[tuple[uuid.UUID, int]],
    *,
    locale: str = "en",
) -> Order:
    """Validate, reserve stock and create the order in one transaction.

    Prices are read from the locked variant rows, never from the client.
    """
    settings = get_settings()
    merged = _merge(items)
    if not merged:
        raise AppError("checkout.error.empty_cart")
    if data.payment_method == PaymentMethod.cod and not settings.cod_enabled:
        raise AppError("checkout.error.cod_disabled")
    if data.payment_method == PaymentMethod.paymob and not settings.paymob_ready:
        raise AppError("checkout.error.online_unavailable")

    max_qty = settings.max_qty_per_line
    try:
        if data.payment_method == PaymentMethod.cod:
            await fraud_service.check_cod_customer(db, data.phone)

        variants = {v.id: v for v in await catalog_repo.lock_variants(db, list(merged))}
        order_items: list[OrderItem] = []
        subtotal = 0
        for position, (variant_id, qty) in enumerate(merged.items()):
            variant = variants.get(variant_id)
            if variant is None or not variant.is_active or not variant.product.is_active:
                raise OutOfStock("checkout.error.unavailable")
            label = variant_label(variant)
            name = localized(variant.product, "name") + (f" ({label})" if label else "")
            if qty > max_qty:
                raise AppError("cart.error.max_qty", max=max_qty)
            if variant.stock < qty:
                raise OutOfStock(
                    "checkout.error.insufficient_stock",
                    name=name,
                    available=variant.stock,
                )
            unit = variant.unit_price_piasters
            subtotal += unit * qty
            variant.stock -= qty
            image = primary_image(variant.product, variant.color_id)
            order_items.append(
                OrderItem(
                    product_id=variant.product_id,
                    variant_id=variant.id,
                    position=position,
                    product_name_en=variant.product.name_en,
                    product_name_ar=variant.product.name_ar,
                    variant_label_en=variant_label(variant, "en"),
                    variant_label_ar=variant_label(variant, "ar"),
                    sku=variant.sku,
                    image_url=image.url if image else None,
                    unit_price_piasters=unit,
                    quantity=qty,
                )
            )

        shipping = shipping_service.fee_for(data.governorate)
        total = subtotal + shipping
        if data.payment_method == PaymentMethod.cod and settings.cod_max_order_egp:
            limit = egp_to_piasters(settings.cod_max_order_egp)
            if total > limit:
                raise AppError("checkout.error.cod_limit", limit=settings.cod_max_order_egp)

        customer_id = await order_repo.upsert_customer(
            db,
            phone=data.phone,
            full_name=data.full_name,
            email=data.email,
            governorate=data.governorate,
            address=data.address,
        )
        order = Order(
            customer_id=customer_id,
            status=OrderStatus.pending,
            payment_method=data.payment_method,
            payment_status=PaymentStatus.unpaid,
            locale=locale,
            ship_full_name=data.full_name,
            ship_phone=data.phone,
            ship_email=data.email,
            ship_governorate=data.governorate,
            ship_address=data.address,
            notes=data.notes,
            subtotal_piasters=subtotal,
            shipping_piasters=shipping,
            total_piasters=total,
            items=order_items,
            events=[],
        )
        _event(order, "created", "customer", to_status=OrderStatus.pending.value)
        db.add(order)
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    log.info(
        "order placed",
        extra={"ctx": {"order": order.order_number, "total": total, "method": data.payment_method}},
    )
    return await get_order(db, order.id)


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await order_repo.get_order(db, order_id)
    if order is None:
        raise NotFound()
    return order


async def restore_stock(db: AsyncSession, order: Order) -> None:
    """Return reserved items to stock exactly once."""
    if order.stock_restored:
        return
    await order_repo.adjust_stock(db, order.items, +1)
    order.stock_restored = True


async def _re_reserve_stock(db: AsyncSession, order: Order) -> bool:
    """Take stock again for an order whose stock was restored. False if not possible."""
    try:
        async with db.begin_nested():
            await order_repo.adjust_stock(db, order.items, -1)
            await db.flush()
    except IntegrityError:
        return False
    order.stock_restored = False
    return True


async def change_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    new_status: OrderStatus,
    *,
    actor: str,
    note: str | None = None,
) -> Order:
    """Manual (admin) status change with audit trail. Cancelling restores stock."""
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        raise NotFound()
    old = order.status
    if new_status == old:
        return order
    if new_status not in TRANSITIONS[old]:
        raise AppError("admin.error.transition", old=old.value, new=new_status.value)
    order.status = new_status
    if new_status == OrderStatus.cancelled:
        await restore_stock(db, order)
        order.cancel_reason = note
    _event(order, "status", actor, note=note, from_status=old.value, to_status=new_status.value)
    await db.commit()
    return await get_order(db, order_id)


async def add_note(db: AsyncSession, order_id: uuid.UUID, note: str, *, actor: str) -> None:
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        raise NotFound()
    _event(order, "note", actor, note=note)
    await db.commit()


async def mark_paid(db: AsyncSession, order: Order, txn_id: str) -> bool:
    """Apply a successful online payment. Caller holds the order row lock and commits.

    Returns True when the order is (now) confirmed, False when it was already
    cancelled and stock could not be reserved again (needs a refund).
    """
    if order.payment_status == PaymentStatus.paid:
        return True
    order.payment_status = PaymentStatus.paid
    order.paymob_txn_id = txn_id
    order.paid_at = datetime.now(UTC)
    _event(order, "payment", "paymob", note=f"paid txn={txn_id}", to_status="paid")
    if order.status == OrderStatus.cancelled:
        if order.stock_restored and not await _re_reserve_stock(db, order):
            _event(order, "note", "system", note="paid after cancellation; stock gone, refund")
            return False
        order.cancel_reason = None
    old = order.status
    if old in (OrderStatus.pending, OrderStatus.cancelled):
        order.status = OrderStatus.confirmed
        _event(order, "status", "paymob", from_status=old.value, to_status="confirmed")
    return True


def mark_failed(order: Order, txn_id: str) -> None:
    """A failed attempt. The order stays pending so the customer can retry;
    the cleanup job cancels it after the timeout."""
    if order.payment_status == PaymentStatus.paid:
        return
    order.payment_status = PaymentStatus.failed
    _event(order, "payment", "paymob", note=f"failed txn={txn_id}", to_status="failed")


async def cancel_stale_online_orders(db: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=get_settings().unpaid_order_timeout_min)
    orders = await order_repo.stale_unpaid_online_orders(db, cutoff)
    for order in orders:
        old = order.status
        order.status = OrderStatus.cancelled
        order.cancel_reason = "payment not completed"
        await restore_stock(db, order)
        _event(
            order,
            "status",
            "system",
            note="unpaid timeout",
            from_status=old.value,
            to_status="cancelled",
        )
    await db.commit()
    if orders:
        log.info("cancelled stale online orders", extra={"ctx": {"count": len(orders)}})
    return len(orders)
