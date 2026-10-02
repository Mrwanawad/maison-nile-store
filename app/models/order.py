"""Orders, items, events, payments, customers."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk


class OrderStatus(enum.StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class PaymentMethod(enum.StrEnum):
    cod = "cod"
    paymob = "paymob"


class PaymentStatus(enum.StrEnum):
    unpaid = "unpaid"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


def _pg_enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Customer(UUIDPk, Timestamps, Base):
    """Latest known details per phone. Orders keep their own copy."""

    __tablename__ = "customers"

    phone: Mapped[str] = mapped_column(String(11), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    governorate: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(Text)


class Order(UUIDPk, Timestamps, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_piasters = subtotal_piasters + shipping_piasters", name="total_sum"),
        CheckConstraint("refunded_piasters >= 0", name="refunded_non_negative"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_ship_phone", "ship_phone"),
    )

    order_number: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1001), unique=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT")
    )
    status: Mapped[OrderStatus] = mapped_column(
        _pg_enum(OrderStatus, "order_status"), default=OrderStatus.pending
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(_pg_enum(PaymentMethod, "payment_method"))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        _pg_enum(PaymentStatus, "payment_status"), default=PaymentStatus.unpaid
    )
    locale: Mapped[str] = mapped_column(String(2), default="en")

    # Shipping details as entered for this order
    ship_full_name: Mapped[str] = mapped_column(String(120))
    ship_phone: Mapped[str] = mapped_column(String(11))
    ship_email: Mapped[str | None] = mapped_column(String(254))
    ship_governorate: Mapped[str] = mapped_column(String(40))
    ship_address: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    subtotal_piasters: Mapped[int] = mapped_column(Integer)
    shipping_piasters: Mapped[int] = mapped_column(Integer)
    total_piasters: Mapped[int] = mapped_column(Integer)
    refunded_piasters: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    paymob_intention_id: Mapped[str | None] = mapped_column(String(120))
    paymob_order_id: Mapped[str | None] = mapped_column(String(64))
    paymob_client_secret: Mapped[str | None] = mapped_column(String(255))
    payment_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Id of the successful Paymob transaction (needed for refunds)
    paymob_txn_id: Mapped[str | None] = mapped_column(String(64))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bosta_delivery_id: Mapped[str | None] = mapped_column(String(64))
    bosta_tracking_number: Mapped[str | None] = mapped_column(String(64))

    stock_restored: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.position"
    )
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.created_at"
    )


class OrderItem(UUIDPk, Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL")
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Copies taken at purchase time
    product_name_en: Mapped[str] = mapped_column(String(160))
    product_name_ar: Mapped[str] = mapped_column(String(160))
    variant_label_en: Mapped[str] = mapped_column(String(120), default="")
    variant_label_ar: Mapped[str] = mapped_column(String(120), default="")
    sku: Mapped[str] = mapped_column(String(64))
    image_url: Mapped[str | None] = mapped_column(Text)
    unit_price_piasters: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")

    @property
    def line_total_piasters(self) -> int:
        return self.unit_price_piasters * self.quantity


class OrderEvent(UUIDPk, Base):
    """Audit trail: who changed what, when."""

    __tablename__ = "order_events"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    # created | status | payment | refund | shipment | note
    kind: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    # "system", "paymob", "customer" or "admin:<username>"
    actor: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="events")


class PaymentTransaction(UUIDPk, Base):
    """Every Paymob transaction seen, keyed by Paymob txn id (idempotency)."""

    __tablename__ = "payment_transactions"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    provider_txn_id: Mapped[str] = mapped_column(String(64), unique=True)
    success: Mapped[bool] = mapped_column(Boolean)
    is_refund: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    amount_piasters: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EGP")
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
