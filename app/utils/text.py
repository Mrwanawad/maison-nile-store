from __future__ import annotations

import re
import unicodedata


def slugify(value: str, max_length: int = 120) -> str:
    """ASCII slug. Arabic-only input falls back to an empty string (caller adds a suffix)."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def clean_text(value: str | None, max_length: int | None = None) -> str:
    """Collapse whitespace and strip control characters from user input."""
    if not value:
        return ""
    value = "".join(ch for ch in value if ch == "\n" or unicodedata.category(ch)[0] != "C")
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:max_length] if max_length else value
