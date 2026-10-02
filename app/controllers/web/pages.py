"""Static content pages (about, shipping & returns, FAQ...) from Markdown files."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import Response
from markupsafe import Markup

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.i18n import get_locale
from app.core.templates import render

router = APIRouter()

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SLUG = re.compile(r"^[a-z0-9-]{1,40}$")


@lru_cache(maxsize=64)
def _load(locale: str, slug: str) -> tuple[str, Markup] | None:
    path = CONTENT_DIR / locale / f"{slug}.md"
    if not path.is_file():
        path = CONTENT_DIR / "en" / f"{slug}.md"
        if not path.is_file():
            return None
    s = get_settings()
    text = path.read_text("utf-8")
    replacements = {
        "{brand}": s.brand_name_ar if locale == "ar" else s.brand_name,
        "{support_email}": s.support_email,
        "{support_phone}": s.support_phone,
        "{whatsapp}": s.whatsapp_number,
        "{delivery_min}": str(s.delivery_days_min),
        "{delivery_max}": str(s.delivery_days_max),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    title, _, body = text.partition("\n")
    html = markdown.markdown(body, extensions=["extra", "sane_lists"])
    return title.lstrip("# ").strip(), Markup(html)  # content is our own files, not user input


@router.get("/pages/{slug}")
async def content_page(request: Request, slug: str) -> Response:
    if not SLUG.match(slug):
        raise NotFound()
    page = _load(get_locale(), slug)
    if page is None:
        raise NotFound()
    title, body = page
    return render(request, "pages/content.html", {"title": title, "body": body, "slug": slug})
