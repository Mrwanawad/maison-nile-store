"""Money helpers. All amounts are integer piasters (1 EGP = 100 piasters)."""

from __future__ import annotations

PIASTERS_PER_EGP = 100


def egp_to_piasters(egp: int | float | str) -> int:
    """Convert a pound amount (as typed by an admin) to piasters, exactly."""
    from decimal import ROUND_HALF_UP, Decimal

    value = Decimal(str(egp)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * PIASTERS_PER_EGP)


def piasters_to_egp_str(piasters: int) -> str:
    """Plain decimal string for forms / APIs, e.g. 125050 -> '1250.50'."""
    sign = "-" if piasters < 0 else ""
    whole, frac = divmod(abs(piasters), PIASTERS_PER_EGP)
    return f"{sign}{whole}" if frac == 0 else f"{sign}{whole}.{frac:02d}"


def format_price(piasters: int, locale: str = "en") -> str:
    """Display format: '1,250 EGP' / '1,250 ج.م'. Shows piasters only when non-zero.

    Western digits are used in Arabic too, as is common on Egyptian storefronts.
    """
    sign = "-" if piasters < 0 else ""
    whole, frac = divmod(abs(piasters), PIASTERS_PER_EGP)
    number = f"{whole:,}" if frac == 0 else f"{whole:,}.{frac:02d}"
    if locale == "ar":
        return f"{sign}{number} ج.م"
    return f"{sign}{number} EGP"


def percent_off(price: int, compare_at: int | None) -> int:
    if not compare_at or compare_at <= price:
        return 0
    return round((compare_at - price) * 100 / compare_at)
