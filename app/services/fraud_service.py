"""Cash-on-delivery abuse protection. All limits come from `.env`.

SMS one-time codes are not active yet (`OTP_PROVIDER=none`); see
`app/integrations/sms` for the provider interface to plug in later.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.repositories import order_repo

HONEYPOT_FIELD = "website"


async def check_cod_customer(db: AsyncSession, phone: str) -> None:
    if await order_repo.is_phone_blocked(db, phone):
        raise AppError("checkout.error.cod_blocked")
    limit = get_settings().cod_max_open_orders_per_phone
    if limit and await order_repo.count_open_cod_orders(db, phone) >= limit:
        raise AppError("checkout.error.cod_open_orders")


def is_bot(honeypot_value: str | None) -> bool:
    """Bots fill every field, including the hidden one humans never see."""
    return bool(honeypot_value and honeypot_value.strip())
