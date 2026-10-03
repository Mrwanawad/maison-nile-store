"""Cart: full page plus HTMX drawer endpoints. Works without JavaScript."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from app.controllers.deps import DB, redirect
from app.core.errors import AppError, is_htmx
from app.core.i18n import t
from app.core.security import verify_csrf
from app.core.templates import render
from app.repositories import catalog_repo
from app.services import cart_service
from app.services.catalog_service import resolve_variant

router = APIRouter(prefix="/cart")


def _optional_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise AppError("cart.error.unavailable") from None


async def _drawer(
    request: Request, db: DB, *, toast: str | None = None, open_drawer: bool = False
) -> Response:
    cart = await cart_service.load(db, request.session)
    events: dict[str, object] = {}
    if toast:
        events["toast"] = {"message": toast, "kind": "success"}
    if open_drawer:
        events["cart:open"] = True
    headers = {"HX-Trigger": json.dumps(events, ensure_ascii=True)} if events else None
    return render(request, "partials/cart_drawer_body.html", {"cart": cart}, headers=headers)


@router.get("")
async def cart_page(request: Request, db: DB) -> Response:
    cart = await cart_service.load(db, request.session)
    return render(request, "pages/cart.html", {"cart": cart})


@router.get("/drawer")
async def cart_drawer(request: Request, db: DB) -> Response:
    return await _drawer(request, db)


@router.post("/items", dependencies=[Depends(verify_csrf)])
async def add_item(
    request: Request,
    db: DB,
    product_id: uuid.UUID = Form(...),
    variant_id: str | None = Form(None),
    color_id: str | None = Form(None),
    size_id: str | None = Form(None),
    quantity: int = Form(1, ge=1, le=99),
) -> Response:
    vid = _optional_uuid(variant_id)
    if vid is None:
        product = await catalog_repo.get_product(db, product_id)
        if product is None or not product.is_active:
            raise AppError("cart.error.unavailable", status_code=404)
        has_colors = any(v.color_id for v in product.variants if v.is_active)
        has_sizes = any(v.size_id for v in product.variants if v.is_active)
        cid, sid = _optional_uuid(color_id), _optional_uuid(size_id)
        if (has_colors and cid is None) or (has_sizes and sid is None):
            raise AppError("cart.error.choose_options")
        variant = resolve_variant(product, cid, sid)
        if variant is None:
            raise AppError("cart.error.unavailable")
        vid = variant.id
    await cart_service.add(db, request.session, vid, quantity)
    if is_htmx(request):
        return await _drawer(request, db, toast=t("cart.added"), open_drawer=True)
    return redirect("/cart")


@router.post("/items/{variant_id}/update", dependencies=[Depends(verify_csrf)])
async def update_item(
    request: Request, db: DB, variant_id: uuid.UUID, quantity: int = Form(..., ge=0, le=99)
) -> Response:
    await cart_service.set_quantity(db, request.session, variant_id, quantity)
    if is_htmx(request):
        if request.headers.get("hx-target") == "cart-page":
            cart = await cart_service.load(db, request.session)
            return render(request, "partials/cart_page_body.html", {"cart": cart})
        return await _drawer(request, db)
    return redirect("/cart")


@router.post("/items/{variant_id}/remove", dependencies=[Depends(verify_csrf)])
async def remove_item(request: Request, db: DB, variant_id: uuid.UUID) -> Response:
    cart_service.remove(request.session, variant_id)
    if is_htmx(request):
        if request.headers.get("hx-target") == "cart-page":
            cart = await cart_service.load(db, request.session)
            return render(request, "partials/cart_page_body.html", {"cart": cart})
        return await _drawer(request, db)
    return redirect("/cart")
