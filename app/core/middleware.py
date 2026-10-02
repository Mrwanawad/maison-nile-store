"""Request id, access logging and security headers (pure ASGI, no body buffering)."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.logging import request_id_var

log = logging.getLogger("app.access")


def _csp() -> str:
    s = get_settings()
    paymob = s.paymob_base_url
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "font-src 'self'",
            "img-src 'self' data: https:",
            "connect-src 'self'",
            f"form-action 'self' {paymob}",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "object-src 'none'",
        ]
    )


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.csp = _csp()
        self.hsts = get_settings().is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = rid
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                if headers.get("content-type", "").startswith("text/html"):
                    headers.setdefault("Content-Security-Policy", self.csp)
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not path.startswith(("/static", "/media", "/health")):
                log.info(
                    "request",
                    extra={
                        "ctx": {
                            "method": scope.get("method"),
                            "path": path,
                            "status": status_holder["code"],
                            "ms": round((time.perf_counter() - started) * 1000, 1),
                        }
                    },
                )
            request_id_var.reset(token)
