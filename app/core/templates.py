"""Jinja2 environment shared by all HTML controllers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.core.config import get_settings
from app.core.i18n import get_locale, is_rtl, localized, strip_locale, t, url
from app.core.security import CSRF_FORM_FIELD, csrf_token
from app.services import nav_cache
from app.utils.governorates import BY_CODE, GOVERNORATES
from app.utils.money import format_price, percent_off

CAIRO = ZoneInfo("Africa/Cairo")
_VIEWS = Path(__file__).resolve().parent.parent / "views"
templates = Jinja2Templates(directory=str(_VIEWS))
settings = get_settings()


def _static(path: str) -> str:
    return f"/static/{path}?v={settings.app_version}"


_UNSPLASH = re.compile(r"^https://images\.unsplash\.com/")
SMALL_SUFFIX = "-480.webp"


def _srcset(url: str) -> str:
    """Responsive candidates: Unsplash width params, or our own 480px upload variant."""
    if _UNSPLASH.match(url):
        base = re.sub(r"([?&])w=\d+", lambda m: m.group(1) + "w={w}", url)
        base = re.sub(r"([?&])h=\d+", lambda m: m.group(1) + "h={h}", base)
        if "{w}" not in base:
            return ""
        return ", ".join(
            f"{base.format(w=w, h=round(w * 1.25))} {w}w" for w in (360, 540, 720, 1000)
        )
    if url.endswith(".webp") and "/products/" in url and not url.endswith(SMALL_SUFFIX):
        return f"{url[: -len('.webp')]}{SMALL_SUFFIX} 480w, {url} 1280w"
    return ""


def _price(piasters: int) -> str:
    return format_price(piasters, get_locale())


def _csrf_input(request: Request) -> Markup:
    return Markup(f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{csrf_token(request)}">')


def _hx_headers(request: Request) -> str:
    return json.dumps({"X-CSRF-Token": csrf_token(request)})


def _switch_locale_url(request: Request) -> str:
    """Same page in the other language."""
    _, path = strip_locale(request.url.path)
    target = "en" if get_locale() == "ar" else "ar"
    query = f"?{request.url.query}" if request.url.query else ""
    return url(path, target) + query


def _whatsapp_link(message: str | None = None) -> str:
    text = quote(message or settings.whatsapp_default_message)
    return f"https://wa.me/{settings.whatsapp_number}?text={text}"


def _cart_count(request: Request) -> int:
    raw = request.session.get("cart")
    if not isinstance(raw, dict):
        return 0
    return sum(q for q in raw.values() if isinstance(q, int) and q > 0)


def _flash(request: Request) -> dict[str, str] | None:
    value = request.session.pop("flash", None)
    return value if isinstance(value, dict) else None


def _governorate_name(code: str) -> str:
    gov = BY_CODE.get(code)
    return gov.name(get_locale()) if gov else code


def _brand_name() -> str:
    return settings.brand_name_ar if get_locale() == "ar" else settings.brand_name


def _tagline() -> str:
    return settings.brand_tagline_ar if get_locale() == "ar" else settings.brand_tagline_en


env = templates.env
env.globals.update(
    settings=settings,
    t=t,
    url=url,
    static=_static,
    price=_price,
    srcset=_srcset,
    percent_off=percent_off,
    localized=localized,
    locale=get_locale,
    is_rtl=is_rtl,
    csrf_input=_csrf_input,
    csrf_token=csrf_token,
    hx_headers=_hx_headers,
    switch_locale_url=_switch_locale_url,
    whatsapp_link=_whatsapp_link,
    brand_name=_brand_name,
    tagline=_tagline,
    governorates=GOVERNORATES,
    cart_count=_cart_count,
    nav_categories=nav_cache.nav_categories,
    pop_flash=_flash,
    cairo_tz=lambda: CAIRO,
    governorate_name=_governorate_name,
)
env.trim_blocks = True
env.lstrip_blocks = True


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    return templates.TemplateResponse(
        request, template, context or {}, status_code=status_code, headers=headers
    )
