"""Test setup: a dedicated Postgres database, migrated with Alembic, reset per test.

Needs the docker compose `db` service (or TEST_DATABASE_URL pointing at Postgres 15+).
"""

from __future__ import annotations

import os

# Must be set before any `app` import (settings and engine are created at import time).
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://store:store@localhost:5432/store_test"
)
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DB_URL,
        "DATABASE_USE_POOLER": "false",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "INTERNAL_CRON_TOKEN": "test-cron-token",
        "PAYMOB_ENABLED": "true",
        "PAYMOB_SECRET_KEY": "sk_test",
        "PAYMOB_PUBLIC_KEY": "pk_test",
        "PAYMOB_HMAC_SECRET": "hmac_test_secret",
        "PAYMOB_INTEGRATION_IDS": "12345",
        "PAYMOB_API_KEY": "",
        "TELEGRAM_BOT_TOKEN": "",
        "EMAIL_PROVIDER": "none",
        "BOSTA_ENABLED": "false",
        "COD_ENABLED": "true",
        "COD_MAX_ORDER_EGP": "5000",
        "COD_MAX_OPEN_ORDERS_PER_PHONE": "2",
        "SHIPPING_DEFAULT_FEE_EGP": "100",
        "SHIPPING_FEE_OVERRIDES": "alexandria:50",
        "STORAGE_BACKEND": "local",
    }
)

import asyncio  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Category,
    Product,
    ProductColor,
    ProductVariant,
    Size,
)

TABLES = (
    "payment_transactions, order_events, order_items, orders, customers, phone_blocklist, "
    "product_images, product_variants, product_colors, products, categories, sizes, admin_users"
)


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Create the test database (if needed) and run migrations once."""
    dsn = _plain_dsn(TEST_DB_URL)
    db_name = dsn.rsplit("/", 1)[1]
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"

    async def create() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", db_name)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()

    asyncio.run(create())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": TEST_DB_URL},
        capture_output=True,
    )


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@dataclass
class Catalog:
    product: Product
    tee_black_m: ProductVariant
    tee_black_l: ProductVariant
    single: ProductVariant  # one-size product


@pytest.fixture
async def catalog(db: AsyncSession) -> Catalog:
    cat = Category(slug="tops", name_en="Tops", name_ar="بلوزات")
    m = Size(code="M", label_en="M", label_ar="M", size_group="apparel", sort_order=1)
    l_ = Size(code="L", label_en="L", label_ar="L", size_group="apparel", sort_order=2)
    db.add_all([cat, m, l_])
    await db.flush()
    tee = Product(
        slug="tee", name_en="Tee", name_ar="تيشيرت", category_id=cat.id, price_piasters=45000
    )
    bag = Product(slug="bag", name_en="Bag", name_ar="شنطة", price_piasters=240000)
    db.add_all([tee, bag])
    await db.flush()
    black = ProductColor(product_id=tee.id, name_en="Black", name_ar="أسود", hex="#000000")
    db.add(black)
    await db.flush()
    v_m = ProductVariant(
        product_id=tee.id, color_id=black.id, size_id=m.id, sku="TEE-BLK-M", stock=5
    )
    v_l = ProductVariant(
        product_id=tee.id, color_id=black.id, size_id=l_.id, sku="TEE-BLK-L", stock=1
    )
    single = ProductVariant(product_id=bag.id, sku="BAG", stock=3)
    db.add_all([v_m, v_l, single])
    await db.commit()
    # Detach so a rollback inside the code under test can't expire these test handles.
    db.expunge_all()
    return Catalog(tee, v_m, v_l, single)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


async def csrf(client: httpx.AsyncClient, path: str = "/track") -> str:
    """Load a page to obtain the session cookie + CSRF token."""
    html = (await client.get(path)).text
    match = CSRF_RE.search(html)
    assert match, f"no csrf token on {path}"
    return match.group(1)


@pytest.fixture
async def admin_client(
    client: httpx.AsyncClient, db: AsyncSession
) -> tuple[httpx.AsyncClient, str]:
    """A client signed in as an admin, plus a CSRF token for its session."""
    from app.core.security import hash_password
    from app.models import AdminUser

    db.add(
        AdminUser(username="owner", display_name="Owner", password_hash=hash_password("pw-1234567"))
    )
    await db.commit()
    token = await csrf(client, "/admin/login")
    r = await client.post(
        "/admin/login", data={"csrf_token": token, "username": "owner", "password": "pw-1234567"}
    )
    assert r.status_code == 303
    return client, await csrf(client, "/admin/blocklist")


async def flash(client: httpx.AsyncClient) -> str:
    """The flash message shown after an admin redirect."""
    html = (await client.get("/admin/blocklist")).text
    match = re.search(r'<template id="flash" data-kind="(\w+)">([^<]*)', html)
    return f"{match.group(1)}: {match.group(2)}" if match else ""


@pytest.fixture
def media_tmp(tmp_path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Local image storage writes into a temp dir instead of ./media."""
    from app.integrations import storage

    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path)
    return tmp_path


class FakeHTTP:
    """Intercepts outbound httpx calls made by integrations (not the ASGI test client)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, httpx.Response] = {}

    def on(self, url_part: str, status: int = 200, json: object | None = None) -> None:
        self.routes[url_part] = httpx.Response(status, json=json if json is not None else {})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for part, response in self.routes.items():
            if part in str(request.url):
                return httpx.Response(
                    response.status_code,
                    content=response.content,
                    headers={"content-type": "application/json"},
                )
        return httpx.Response(404, json={"detail": "no fake route"})

    def sent(self, url_part: str) -> list[dict[str, object]]:
        import json as _json

        out = []
        for r in self.requests:
            if url_part in str(r.url) and r.headers.get("content-type", "").startswith(
                "application/json"
            ):
                out.append(_json.loads(r.content or b"{}"))
        return out


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> FakeHTTP:
    fake = FakeHTTP()
    real = httpx.AsyncClient

    class Patched(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs.setdefault("transport", httpx.MockTransport(fake.handler))
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    return fake
