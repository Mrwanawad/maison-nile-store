"""Online payments via Paymob: start checkout, apply verified transactions, refunds."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, IntegrationError, NotFound
from app.integrations import paymob
from app.models import Order, OrderEvent, OrderStatus, PaymentMethod, PaymentStatus
from app.repositories import order_repo
from app.services import order_service
from app.utils import governorates

log = logging.getLogger("app.payments")

REF_SEPARATOR = "~"


class Outcome(StrEnum):
    paid = "paid"
    failed = "failed"
    ignored = "ignored"
    needs_refund = "needs_refund"


@dataclass(slots=True)
class PaymentResult:
    order_id: uuid.UUID | None
    outcome: Outcome


def _reference(order: Order) -> str:
    # Paymob needs a unique reference per intention; one order may need several attempts.
    return f"{order.id}{REF_SEPARATOR}{order.payment_attempts}"


def order_id_from_reference(reference: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(reference.split(REF_SEPARATOR, 1)[0])
    except ValueError:
        return None


def _billing(order: Order) -> dict[str, str]:
    first, _, last = order.ship_full_name.partition(" ")
    gov = governorates.get(order.ship_governorate)
    return {
        "first_name": first or "NA",
        "last_name": last or first or "NA",
        "phone_number": "+2" + order.ship_phone,
        "email": order.ship_email or "na@example.com",
        "street": order.ship_address[:200],
        "building": "NA",
        "floor": "NA",
        "apartment": "NA",
        "city": gov.name_en if gov else "NA",
        "state": gov.name_en if gov else "NA",
        "country": "EGY",
    }


def _items(order: Order) -> list[dict[str, object]]:
    items: list[dict[str, object]] = [
        {
            "name": (
                item.product_name_en
                + (f" - {item.variant_label_en}" if item.variant_label_en else "")
            )[:50],
            "amount": item.unit_price_piasters,
            "quantity": item.quantity,
            "description": item.sku,
        }
        for item in order.items
    ]
    if order.shipping_piasters:
        items.append(
            {
                "name": "Shipping",
                "amount": order.shipping_piasters,
                "quantity": 1,
                "description": "Delivery",
            }
        )
    return items


async def start_checkout(db: AsyncSession, order_id: uuid.UUID) -> str:
    """Create a Paymob intention for the order and return the hosted checkout URL."""
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        raise NotFound()
    if order.payment_method != PaymentMethod.paymob:
        raise AppError("payment.error.not_online")
    if order.payment_status == PaymentStatus.paid or order.status != OrderStatus.pending:
        raise AppError("payment.error.not_payable")
    order.payment_attempts += 1
    try:
        intention = await paymob.create_intention(
            amount_cents=order.total_piasters,
            special_reference=_reference(order),
            billing=_billing(order),
            items=_items(order),
            extras={"order_number": order.order_number},
        )
    except IntegrationError:
        await db.rollback()
        raise AppError("payment.error.unavailable", status_code=502) from None
    order.paymob_intention_id = intention.id
    order.paymob_order_id = intention.paymob_order_id
    order.paymob_client_secret = intention.client_secret
    await db.commit()
    return paymob.checkout_url(intention.client_secret)


async def apply_transaction(db: AsyncSession, txn: paymob.Transaction) -> PaymentResult:
    """Apply a verified transaction exactly once. Safe for webhook + redirect + inquiry."""
    order_id = order_id_from_reference(txn.merchant_order_id)
    if order_id is None:
        log.warning("paymob txn without our reference", extra={"ctx": {"txn": txn.id}})
        return PaymentResult(None, Outcome.ignored)
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        log.warning("paymob txn for unknown order", extra={"ctx": {"txn": txn.id}})
        return PaymentResult(None, Outcome.ignored)
    if txn.pending or txn.is_refund or txn.is_voided:
        # Refunds are recorded by the refund flow; pending txns will be re-sent.
        await db.rollback()
        return PaymentResult(order.id, Outcome.ignored)

    is_new = await order_repo.record_transaction(
        db,
        order_id=order.id,
        provider_txn_id=txn.id,
        success=txn.success,
        is_refund=False,
        amount_piasters=txn.amount_cents,
        currency=txn.currency,
        raw=txn.raw,
    )
    if not is_new:
        await db.rollback()
        return PaymentResult(order.id, Outcome.ignored)

    if txn.success and (txn.amount_cents != order.total_piasters or txn.currency != "EGP"):
        order.events.append(
            OrderEvent(
                kind="payment",
                actor="paymob",
                note=f"amount mismatch txn={txn.id} {txn.amount_cents} {txn.currency}",
            )
        )
        await db.commit()
        log.error("paymob amount mismatch", extra={"ctx": {"order": order.order_number}})
        return PaymentResult(order.id, Outcome.needs_refund)

    if txn.success:
        ok = await order_service.mark_paid(db, order, txn.id)
        outcome = Outcome.paid if ok else Outcome.needs_refund
    else:
        order_service.mark_failed(order, txn.id)
        outcome = Outcome.failed
    await db.commit()
    log.info("payment applied", extra={"ctx": {"order": order.order_number, "outcome": outcome}})
    return PaymentResult(order.id, outcome)


async def reconcile(
    db: AsyncSession, order: Order, txn_id: str | None = None
) -> PaymentResult | None:
    """Ask Paymob directly (needs PAYMOB_API_KEY) when no callback arrived yet."""
    if order.payment_status == PaymentStatus.paid:
        return None
    try:
        if txn_id:
            txn = await paymob.get_transaction(txn_id)
            candidates = [txn] if txn else []
        else:
            candidates = await paymob.get_order_transactions(order.paymob_order_id or "")
    except IntegrationError:
        return None
    result = None
    for txn in candidates:
        belongs = order_id_from_reference(txn.merchant_order_id) == order.id or (
            order.paymob_order_id and txn.paymob_order_id == order.paymob_order_id
        )
        if not belongs:
            continue
        if not txn.merchant_order_id:
            txn = replace(txn, merchant_order_id=f"{order.id}{REF_SEPARATOR}0")
        result = await apply_transaction(db, txn)
        if result.outcome == Outcome.paid:
            break
    return result


async def refund(
    db: AsyncSession, order_id: uuid.UUID, amount_piasters: int, *, actor: str
) -> Order:
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        raise NotFound()
    if order.payment_status not in (PaymentStatus.paid, PaymentStatus.partially_refunded):
        raise AppError("admin.error.refund_not_paid")
    if not order.paymob_txn_id:
        raise AppError("admin.error.refund_no_txn")
    refundable = order.total_piasters - order.refunded_piasters
    if amount_piasters <= 0 or amount_piasters > refundable:
        raise AppError("admin.error.refund_amount")
    try:
        response = await paymob.refund(order.paymob_txn_id, amount_piasters)
    except IntegrationError:
        await db.rollback()
        raise AppError("admin.error.refund_failed", status_code=502) from None
    if response.get("success") is False:
        await db.rollback()
        raise AppError("admin.error.refund_failed", status_code=502)
    refund_txn_id = str(response.get("id") or f"refund-{uuid.uuid4().hex[:12]}")
    await order_repo.record_transaction(
        db,
        order_id=order.id,
        provider_txn_id=refund_txn_id,
        success=True,
        is_refund=True,
        amount_piasters=amount_piasters,
        currency="EGP",
        raw=response,
    )
    order.refunded_piasters += amount_piasters
    order.payment_status = (
        PaymentStatus.refunded
        if order.refunded_piasters >= order.total_piasters
        else PaymentStatus.partially_refunded
    )
    order.events.append(
        OrderEvent(kind="refund", actor=actor, note=f"refunded {amount_piasters} piasters")
    )
    await db.commit()
    return await order_service.get_order(db, order.id)
