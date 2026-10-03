"""Async SQLAlchemy engine and session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def _engine_kwargs() -> dict[str, Any]:
    settings = get_settings()
    if settings.database_use_pooler:
        # Transaction-mode poolers (Supabase/PgBouncer) cannot keep prepared
        # statements between transactions: disable caching and use unique names.
        return {
            "poolclass": NullPool,
            "connect_args": {
                "statement_cache_size": 0,
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
            },
        }
    return {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True}


engine = create_async_engine(get_settings().database_url, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
