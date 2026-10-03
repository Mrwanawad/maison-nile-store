"""Shipping fees per governorate, configured in `.env`."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.utils import governorates
from app.utils.money import egp_to_piasters


@dataclass(frozen=True, slots=True)
class ShippingRate:
    code: str
    name_en: str
    name_ar: str
    fee_piasters: int


def validate_config(settings: Settings | None = None) -> None:
    """Fail fast at startup if SHIPPING_FEE_OVERRIDES names an unknown governorate."""
    settings = settings or get_settings()
    unknown = set(settings.shipping_overrides_egp) - set(governorates.BY_CODE)
    if unknown:
        raise RuntimeError(
            f"SHIPPING_FEE_OVERRIDES has unknown governorate codes: {sorted(unknown)}. "
            f"Valid codes: {', '.join(governorates.BY_CODE)}"
        )


def fee_for(code: str) -> int:
    """Shipping fee in piasters for a governorate code."""
    if code not in governorates.BY_CODE:
        raise AppError("checkout.error.governorate")
    settings = get_settings()
    egp = settings.shipping_overrides_egp.get(code, settings.shipping_default_fee_egp)
    return egp_to_piasters(egp)


def all_rates() -> list[ShippingRate]:
    return [
        ShippingRate(g.code, g.name_en, g.name_ar, fee_for(g.code))
        for g in governorates.GOVERNORATES
    ]


def lowest_fee() -> int:
    return min(r.fee_piasters for r in all_rates())
