"""Application settings, loaded from environment variables / `.env`.

Every business-tunable value lives here so nothing is hard-coded elsewhere.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "brand-store"
    app_version: str = "0.1.0"
    app_env: Literal["development", "production", "test"] = "development"
    base_url: str = "http://localhost:8000"
    secret_key: str = "change-me-to-a-long-random-string"

    # Brand
    brand_name: str = "Maison Nile"
    brand_name_ar: str = "ميزون نايل"
    brand_tagline_en: str = "Everyday pieces, made in Egypt."
    brand_tagline_ar: str = "قطع يومية، صُنعت في مصر."
    brand_logo_url: str = ""
    brand_favicon_url: str = "/static/img/favicon.svg"
    brand_accent_color: str = "#B4532A"
    brand_accent_hover_color: str = "#8E3F1E"
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
    email_from_name: str = "Maison Nile"

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
