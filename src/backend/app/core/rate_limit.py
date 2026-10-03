"""In-memory rate limiter (fine for a single worker). Limits come from `.env`."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    enabled=_settings.app_env != "test",
    headers_enabled=False,
)

CHECKOUT_LIMIT = _settings.rate_limit_checkout
LOGIN_LIMIT = _settings.rate_limit_login
API_LIMIT = _settings.rate_limit_api
