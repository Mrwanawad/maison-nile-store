"""Order SQL access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
    PhoneBlock,
    ProductVariant,
)

OPEN_STATUSES = (OrderStatus.pending, OrderStatus.confirmed)


async def upsert_customer(
    session: AsyncSession,
    *,
    phone: str,
    full_name: str,
    email: str | None,
    governorate: str,
    address: str,
) -> uuid.UUID:
    values = {
        "phone": phone,
        "full_name": full_name,
        "email": email,
        "governorate": governorate,
        "address": address,
    }
    stmt = (
        insert(Customer)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[Customer.phone],
            set_={**values, "updated_at": func.now()},
        )
        .returning(Customer.id)
    )
    customer_id = (await session.execute(stmt)).scalar_one()
    return customer_id


async def get_order(
    session: AsyncSession, order_id: uuid.UUID, *, for_update: bool = False
) -> Order | None:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.events))
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Order)
    return await session.scalar(stmt)


async def get_order_by_number(session: AsyncSession, number: int) -> Order | None:
    stmt = (
        select(Order)
        .where(Order.order_number == number)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    return await session.scalar(stmt)


async def list_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    payment_status: PaymentStatus | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Order], int]:
    stmt = select(Order)
    if status:
        stmt = stmt.where(Order.status == status)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if query:
        q = query.strip().lstrip("#")
        conds: list[Any] = [
            Order.ship_phone.ilike(f"%{q}%"),
            Order.ship_full_name.ilike(f"%{q}%"),
        ]
        if q.isdigit():
            conds.append(Order.order_number == int(q))
        stmt = stmt.where(or_(*conds))
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await session.scalars(
        stmt.order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(Order.items))
    )
    return rows.all(), total


async def count_open_cod_orders(session: AsyncSession, phone: str) -> int:
    stmt = select(func.count()).where(
        Order.ship_phone == phone,
        Order.payment_method == PaymentMethod.cod,
        Order.status.in_(OPEN_STATUSES),
    )
    return int(await session.scalar(stmt) or 0)


async def is_phone_blocked(session: AsyncSession, phone: str) -> bool:
    return (await session.get(PhoneBlock, phone)) is not None


async def record_transaction(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    provider_txn_id: str,
    success: bool,
    is_refund: bool,
    amount_piasters: int,
    currency: str,
    raw: dict[str, Any],
) -> bool:
    """Insert a Paymob transaction. Returns False if it was already recorded (duplicate)."""
    stmt = (
        insert(PaymentTransaction)
        .values(
            order_id=order_id,
            provider_txn_id=provider_txn_id,
            success=success,
            is_refund=is_refund,
            amount_piasters=amount_piasters,
            currency=currency,
            raw=raw,
        )
        .on_conflict_do_nothing(index_elements=[PaymentTransaction.provider_txn_id])
        .returning(PaymentTransaction.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def stale_unpaid_online_orders(
    session: AsyncSession, cutoff: datetime, limit: int = 100
) -> Sequence[Order]:
    stmt = (
        select(Order)
        .where(
            Order.payment_method == PaymentMethod.paymob,
            Order.payment_status.in_((PaymentStatus.unpaid, PaymentStatus.failed)),
            Order.status == OrderStatus.pending,
            Order.created_at < cutoff,
        )
        .order_by(Order.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    return (await session.scalars(stmt)).all()


async def adjust_stock(session: AsyncSession, items: Sequence[OrderItem], sign: int) -> None:
    """Add (sign=1) or remove (sign=-1) the item quantities to/from variant stock."""
    for item in sorted(items, key=lambda i: str(i.variant_id)):
        if item.variant_id is None:
            continue
        variant = await session.get(ProductVariant, item.variant_id, with_for_update=True)
        if variant is not None:
            variant.stock += sign * item.quantity


async def stats_since(session: AsyncSession, since: datetime) -> dict[str, int]:
    row = (
        await session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_piasters), 0),
            ).where(Order.created_at >= since, Order.status != OrderStatus.cancelled)
        )
    ).one()
    return {"orders": int(row[0]), "revenue": int(row[1])}


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Order.status, func.count()).group_by(Order.status))
    return {str(status): int(n) for status, n in rows.all()}
