"""SMS one-time codes for cash-on-delivery verification.

Not active (OTP_PROVIDER=none). To enable later, implement `OtpProvider` for a
paid Egyptian SMS gateway, return it from `get_provider()`, and call it from the
checkout flow before `place_order` for COD orders.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings


class OtpProvider(Protocol):
    async def send_code(self, phone: str, code: str) -> None: ...


def get_provider() -> OtpProvider | None:
    if get_settings().otp_provider == "none":
        return None
    raise NotImplementedError("No SMS provider configured")
