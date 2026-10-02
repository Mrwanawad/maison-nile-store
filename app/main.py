"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.controllers import system
from app.controllers.admin import auth as admin_auth
from app.controllers.admin import catalog as admin_catalog
from app.controllers.admin import orders as admin_orders
from app.controllers.api.v1 import routes as api_v1
from app.controllers.web import cart, checkout, orders, pages, payments, shop
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.errors import register_error_handlers
from app.core.i18n import LocaleMiddleware
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import limiter
from app.integrations.storage import MEDIA_ROOT
from app.services import nav_cache, shipping_service

log = logging.getLogger("app")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _check_config() -> None:
    s = get_settings()
    shipping_service.validate_config(s)
    if s.is_production:
        problems = []
        if s.secret_key.startswith("change-me") or len(s.secret_key) < 32:
            problems.append("SECRET_KEY")
        if s.internal_cron_token.startswith("change-me"):
            problems.append("INTERNAL_CRON_TOKEN")
        if not s.base_url.startswith("https://"):
            problems.append("BASE_URL (must be https)")
        if problems:
            raise RuntimeError(f"Insecure production settings: {', '.join(problems)}")
    if s.paymob_enabled and not s.paymob_ready:
        log.warning("PAYMOB_ENABLED but keys/integration ids missing: online payment hidden")
    if s.bosta_enabled and not s.bosta_ready:
        log.warning("BOSTA_ENABLED but BOSTA_API_KEY missing")


def _init_sentry() -> None:
    dsn = get_settings().sentry_dsn
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk is not installed")
        return
    sentry_sdk.init(dsn=dsn, release=get_settings().app_version, traces_sample_rate=0.0)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("starting", extra={"ctx": {"version": get_settings().app_version}})
    try:
        async with SessionLocal() as db:
            await nav_cache.refresh(db)
    except Exception:
        log.exception("could not load categories at startup")
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging(s.log_level)
    _check_config()
    _init_sentry()

    app = FastAPI(
        title=f"{s.brand_name} API",
        version=s.app_version,
        docs_url=None if s.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if s.is_production else "/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    register_error_handlers(app)

    # Middleware: last added runs first.
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.secret_key,
        session_cookie="session",
        max_age=s.session_max_age_days * 86400,
        same_site="lax",
        https_only=s.is_production,
    )
    app.add_middleware(LocaleMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if s.storage_backend == "local":
        MEDIA_ROOT.mkdir(exist_ok=True)
        app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

    for module in (
        system,
        payments,
        api_v1,
        admin_auth,
        admin_orders,
        admin_catalog,
        shop,
        cart,
        checkout,
        orders,
        pages,
    ):
        app.include_router(module.router)
    return app


app = create_app()
