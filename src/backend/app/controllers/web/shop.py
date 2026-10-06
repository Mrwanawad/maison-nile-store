"""Storefront pages: home, listing, category, product."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.controllers.deps import DB
from app.core.errors import NotFound, is_htmx
from app.core.templates import render
from app.repositories import catalog_repo
from app.services import catalog_service, shipping_service
from app.services.catalog_service import (
    color_available,
    default_variant,
    picker_data,
    size_available,
    sizes_for,
)

router = APIRouter()

Sort = Literal["featured", "newest", "price_asc", "price_desc"]


@router.get("/")
async def home(request: Request, db: DB) -> Response:
    return render(
        request,
        "pages/home.html",
        {
            "cards": await catalog_service.featured_cards(db, limit=8),
            "categories": await catalog_repo.list_categories(db),
            "tiles": await catalog_service.category_tiles(db),
        },
    )


async def _listing(
    request: Request,
    db: DB,
    *,
    category_slug: str | None,
    q: str | None,
    size: str | None,
    in_stock: bool,
    sort: Sort,
    page: int,
) -> Response:
    category = None
    if category_slug:
        category = await catalog_repo.get_category_by_slug(db, category_slug)
        if category is None:
            raise NotFound()
    result = await catalog_service.listing(
        db,
        category=category,
        query=q,
        size_code=size,
        in_stock_only=in_stock,
        sort=sort,
        page=page,
    )
    context = {
        "listing": result,
        "category": category,
        "categories": await catalog_repo.list_categories(db),
        "sizes": await catalog_repo.list_sizes_in_use(db),
        "filters": {"q": q or "", "size": size or "", "in_stock": in_stock, "sort": sort},
    }
    template = "partials/listing_results.html" if is_htmx(request) else "pages/listing.html"
    return render(request, template, context)


@router.get("/shop")
async def shop(
    request: Request,
    db: DB,
    q: str | None = Query(None, max_length=80),
    category: str | None = Query(None, max_length=120),
    size: str | None = Query(None, max_length=20),
    in_stock: bool = False,
    sort: Sort = "featured",
    page: int = Query(1, ge=1, le=500),
) -> Response:
    return await _listing(
        request,
        db,
        category_slug=category or None,
        q=q,
        size=size,
        in_stock=in_stock,
        sort=sort,
        page=page,
    )


@router.get("/c/{slug}")
async def category_page(
    request: Request,
    db: DB,
    slug: str,
    q: str | None = Query(None, max_length=80),
    size: str | None = Query(None, max_length=20),
    in_stock: bool = False,
    sort: Sort = "featured",
    page: int = Query(1, ge=1, le=500),
) -> Response:
    return await _listing(
        request, db, category_slug=slug, q=q, size=size, in_stock=in_stock, sort=sort, page=page
    )


@router.get("/p/{slug}")
async def product_page(request: Request, db: DB, slug: str) -> Response:
    product = await catalog_service.get_product_or_404(db, slug)
    sizes = sizes_for(product)
    return render(
        request,
        "pages/product.html",
        {
            "product": product,
            "card": catalog_service.to_card(product),
            "colors": product.colors,
            "sizes": sizes,
            "size_available": lambda size_id: size_available(product, size_id),
            "color_available": lambda color_id: color_available(product, color_id),
            "single_variant": default_variant(product),
            "picker": picker_data(product),
            "related": await catalog_service.related_cards(db, product),
            "shipping_from": shipping_service.lowest_fee(),
        },
    )
