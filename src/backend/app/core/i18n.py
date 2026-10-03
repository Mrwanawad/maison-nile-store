"""Tiny i18n: English at "/", Arabic under "/ar/...".

`LocaleMiddleware` strips the "/ar" prefix so every route is declared once,
and stores the active locale in a context variable read by `t()` and `url()`.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from starlette.types import ASGIApp, Receive, Scope, Send

Locale = Literal["en", "ar"]
RTL_LOCALES = {"ar"}
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

current_locale: ContextVar[Locale] = ContextVar("current_locale", default="en")


@lru_cache
def catalog(locale: str) -> dict[str, str]:
    data: dict[str, str] = json.loads((_LOCALES_DIR / f"{locale}.json").read_text("utf-8"))
    return data


def t(key: str, /, **params: Any) -> str:
    """Translate `key` into the active locale; falls back to English, then the key."""
    locale = current_locale.get()
    text = catalog(locale).get(key) or catalog("en").get(key) or key
    return text.format(**params) if params else text


def t_in(locale: str, key: str, /, **params: Any) -> str:
    """Translate `key` into a specific locale (e.g. the bilingual home hero)."""
    text = catalog(locale).get(key) or catalog("en").get(key) or key
    return text.format(**params) if params else text


def get_locale() -> Locale:
    return current_locale.get()


def is_rtl() -> bool:
    return current_locale.get() in RTL_LOCALES


def localized(obj: Any, field: str) -> str:
    """Pick `obj.<field>_ar` or `obj.<field>_en` for the active locale (falls back to en)."""
    locale = current_locale.get()
    value: str = getattr(obj, f"{field}_{locale}", "") or getattr(obj, f"{field}_en", "")
    return value


def url(path: str, locale: str | None = None) -> str:
    """Prefix an app path with the locale segment, e.g. url('/p/x') -> '/ar/p/x'."""
    locale = locale or current_locale.get()
    if not path.startswith("/"):
        path = "/" + path
    if locale == "ar":
        return "/ar" if path == "/" else "/ar" + path
    return path


def strip_locale(path: str) -> tuple[Locale, str]:
    if path == "/ar" or path.startswith("/ar/"):
        return "ar", path[3:] or "/"
    return "en", path


class LocaleMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        locale, path = strip_locale(scope["path"])
        scope = dict(scope)
        scope["path"] = path
        scope["raw_path"] = path.encode()
        scope.setdefault("state", {})["locale"] = locale
        token = current_locale.set(locale)
        try:
            await self.app(scope, receive, send)
        finally:
            current_locale.reset(token)
