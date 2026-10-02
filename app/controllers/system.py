"""Health check and scheduled jobs."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.controllers.deps import DB
from app.core.config import get_settings
from app.core.security import constant_time_equals
from app.repositories import order_repo
from app.services import order_service, payment_service

router = APIRouter()


@router.get("/health", include_in_schema=False)
async def health(db: DB) -> JSONResponse:
    await db.execute(text("SELECT 1"))
    return JSONResponse({"status": "ok", "version": get_settings().app_version})


@router.post("/internal/cleanup", include_in_schema=False)
async def cleanup(db: DB, authorization: str = Header("")) -> JSONResponse:
    expected = f"Bearer {get_settings().internal_cron_token}"
    if not constant_time_equals(authorization, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")

    # Before cancelling, ask Paymob about orders whose callback may have been missed.
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(minutes=get_settings().unpaid_order_timeout_min)
    reconciled = 0
    for order in await order_repo.stale_unpaid_online_orders(db, cutoff):
        await db.rollback()  # release the row lock taken by the query
        result = await payment_service.reconcile(db, order)
        reconciled += int(bool(result))
    await db.rollback()
    cancelled = await order_service.cancel_stale_online_orders(db)
    return JSONResponse({"cancelled": cancelled, "reconciled": reconciled})
