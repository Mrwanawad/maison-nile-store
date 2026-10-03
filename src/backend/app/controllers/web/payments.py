"""Paymob webhook (source of truth) and customer return page."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse, Response

from app.controllers.deps import DB, redirect
from app.core.security import order_token
from app.integrations import paymob
from app.repositories import order_repo
from app.services import notification_service, order_service, payment_service
from app.services.payment_service import Outcome, order_id_from_reference

log = logging.getLogger("app.payments")

router = APIRouter()


@router.post("/webhooks/paymob")
async def paymob_webhook(
    request: Request, db: DB, background: BackgroundTasks, hmac: str | None = Query(None)
) -> Response:
    try:
        body: dict[str, Any] = await request.json()
    except ValueError:
        return JSONResponse({"ok": False}, status_code=400)
    obj = body.get("obj")
    if body.get("type") not in (None, "TRANSACTION") or not isinstance(obj, dict):
        # Other callback types (e.g. card tokens) are not used.
        return JSONResponse({"ok": True})
    if not paymob.verify_callback(obj, hmac):
        log.warning("paymob webhook rejected: bad hmac")
        return JSONResponse({"ok": False}, status_code=401)

    result = await payment_service.apply_transaction(db, paymob.parse_transaction(obj))
    if result.order_id and result.outcome in (Outcome.paid, Outcome.failed, Outcome.needs_refund):
        order = await order_service.get_order(db, result.order_id)
        background.add_task(
            notification_service.after_payment,
            notification_service.snapshot(order),
            result.outcome.value,
        )
    return JSONResponse({"ok": True})


@router.get("/payments/paymob/return")
async def paymob_return(
    request: Request,
    db: DB,
    background: BackgroundTasks,
    merchant_order_id: str = Query("", max_length=120),
    id: str = Query("", max_length=40),
) -> Response:
    """The customer lands here after Paymob. Redirect params are not trusted;
    if the webhook has not arrived yet we ask Paymob directly (when an API key is set)."""
    order_id = order_id_from_reference(merchant_order_id)
    order = await order_repo.get_order(db, order_id) if order_id else None
    if order is None:
        return redirect("/")
    result = await payment_service.reconcile(db, order, id or None)
    if (
        result
        and result.order_id
        and result.outcome in (Outcome.paid, Outcome.failed, Outcome.needs_refund)
    ):
        fresh = await order_service.get_order(db, order.id)
        background.add_task(
            notification_service.after_payment,
            notification_service.snapshot(fresh),
            result.outcome.value,
        )
    prefix = "/ar" if order.locale == "ar" else ""
    return redirect(f"{prefix}/order/{order.id}?t={order_token(order.id)}", localize=False)
