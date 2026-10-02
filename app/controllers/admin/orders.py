"""Admin dashboard and order management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import Response

from app.controllers.deps import DB, redirect
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import verify_csrf
from app.core.templates import render
from app.integrations import bosta
from app.models import AdminUser, OrderStatus, PaymentStatus
from app.repositories import catalog_repo, order_repo
from app.services import order_service, payment_service, shipment_service
from app.services.admin_auth_service import actor, current_admin
from app.services.order_service import TRANSITIONS
from app.utils.money import egp_to_piasters

Admin = Annotated[AdminUser, Depends(current_admin)]

router = APIRouter(prefix="/admin", dependencies=[Depends(verify_csrf), Depends(current_admin)])

PAGE = 50
CAIRO = ZoneInfo("Africa/Cairo")


def _flash(request: Request, message: str, kind: str = "success") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


@router.get("")
async def dashboard(request: Request, db: DB, admin: Admin) -> Response:
    now = datetime.now(UTC)
    start_today = now.astimezone(CAIRO).replace(hour=0, minute=0, second=0, microsecond=0)
    recent, _ = await order_repo.list_orders(db, limit=8)
    return render(
        request,
        "admin/dashboard.html",
        {
            "admin": admin,
            "today": await order_repo.stats_since(db, start_today),
            "week": await order_repo.stats_since(db, now - timedelta(days=7)),
            "by_status": await order_repo.count_by_status(db),
            "recent": recent,
            "low_stock": await catalog_repo.low_stock_variants(
                db, get_settings().low_stock_threshold
            ),
        },
    )


@router.get("/orders")
async def orders_list(
    request: Request,
    db: DB,
    admin: Admin,
    status: str = Query("", max_length=20),
    payment: str = Query("", max_length=20),
    q: str | None = Query(None, max_length=60),
    page: int = Query(1, ge=1),
) -> Response:
    status_filter = OrderStatus(status) if status in OrderStatus.__members__ else None
    payment_filter = PaymentStatus(payment) if payment in PaymentStatus.__members__ else None
    orders, total = await order_repo.list_orders(
        db,
        status=status_filter,
        payment_status=payment_filter,
        query=q,
        limit=PAGE,
        offset=(page - 1) * PAGE,
    )
    context = {
        "admin": admin,
        "orders": orders,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // PAGE)),
        "filters": {
            "status": status_filter.value if status_filter else "",
            "payment": payment_filter.value if payment_filter else "",
            "q": q or "",
        },
        "statuses": list(OrderStatus),
        "payment_statuses": list(PaymentStatus),
    }
    template = (
        "admin/partials/orders_table.html"
        if request.headers.get("hx-request")
        else "admin/orders.html"
    )
    return render(request, template, context)


@router.get("/orders/{order_id}")
async def order_detail(request: Request, db: DB, admin: Admin, order_id: uuid.UUID) -> Response:
    order = await order_service.get_order(db, order_id)
    return render(
        request,
        "admin/order_detail.html",
        {
            "admin": admin,
            "order": order,
            "next_statuses": sorted(
                TRANSITIONS[order.status], key=lambda s: list(OrderStatus).index(s)
            ),
            "bosta_ready": get_settings().bosta_ready,
            "paymob_ready": get_settings().paymob_ready,
            "tracking_url": bosta.tracking_url(order.bosta_tracking_number)
            if order.bosta_tracking_number
            else None,
            "refundable": order.total_piasters - order.refunded_piasters,
        },
    )


@router.post("/orders/{order_id}/status")
async def change_status(
    request: Request,
    db: DB,
    admin: Admin,
    order_id: uuid.UUID,
    status: OrderStatus = Form(...),
    note: str = Form("", max_length=500),
) -> Response:
    await order_service.change_status(
        db, order_id, status, actor=actor(admin), note=note.strip() or None
    )
    msg = f"Status changed to {status.value}."
    if status == OrderStatus.cancelled:
        msg += " Stock restored."
    _flash(request, msg)
    return redirect(f"/admin/orders/{order_id}", localize=False)


@router.post("/orders/{order_id}/note")
async def add_note(
    request: Request,
    db: DB,
    admin: Admin,
    order_id: uuid.UUID,
    note: str = Form(..., min_length=1, max_length=1000),
) -> Response:
    await order_service.add_note(db, order_id, note.strip(), actor=actor(admin))
    return redirect(f"/admin/orders/{order_id}", localize=False)


@router.post("/orders/{order_id}/refund")
async def refund(
    request: Request,
    db: DB,
    admin: Admin,
    order_id: uuid.UUID,
    amount_egp: str = Form(..., max_length=20),
) -> Response:
    try:
        amount = egp_to_piasters(amount_egp.replace(",", "").strip())
    except Exception:
        raise AppError("admin.error.refund_amount") from None
    await payment_service.refund(db, order_id, amount, actor=actor(admin))
    _flash(request, "Refund sent to Paymob.")
    return redirect(f"/admin/orders/{order_id}", localize=False)


@router.post("/orders/{order_id}/bosta")
async def create_shipment(request: Request, db: DB, admin: Admin, order_id: uuid.UUID) -> Response:
    order = await shipment_service.create_shipment(db, order_id, actor=actor(admin))
    _flash(request, f"Bosta shipment created: {order.bosta_tracking_number}")
    return redirect(f"/admin/orders/{order_id}", localize=False)


@router.post("/orders/{order_id}/check-payment")
async def check_payment(request: Request, db: DB, admin: Admin, order_id: uuid.UUID) -> Response:
    order = await order_service.get_order(db, order_id)
    result = await payment_service.reconcile(db, order)
    _flash(
        request,
        f"Paymob says: {result.outcome.value}"
        if result
        else "No new payment information from Paymob.",
        "success" if result else "info",
    )
    return redirect(f"/admin/orders/{order_id}", localize=False)
