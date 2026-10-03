"""Hand an order to Bosta."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, IntegrationError, NotFound
from app.integrations import bosta
from app.models import Order, OrderEvent, OrderStatus, PaymentStatus
from app.repositories import order_repo
from app.services import order_service
from app.utils import governorates


def _cod_amount(order: Order) -> int:
    """Amount the courier collects: nothing if already paid online."""
    if order.payment_status in (PaymentStatus.paid, PaymentStatus.partially_refunded):
        return 0
    return order.total_piasters


async def create_shipment(db: AsyncSession, order_id: uuid.UUID, *, actor: str) -> Order:
    if not get_settings().bosta_ready:
        raise AppError("admin.error.bosta_disabled")
    order = await order_repo.get_order(db, order_id, for_update=True)
    if order is None:
        raise NotFound()
    if order.bosta_tracking_number:
        raise AppError("admin.error.bosta_exists")
    if order.status not in (OrderStatus.confirmed, OrderStatus.pending):
        raise AppError("admin.error.bosta_status")
    first, _, last = order.ship_full_name.partition(" ")
    gov = governorates.get(order.ship_governorate)
    try:
        delivery = await bosta.create_delivery(
            reference=f"#{order.order_number}",
            cod_piasters=_cod_amount(order),
            first_name=first,
            last_name=last,
            phone=order.ship_phone,
            email=order.ship_email,
            city=gov.name_en if gov else order.ship_governorate,
            address=order.ship_address,
            items_count=sum(i.quantity for i in order.items),
            description=", ".join(f"{i.sku} x{i.quantity}" for i in order.items),
            notes=order.notes,
        )
    except IntegrationError as exc:
        await db.rollback()
        raise AppError("admin.error.bosta_failed", status_code=502, detail=str(exc)) from None
    order.bosta_delivery_id = delivery.id
    order.bosta_tracking_number = delivery.tracking_number
    order.events.append(
        OrderEvent(kind="shipment", actor=actor, note=f"Bosta {delivery.tracking_number}")
    )
    await db.commit()
    if order.status == OrderStatus.confirmed:
        return await order_service.change_status(
            db, order.id, OrderStatus.shipped, actor=actor, note="handed to Bosta"
        )
    return await order_service.get_order(db, order.id)
