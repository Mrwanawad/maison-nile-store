"""Admin: products (with colors, sizes, variants, images), categories, sizes, blocklist."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.controllers.deps import DB, redirect
from app.core.errors import NotFound
from app.core.security import verify_csrf
from app.core.templates import render
from app.models import AdminUser, PhoneBlock
from app.repositories import catalog_repo
from app.services import nav_cache
from app.services import product_admin_service as svc
from app.services.admin_auth_service import actor, current_admin
from app.utils.money import piasters_to_egp_str

Admin = Annotated[AdminUser, Depends(current_admin)]

router = APIRouter(prefix="/admin", dependencies=[Depends(verify_csrf), Depends(current_admin)])


def _flash(request: Request, message: str, kind: str = "success") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _product_back(product_id: uuid.UUID, anchor: str = "") -> Response:
    return redirect(f"/admin/products/{product_id}{anchor}", localize=False)


# --- Products -----------------------------------------------------------------


@router.get("/products")
async def products_list(request: Request, db: DB, admin: Admin, q: str | None = None) -> Response:
    products = await catalog_repo.list_products(
        db, query=q, active_only=False, limit=500, sort="featured"
    )
    return render(
        request, "admin/products.html", {"admin": admin, "products": products, "q": q or ""}
    )


@router.get("/products/new")
async def product_new(request: Request, db: DB, admin: Admin) -> Response:
    return render(
        request,
        "admin/product_form.html",
        {
            "admin": admin,
            "product": None,
            "categories": await catalog_repo.list_categories(db, active_only=False),
        },
    )


def _product_input(form: dict[str, str]) -> svc.ProductInput:
    try:
        sort_order = int(form.get("sort_order") or 0)
    except ValueError:
        sort_order = 0
    return svc.ProductInput(
        name_en=form.get("name_en", ""),
        name_ar=form.get("name_ar", ""),
        slug=form.get("slug", ""),
        description_en=form.get("description_en", ""),
        description_ar=form.get("description_ar", ""),
        category_id=_uuid_or_none(form.get("category_id")),
        price_egp=form.get("price_egp", ""),
        compare_at_egp=form.get("compare_at_egp", ""),
        is_active=form.get("is_active") == "on",
        is_featured=form.get("is_featured") == "on",
        sort_order=sort_order,
    )


@router.post("/products")
async def product_create(request: Request, db: DB, admin: Admin) -> Response:
    form = {k: str(v) for k, v in (await request.form()).items()}
    product = await svc.save_product(db, _product_input(form))
    _flash(request, "Product created. Now add colors, sizes, stock and photos.")
    return _product_back(product.id)


@router.get("/products/{product_id}")
async def product_edit(request: Request, db: DB, admin: Admin, product_id: uuid.UUID) -> Response:
    product = await catalog_repo.get_product(db, product_id)
    if product is None:
        raise NotFound()
    sizes = await catalog_repo.list_sizes(db)
    used_sizes = {v.size_id for v in product.variants if v.size_id and v.is_active}
    variants = sorted(
        product.variants,
        key=lambda v: (
            not v.is_active,
            v.color.sort_order if v.color else -1,
            v.size.sort_order if v.size else -1,
        ),
    )
    return render(
        request,
        "admin/product_form.html",
        {
            "admin": admin,
            "product": product,
            "categories": await catalog_repo.list_categories(db, active_only=False),
            "sizes": sizes,
            "used_sizes": used_sizes,
            "variants": variants,
            "egp": piasters_to_egp_str,
        },
    )


@router.post("/products/{product_id}")
async def product_update(request: Request, db: DB, admin: Admin, product_id: uuid.UUID) -> Response:
    form = {k: str(v) for k, v in (await request.form()).items()}
    await svc.save_product(db, _product_input(form), product_id)
    _flash(request, "Product saved.")
    return _product_back(product_id)


@router.post("/products/{product_id}/delete")
async def product_delete(request: Request, db: DB, admin: Admin, product_id: uuid.UUID) -> Response:
    await svc.delete_product(db, product_id)
    _flash(request, "Product deleted. Past orders keep their item details.")
    return redirect("/admin/products", localize=False)


@router.post("/products/{product_id}/colors")
async def color_add(
    request: Request,
    db: DB,
    admin: Admin,
    product_id: uuid.UUID,
    name_en: str = Form(..., max_length=60),
    name_ar: str = Form("", max_length=60),
    hex: str = Form("#000000", max_length=7),
) -> Response:
    await svc.add_color(db, product_id, name_en, name_ar, hex)
    _flash(request, f"Color “{name_en}” added. Set stock for its sizes below.")
    return _product_back(product_id, "#variants")


@router.post("/products/{product_id}/colors/{color_id}/delete")
async def color_delete(
    request: Request, db: DB, admin: Admin, product_id: uuid.UUID, color_id: uuid.UUID
) -> Response:
    await svc.delete_color(db, product_id, color_id)
    _flash(request, "Color removed.")
    return _product_back(product_id, "#variants")


@router.post("/products/{product_id}/sizes")
async def sizes_set(request: Request, db: DB, admin: Admin, product_id: uuid.UUID) -> Response:
    form = await request.form()
    size_ids = [u for u in (_uuid_or_none(str(v)) for v in form.getlist("size_ids")) if u]
    await svc.rebuild_variants(db, product_id, size_ids)
    _flash(request, "Sizes updated. Set stock for each combination below.")
    return _product_back(product_id, "#variants")


@router.post("/products/{product_id}/variants")
async def variants_update(
    request: Request, db: DB, admin: Admin, product_id: uuid.UUID
) -> Response:
    form = await request.form()
    rows: list[svc.VariantUpdate] = []
    for raw_id in form.getlist("variant_id"):
        vid = _uuid_or_none(str(raw_id))
        if vid is None:
            continue
        key = str(vid)
        try:
            stock = int(str(form.get(f"stock_{key}", "0")) or 0)
        except ValueError:
            stock = -1
        rows.append(
            svc.VariantUpdate(
                id=vid,
                stock=stock,
                price_override_egp=str(form.get(f"price_{key}", "")),
                is_active=form.get(f"active_{key}") == "on",
                sku=str(form.get(f"sku_{key}", "")),
            )
        )
    await svc.update_variants(db, product_id, rows)
    _flash(request, "Stock and prices saved.")
    return _product_back(product_id, "#variants")


@router.post("/products/{product_id}/images")
async def images_upload(
    request: Request,
    db: DB,
    admin: Admin,
    product_id: uuid.UUID,
    files: list[UploadFile] = File(default=[]),
    color_id: str = Form(""),
    image_url: str = Form("", max_length=1000),
) -> Response:
    cid = _uuid_or_none(color_id)
    added = 0
    if files:
        payload = [(await f.read(), f.filename or "") for f in files if f.filename]
        added = await svc.upload_images(db, product_id, payload, cid)
    if image_url.strip():
        await svc.add_image_url(db, product_id, image_url.strip(), cid)
        added += 1
    _flash(
        request,
        f"{added} photo(s) added." if added else "No photo selected.",
        "success" if added else "info",
    )
    return _product_back(product_id, "#images")


@router.post("/products/{product_id}/images/{image_id}")
async def image_update(
    request: Request,
    db: DB,
    admin: Admin,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    action: str = Form(...),
    color_id: str = Form(""),
) -> Response:
    if action == "up":
        await svc.move_image(db, product_id, image_id, -1)
    elif action == "down":
        await svc.move_image(db, product_id, image_id, 1)
    elif action == "delete":
        await svc.delete_image(db, product_id, image_id)
    elif action == "color":
        await svc.update_image(db, product_id, image_id, _uuid_or_none(color_id))
    return _product_back(product_id, "#images")


# --- Categories & sizes ----------------------------------------------------------


@router.get("/categories")
async def categories(request: Request, db: DB, admin: Admin) -> Response:
    return render(
        request,
        "admin/categories.html",
        {
            "admin": admin,
            "categories": await catalog_repo.list_categories(db, active_only=False),
            "sizes": await catalog_repo.list_sizes(db),
        },
    )


@router.post("/categories")
async def category_save(
    request: Request,
    db: DB,
    admin: Admin,
    category_id: str = Form(""),
    name_en: str = Form(..., max_length=120),
    name_ar: str = Form("", max_length=120),
    sort_order: int = Form(0),
    is_active: str = Form(""),
) -> Response:
    await svc.save_category(
        db,
        category_id=_uuid_or_none(category_id),
        name_en=name_en,
        name_ar=name_ar,
        sort_order=sort_order,
        is_active=is_active == "on",
    )
    await nav_cache.refresh(db)
    _flash(request, "Category saved.")
    return redirect("/admin/categories", localize=False)


@router.post("/categories/{category_id}/delete")
async def category_delete(
    request: Request, db: DB, admin: Admin, category_id: uuid.UUID
) -> Response:
    await svc.delete_category(db, category_id)
    await nav_cache.refresh(db)
    _flash(request, "Category deleted. Its products are now uncategorised.")
    return redirect("/admin/categories", localize=False)


@router.post("/sizes")
async def size_add(
    request: Request,
    db: DB,
    admin: Admin,
    code: str = Form(..., max_length=20),
    label_en: str = Form("", max_length=40),
    label_ar: str = Form("", max_length=40),
    size_group: str = Form("apparel", max_length=30),
    sort_order: int = Form(0),
) -> Response:
    await svc.add_size(
        db,
        code=code,
        label_en=label_en,
        label_ar=label_ar,
        size_group=size_group,
        sort_order=sort_order,
    )
    _flash(request, f"Size {code.upper()} added.")
    return redirect("/admin/categories#sizes", localize=False)


@router.post("/sizes/{size_id}/delete")
async def size_delete(request: Request, db: DB, admin: Admin, size_id: uuid.UUID) -> Response:
    await svc.delete_size(db, size_id)
    _flash(request, "Size deleted.")
    return redirect("/admin/categories#sizes", localize=False)


# --- COD blocklist -----------------------------------------------------------------


@router.get("/blocklist")
async def blocklist(request: Request, db: DB, admin: Admin) -> Response:
    rows = (await db.scalars(select(PhoneBlock).order_by(PhoneBlock.created_at.desc()))).all()
    return render(request, "admin/blocklist.html", {"admin": admin, "rows": rows})


@router.post("/blocklist")
async def blocklist_add(
    request: Request,
    db: DB,
    admin: Admin,
    phone: str = Form(..., max_length=30),
    reason: str = Form("", max_length=300),
) -> Response:
    await svc.block_phone(db, phone, reason, actor=actor(admin))
    _flash(request, "Phone blocked from cash on delivery.")
    return redirect("/admin/blocklist", localize=False)


@router.post("/blocklist/{phone}/delete")
async def blocklist_remove(request: Request, db: DB, admin: Admin, phone: str) -> Response:
    await svc.unblock_phone(db, phone)
    _flash(request, "Phone unblocked.")
    return redirect("/admin/blocklist", localize=False)
