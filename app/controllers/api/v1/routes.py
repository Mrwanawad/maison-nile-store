"""Public JSON API v1 (for a future mobile app or integrations).

Stateless: no cookies, no CSRF. Uses the same services as the HTML storefront.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request

from app.controllers.deps import DB
from app.core.errors import AppError, NotFound
from app.core.rate_limit import API_LIMIT, CHECKOUT_LIMIT, limiter
from app.core.security import order_token, verify_order_token
from app.models import Order, PaymentMethod, Product
from app.repositories import catalog_repo
from app.schemas.api import (
    CategoryOut,
    ColorOut,
    ImageOut,
    OrderCreateIn,
    OrderItemOut,
    OrderOut,
    ProductOut,
    ProductPage,
    ProductSummaryOut,
    ShippingRateOut,
    SizeOut,
    VariantOut,
)
from app.services import (
    catalog_service,
    notification_service,
    order_service,
    payment_service,
    shipping_service,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _summary(p: Product) -> ProductSummaryOut:
    return ProductSummaryOut(
        slug=p.slug,
        name_en=p.name_en,
        name_ar=p.name_ar,
        price_piasters=p.price_piasters,
        compare_at_piasters=p.compare_at_piasters,
        image_url=p.images[0].url if p.images else None,
        in_stock=any(v.is_active and v.stock > 0 for v in p.variants),
        category=p.category.slug if p.category else None,
    )


def _order_out(order: Order, payment_url: str | None = None) -> OrderOut:
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        token=order_token(order.id),
        status=order.status.value,
        payment_method=order.payment_method.value,
        payment_status=order.payment_status.value,
        subtotal_piasters=order.subtotal_piasters,
        shipping_piasters=order.shipping_piasters,
        total_piasters=order.total_piasters,
        created_at=order.created_at,
        items=[OrderItemOut.model_validate(i, from_attributes=True) for i in order.items],
        payment_url=payment_url,
        tracking_number=order.bosta_tracking_number,
    )


@router.get("/categories", response_model=list[CategoryOut])
@limiter.limit(API_LIMIT)
async def categories(request: Request, db: DB) -> list[CategoryOut]:
    return [
        CategoryOut.model_validate(c, from_attributes=True)
        for c in await catalog_repo.list_categories(db)
    ]


@router.get("/products", response_model=ProductPage)
@limiter.limit(API_LIMIT)
async def products(
    request: Request,
    db: DB,
    category: str | None = Query(None, max_length=120),
    q: str | None = Query(None, max_length=80),
    size: str | None = Query(None, max_length=20),
    in_stock: bool = False,
    sort: Literal["featured", "newest", "price_asc", "price_desc"] = "featured",
    page: int = Query(1, ge=1, le=500),
) -> ProductPage:
    cat = await catalog_repo.get_category_by_slug(db, category) if category else None
    if category and cat is None:
        raise NotFound()
    category_id = cat.id if cat else None
    per_page = catalog_service.PAGE_SIZE
    total = await catalog_repo.count_products(
        db, category_id=category_id, query=q, size_code=size, in_stock_only=in_stock
    )
    rows = await catalog_repo.list_products(
        db,
        category_id=category_id,
        query=q,
        size_code=size,
        in_stock_only=in_stock,
        sort=sort,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ProductPage(
        items=[_summary(p) for p in rows],
        total=total,
        page=page,
        pages=max(1, -(-total // per_page)),
    )


@router.get("/products/{slug}", response_model=ProductOut)
@limiter.limit(API_LIMIT)
async def product(request: Request, db: DB, slug: str) -> ProductOut:
    p = await catalog_service.get_product_or_404(db, slug)
    return ProductOut(
        **_summary(p).model_dump(),
        description_en=p.description_en,
        description_ar=p.description_ar,
        colors=[ColorOut.model_validate(c, from_attributes=True) for c in p.colors],
        sizes=[
            SizeOut.model_validate(s, from_attributes=True) for s in catalog_service.sizes_for(p)
        ],
        variants=[
            VariantOut(
                id=v.id,
                sku=v.sku,
                color_id=v.color_id,
                size_id=v.size_id,
                price_piasters=v.price_override_piasters or p.price_piasters,
                in_stock=v.stock > 0,
                stock=v.stock,
            )
            for v in p.variants
            if v.is_active
        ],
        images=[ImageOut.model_validate(i, from_attributes=True) for i in p.images],
    )


@router.get("/shipping/rates", response_model=list[ShippingRateOut])
@limiter.limit(API_LIMIT)
async def shipping_rates(request: Request) -> list[ShippingRateOut]:
    return [
        ShippingRateOut.model_validate(r, from_attributes=True)
        for r in shipping_service.all_rates()
    ]


@router.post("/orders", response_model=OrderOut, status_code=201)
@limiter.limit(CHECKOUT_LIMIT)
async def create_order(
    request: Request, db: DB, background: BackgroundTasks, body: OrderCreateIn
) -> OrderOut:
    order = await order_service.place_order(
        db, body, [(i.variant_id, i.quantity) for i in body.items], locale=body.locale
    )
    background.add_task(
        notification_service.after_order_placed, notification_service.snapshot(order), []
    )
    payment_url = None
    if order.payment_method == PaymentMethod.paymob:
        try:
            payment_url = await payment_service.start_checkout(db, order.id)
        except AppError:
            payment_url = None
        order = await order_service.get_order(db, order.id)
    return _order_out(order, payment_url)


@router.get("/orders/{order_id}", response_model=OrderOut)
@limiter.limit(API_LIMIT)
async def get_order(
    request: Request, db: DB, order_id: uuid.UUID, token: str = Query(..., max_length=64)
) -> OrderOut:
    if not verify_order_token(order_id, token):
        raise NotFound()
    return _order_out(await order_service.get_order(db, order_id))
