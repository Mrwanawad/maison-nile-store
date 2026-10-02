"""Checkout: form, live shipping fee, order placement (COD or Paymob)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError

from app.controllers.deps import DB, redirect
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.i18n import get_locale, t
from app.core.rate_limit import CHECKOUT_LIMIT, limiter
from app.core.security import order_token, verify_csrf
from app.core.templates import render
from app.models import Order, PaymentMethod
from app.repositories import catalog_repo
from app.schemas.checkout import FIELD_ERROR_KEYS, CheckoutData
from app.services import (
    cart_service,
    fraud_service,
    notification_service,
    order_service,
    payment_service,
    shipping_service,
)
from app.services.catalog_service import variant_label
from app.utils import governorates

router = APIRouter()

FORM_FIELDS = ("full_name", "phone", "email", "governorate", "address", "notes", "payment_method")


def _payment_options() -> list[dict[str, Any]]:
    s = get_settings()
    options = []
    if s.paymob_ready:
        label = s.paymob_method_label_ar if get_locale() == "ar" else s.paymob_method_label_en
        options.append({"value": "paymob", "label": label, "hint": t("checkout.pay.online_hint")})
    if s.cod_enabled:
        options.append(
            {"value": "cod", "label": t("checkout.pay.cod"), "hint": t("checkout.pay.cod_hint")}
        )
    return options


async def _render_form(
    request: Request,
    db: DB,
    *,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    form_error: str | None = None,
    status_code: int = 200,
) -> Response:
    cart = await cart_service.load(db, request.session)
    values = values or {}
    options = _payment_options()
    if "payment_method" not in values and options:
        values["payment_method"] = options[0]["value"]
    gov = values.get("governorate", "")
    shipping = shipping_service.fee_for(gov) if gov in governorates.BY_CODE else None
    return render(
        request,
        "pages/checkout.html",
        {
            "cart": cart,
            "values": values,
            "errors": errors or {},
            "form_error": form_error,
            "payment_options": options,
            "shipping": shipping,
            "total": cart.subtotal + (shipping or 0),
            "honeypot": fraud_service.HONEYPOT_FIELD,
        },
        status_code=status_code,
    )


@router.get("/checkout")
async def checkout_form(request: Request, db: DB) -> Response:
    cart = await cart_service.load(db, request.session)
    if cart.is_empty:
        return redirect("/cart")
    return await _render_form(request, db)


@router.get("/checkout/summary")
async def checkout_summary(
    request: Request, db: DB, governorate: str = Query("", max_length=40)
) -> Response:
    """HTMX: recompute totals when the governorate changes."""
    cart = await cart_service.load(db, request.session)
    shipping = (
        shipping_service.fee_for(governorate) if governorate in governorates.BY_CODE else None
    )
    return render(
        request,
        "partials/checkout_totals.html",
        {"cart": cart, "shipping": shipping, "total": cart.subtotal + (shipping or 0)},
    )


def _order_url(order: Order) -> str:
    return f"/order/{order.id}?t={order_token(order.id)}"


async def _low_stock(db: DB, order: Order) -> list[tuple[str, int]]:
    threshold = get_settings().low_stock_threshold
    ids = [i.variant_id for i in order.items if i.variant_id]
    rows = []
    for v in await catalog_repo.get_variants(db, ids):
        if v.stock <= threshold:
            label = variant_label(v, "en")
            rows.append((v.product.name_en + (f" ({label})" if label else ""), v.stock))
    return rows


@router.post("/checkout", dependencies=[Depends(verify_csrf)])
@limiter.limit(CHECKOUT_LIMIT)
async def place_order(request: Request, db: DB, background: BackgroundTasks) -> Response:
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in FORM_FIELDS}

    if fraud_service.is_bot(str(form.get(fraud_service.HONEYPOT_FIELD, ""))):
        return redirect("/")

    try:
        data = CheckoutData.model_validate(
            {k: v or None if k in ("email", "notes") else v for k, v in values.items()}
        )
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else ""
            errors.setdefault(field, t(FIELD_ERROR_KEYS.get(field, "error.validation")))
        return await _render_form(request, db, values=values, errors=errors, status_code=422)

    cart = await cart_service.load(db, request.session)
    if cart.is_empty:
        return redirect("/cart")

    try:
        order = await order_service.place_order(
            db, data, cart_service.items_for_order(cart), locale=get_locale()
        )
    except AppError as exc:
        return await _render_form(
            request, db, values=values, form_error=exc.message, status_code=exc.status_code
        )

    cart_service.clear(request.session)
    snap = notification_service.snapshot(order)
    background.add_task(notification_service.after_order_placed, snap, await _low_stock(db, order))

    if order.payment_method == PaymentMethod.paymob:
        try:
            checkout_url = await payment_service.start_checkout(db, order.id)
        except AppError:
            # Order exists; the order page offers a retry button.
            return redirect(_order_url(order) + "&pay_error=1")
        return RedirectResponse(checkout_url, status_code=303)
    return redirect(_order_url(order))
