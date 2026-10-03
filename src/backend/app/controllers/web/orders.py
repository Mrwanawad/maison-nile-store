"""Order confirmation (signed link), payment retry, and order tracking."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response

from app.controllers.deps import DB, redirect
from app.core.errors import AppError, NotFound
from app.core.rate_limit import CHECKOUT_LIMIT, limiter
from app.core.security import order_token, verify_csrf, verify_order_token
from app.core.templates import render
from app.integrations import bosta
from app.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.repositories import order_repo
from app.services import order_service, payment_service
from app.utils.phone import normalize_eg_mobile

router = APIRouter()


async def _authorized_order(db: DB, order_id: uuid.UUID, token: str | None) -> Order:
    if not verify_order_token(order_id, token):
        raise NotFound()
    return await order_service.get_order(db, order_id)


def _awaiting_payment(order: Order) -> bool:
    return (
        order.payment_method == PaymentMethod.paymob
        and order.status == OrderStatus.pending
        and order.payment_status in (PaymentStatus.unpaid, PaymentStatus.failed)
    )


def _context(order: Order, token: str) -> dict[str, object]:
    return {
        "order": order,
        "token": token,
        "awaiting_payment": _awaiting_payment(order),
        "tracking_url": bosta.tracking_url(order.bosta_tracking_number)
        if order.bosta_tracking_number
        else None,
    }


@router.get("/order/{order_id}")
async def order_page(
    request: Request,
    db: DB,
    order_id: uuid.UUID,
    t: str | None = Query(None, max_length=64),
    pay_error: int = 0,
) -> Response:
    order = await _authorized_order(db, order_id, t)
    context = _context(order, t or "")
    context["pay_error"] = bool(pay_error)
    return render(request, "pages/order.html", context)


@router.get("/order/{order_id}/status")
async def order_status(
    request: Request, db: DB, order_id: uuid.UUID, t: str | None = Query(None)
) -> Response:
    """HTMX polling while an online payment is being confirmed."""
    order = await _authorized_order(db, order_id, t)
    return render(request, "partials/order_status.html", _context(order, t or ""))


@router.post("/order/{order_id}/pay", dependencies=[Depends(verify_csrf)])
@limiter.limit(CHECKOUT_LIMIT)
async def retry_payment(
    request: Request, db: DB, order_id: uuid.UUID, t: str = Form(...)
) -> Response:
    order = await _authorized_order(db, order_id, t)
    if not _awaiting_payment(order):
        return redirect(f"/order/{order.id}?t={t}")
    try:
        checkout_url = await payment_service.start_checkout(db, order.id)
    except AppError:
        return redirect(f"/order/{order.id}?t={t}&pay_error=1")
    return RedirectResponse(checkout_url, status_code=303)


@router.get("/track")
async def track_form(request: Request) -> Response:
    return render(request, "pages/track.html", {"values": {}, "error": None})


@router.post("/track", dependencies=[Depends(verify_csrf)])
@limiter.limit(CHECKOUT_LIMIT)
async def track_lookup(
    request: Request,
    db: DB,
    order_number: str = Form("", max_length=20),
    phone: str = Form("", max_length=30),
) -> Response:
    number = order_number.strip().lstrip("#")
    normalized = normalize_eg_mobile(phone)
    order = None
    if number.isdigit() and normalized:
        order = await order_repo.get_order_by_number(db, int(number))
    if order is None or order.ship_phone != normalized:
        return render(
            request,
            "pages/track.html",
            {"values": {"order_number": order_number, "phone": phone}, "error": "track.not_found"},
            status_code=404,
        )
    return redirect(f"/order/{order.id}?t={order_token(order.id)}")
