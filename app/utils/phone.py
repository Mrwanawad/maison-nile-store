"""Egyptian mobile number normalization."""

from __future__ import annotations

import re

_EG_MOBILE = re.compile(r"^01[0125]\d{8}$")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_eg_mobile(raw: str) -> str | None:
    """Return the number as 01XXXXXXXXX, or None if it is not a valid Egyptian mobile.

    Accepts spaces/dashes, Arabic-Indic digits and +20 / 0020 / 20 prefixes.
    """
    digits = re.sub(r"\D", "", raw.translate(_AR_DIGITS))
    if digits.startswith("0020"):
        digits = digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits
    return digits if _EG_MOBILE.match(digits) else None
