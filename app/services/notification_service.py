"""Owner alerts (Telegram) and customer emails, run as background tasks.

Functions take a plain snapshot, not ORM objects, because they run after the
request's DB session is closed. They never raise.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.i18n import current_locale, t
from app.core.security import order_token
from app.integrations import email, telegram
from app.models import Order
from app.utils import governorates
from app.utils.money import format_price

log = logging.getLogger("app.notify")


@dataclass(frozen=True, slots=True)
class LineSnapshot:
    name: str
    label: str
    quantity: int
    line_total: int


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    id: str
    number: int
    locale: str
    name: str
    phone: str
    email: str | None
    governorate: str
    address: str
    notes: str | None
    payment_method: str
    subtotal: int
    shipping: int
    total: int
    lines: list[LineSnapshot] = field(default_factory=list)

    @property
    def link(self) -> str:
        prefix = "/ar" if self.locale == "ar" else ""
        return f"{get_settings().base_url}{prefix}/order/{self.id}?t={order_token(self.id)}"

    @property
    def admin_link(self) -> str:
        return f"{get_settings().base_url}/admin/orders/{self.id}"


def snapshot(order: Order) -> OrderSnapshot:
    ar = order.locale == "ar"
    return OrderSnapshot(
        id=str(order.id),
        number=order.order_number,
        locale=order.locale,
        name=order.ship_full_name,
        phone=order.ship_phone,
        email=order.ship_email,
        governorate=order.ship_governorate,
        address=order.ship_address,
        notes=order.notes,
        payment_method=order.payment_method.value,
        subtotal=order.subtotal_piasters,
        shipping=order.shipping_piasters,
        total=order.total_piasters,
        lines=[
            LineSnapshot(
                name=i.product_name_ar if ar else i.product_name_en,
                label=i.variant_label_ar if ar else i.variant_label_en,
                quantity=i.quantity,
                line_total=i.line_total_piasters,
            )
            for i in order.items
        ],
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


async def owner_new_order(o: OrderSnapshot) -> None:
    gov = governorates.get(o.governorate)
    method = (
        "Cash on delivery" if o.payment_method == "cod" else "Online (Paymob) - awaiting payment"
    )
    items = "\n".join(
        f"• {_e(line.name)}{' (' + _e(line.label) + ')' if line.label else ''} × {line.quantity}"
        for line in o.lines
    )
    text = (
        f"<b>New order #{o.number}</b>\n"
        f"{_e(o.name)} · <code>{o.phone}</code>\n"
        f"{_e(gov.name_en if gov else o.governorate)} · {_e(o.address)}\n\n"
        f"{items}\n\n"
        f"Total: <b>{format_price(o.total)}</b> ({_e(method)})\n"
        + (f"Notes: {_e(o.notes)}\n" if o.notes else "")
        + f'<a href="{o.admin_link}">Open in admin</a>'
    )
    await telegram.send(text)


async def owner_payment(o: OrderSnapshot, outcome: str) -> None:
    labels = {
        "paid": "Payment received",
        "failed": "Payment failed",
        "needs_refund": "ACTION NEEDED: paid but cannot fulfil (refund)",
    }
    text = (
        f"<b>{labels.get(outcome, outcome)} · #{o.number}</b>\n"
        f"{format_price(o.total)} · {_e(o.name)}\n"
        f'<a href="{o.admin_link}">Open in admin</a>'
    )
    await telegram.send(text)


async def owner_low_stock(rows: list[tuple[str, int]]) -> None:
    if not rows:
        return
    body = "\n".join(f"• {_e(name)}: {stock} left" for name, stock in rows)
    await telegram.send(f"<b>Low stock</b>\n{body}")


async def customer_confirmation(o: OrderSnapshot) -> None:
    if not o.email:
        return
    from app.core.templates import templates

    token = current_locale.set("ar" if o.locale == "ar" else "en")
    try:
        context = {"o": o}
        html_body = templates.get_template("emails/order_confirmation.html").render(context)
        text_body = templates.get_template("emails/order_confirmation.txt").render(context)
        subject = t("email.subject", number=o.number)
    finally:
        current_locale.reset(token)
    await email.send(to=o.email, subject=subject, html=html_body, text=text_body)


async def after_order_placed(o: OrderSnapshot, low_stock: list[tuple[str, int]]) -> None:
    await owner_new_order(o)
    await owner_low_stock(low_stock)
    if o.payment_method == "cod":
        await customer_confirmation(o)


async def after_payment(o: OrderSnapshot, outcome: str) -> None:
    await owner_payment(o, outcome)
    if outcome == "paid":
        await customer_confirmation(o)
