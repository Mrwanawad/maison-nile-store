"""Application settings, loaded from environment variables / `.env`.

Every business-tunable value lives here so nothing is hard-coded elsewhere.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


_DEFAULT_BASE_URL = "http://localhost:8000"
_SYNC_SCHEMES = ("postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg")


def normalize_database_url(url: str) -> str:
    """Accept a URL copied as-is from Supabase/Render and make it asyncpg-ready.

    - `postgres://` / `postgresql://` -> `postgresql+asyncpg://`
    - libpq's `sslmode=` -> asyncpg's `ssl=`; drop `pgbouncer=` (a Prisma-only flag)
    """
    parts = urlsplit(url.strip())
    scheme = "postgresql+asyncpg" if parts.scheme in _SYNC_SCHEMES else parts.scheme
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "pgbouncer":
            continue
        query.append(("ssl" if key == "sslmode" else key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "brand-store"
    app_version: str = "0.1.0"
    app_env: Literal["development", "production", "test"] = "development"
    base_url: str = _DEFAULT_BASE_URL
    # Set by Render on every service; used as BASE_URL when BASE_URL is not set.
    render_external_url: str = ""
    secret_key: str = "change-me-to-a-long-random-string"

    # Brand
    brand_name: str = "SYN"
    brand_name_ar: str = "سين"
    brand_tagline_en: str = "Made together, in Egypt."
    brand_tagline_ar: str = "صُنعت معًا، في مصر."
    brand_logo_url: str = ""
    brand_favicon_url: str = "/static/img/favicon.svg"
    # Tint = interactive colour only (primary action, links, focus). Light and dark
    # appearances each need their own value to keep 4.5:1 contrast.
    brand_accent_color: str = "#006A73"
    brand_accent_hover_color: str = "#00535A"
    brand_accent_dark_color: str = "#5CC8CF"
    hero_image_url: str = ""

    # Contact
    whatsapp_number: str = ""
    whatsapp_default_message: str = "Hi! I have a question about your products."
    instagram_url: str = ""
    facebook_url: str = ""
    tiktok_url: str = ""
    support_email: str = ""
    support_phone: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://store:store@localhost:5432/store"
    database_use_pooler: bool = False

    # First-boot bootstrap (runs after migrations on every start; both steps are idempotent)
    seed_demo_data: bool = False
    admin_bootstrap_username: str = ""
    admin_bootstrap_password: str = ""
    admin_bootstrap_name: str = "Owner"

    # Storage
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "products"
    image_max_size_px: int = 1600
    image_quality: int = Field(80, ge=1, le=100)

    # Shipping
    shipping_default_fee_egp: int = Field(100, ge=0)
    shipping_fee_overrides: str = "alexandria:50"
    delivery_days_min: int = 2
    delivery_days_max: int = 5
    exchange_days: int = Field(14, ge=0)

    # Checkout / COD
    cod_enabled: bool = True
    cod_max_order_egp: int = Field(5000, ge=0)
    cod_max_open_orders_per_phone: int = Field(2, ge=0)
    max_qty_per_line: int = Field(10, ge=1)
    low_stock_threshold: int = Field(3, ge=0)
    unpaid_order_timeout_min: int = Field(45, ge=5)

    # Paymob
    paymob_enabled: bool = False
    paymob_secret_key: str = ""
    paymob_public_key: str = ""
    paymob_hmac_secret: str = ""
    paymob_api_key: str = ""
    paymob_integration_ids: str = ""
    paymob_base_url: str = "https://accept.paymob.com"
    paymob_method_label_en: str = "Pay online (Apple Pay)"
    paymob_method_label_ar: str = "الدفع أونلاين (Apple Pay)"

    # Bosta
    bosta_enabled: bool = False
    bosta_api_key: str = ""
    bosta_base_url: str = "https://stg-app.bosta.co/api/v2"
    bosta_pickup_location_id: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""

    # Email
    email_provider: Literal["none", "brevo", "resend"] = "none"
    email_api_key: str = ""
    email_from: str = "orders@example.com"
    email_from_name: str = "SYN"

    # OTP
    otp_provider: Literal["none"] = "none"

    # Security / limits
    rate_limit_checkout: str = "10/minute"
    rate_limit_login: str = "5/minute"
    rate_limit_api: str = "60/minute"
    internal_cron_token: str = "change-me-too"
    session_max_age_days: int = 14

    # Observability
    log_level: str = "INFO"
    sentry_dsn: str = ""

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _derive_defaults(self) -> Self:
        if self.base_url == _DEFAULT_BASE_URL and self.render_external_url:
            self.base_url = self.render_external_url.rstrip("/")
        parts = urlsplit(self.database_url)
        if (parts.hostname or "").endswith(".pooler.supabase.com") and parts.port == 6543:
            # Supabase transaction-mode pooler: prepared statements must not be cached.
            self.database_use_pooler = True
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def paymob_integration_id_list(self) -> list[int]:
        return [int(x) for x in _csv(self.paymob_integration_ids)]

    @property
    def telegram_chat_id_list(self) -> list[str]:
        return _csv(self.telegram_chat_ids)

    @property
    def shipping_overrides_egp(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for pair in _csv(self.shipping_fee_overrides):
            code, _, fee = pair.partition(":")
            result[code.strip().lower()] = int(fee)
        return result

    @property
    def paymob_ready(self) -> bool:
        return bool(
            self.paymob_enabled
            and self.paymob_secret_key
            and self.paymob_public_key
            and self.paymob_hmac_secret
            and self.paymob_integration_id_list
        )

    @property
    def bosta_ready(self) -> bool:
        return bool(self.bosta_enabled and self.bosta_api_key)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id_list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
