"""Domain errors and global exception handlers (HTML, HTMX and JSON aware)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.i18n import t

log = logging.getLogger("app.errors")


class AppError(Exception):
    """A business error that is safe to show to the user.

    `key` is an i18n message key; `params` fill its placeholders.
    """

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, key: str, status_code: int | None = None, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params
        if status_code is not None:
            self.status_code = status_code

    @property
    def message(self) -> str:
        return t(self.key, **self.params)


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, key: str = "error.not_found", **params: Any) -> None:
        super().__init__(key, **params)


class OutOfStock(AppError):
    status_code = status.HTTP_409_CONFLICT


class IntegrationError(Exception):
    """A third-party call failed (Paymob, Bosta, ...). Logged, shown generically."""


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def toast_headers(message: str, kind: str = "error") -> dict[str, str]:
    return {
        "HX-Trigger": json.dumps({"toast": {"message": message, "kind": kind}}, ensure_ascii=True),
        "HX-Reswap": "none",
    }


def _render_error_page(request: Request, status_code: int, message: str) -> Response:
    from app.core.templates import templates

    template = "pages/404.html" if status_code == 404 else "pages/error.html"
    return templates.TemplateResponse(
        request, template, {"status_code": status_code, "message": message}, status_code=status_code
    )


def _respond(request: Request, status_code: int, code: str, message: str) -> Response:
    if (
        request.url.path.startswith("/admin/")
        and request.method == "POST"
        and not is_htmx(request)
        and status_code < 500
        and "session" in request.scope
    ):
        # Admin forms: show the problem on the page the admin came from.
        request.session["flash"] = {"message": message, "kind": "error"}
        referer = urlsplit(request.headers.get("referer", ""))
        back = referer.path if referer.path.startswith("/admin") else "/admin"
        if referer.query:
            back += "?" + referer.query
        return RedirectResponse(back, status_code=303)
    if is_api(request):
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)
    if is_htmx(request):
        return Response(status_code=status_code, headers=toast_headers(message))
    return _render_error_page(request, status_code, message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> Response:
        return _respond(request, exc.status_code, exc.key, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404:
            return _respond(request, 404, "not_found", t("error.not_found"))
        if exc.status_code == 403 and exc.detail == "csrf":
            return _respond(request, 403, "csrf", t("error.csrf"))
        if exc.status_code in (401, 303, 302) and exc.headers:
            return Response(status_code=exc.status_code, headers=exc.headers)
        message = exc.detail if isinstance(exc.detail, str) else t("error.generic")
        return _respond(request, exc.status_code, "http_error", message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if is_api(request):
            errors = [
                {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                for e in exc.errors()
            ]
            return JSONResponse(
                {
                    "error": {
                        "code": "validation",
                        "message": t("error.validation"),
                        "fields": errors,
                    }
                },
                status_code=422,
            )
        return _respond(request, 422, "validation", t("error.validation"))

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> Response:
        log.warning("rate limited", extra={"ctx": {"path": request.url.path}})
        response = _respond(request, 429, "rate_limited", t("error.rate_limited"))
        response.headers["Retry-After"] = "60"
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        log.exception("unhandled error", extra={"ctx": {"path": request.url.path}})
        return _respond(request, 500, "server_error", t("error.server"))
