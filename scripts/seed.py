"""Load demo catalog data: categories, sizes, 10 products with colors/sizes/stock/photos.

    uv run python -m scripts.seed           # only if the catalog is empty
    uv run python -m scripts.seed --reset   # wipe catalog (not orders) and reload

Photos are Unsplash placeholders; replace them from the admin panel.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select

from app.core.db import SessionLocal, engine
from app.models import (
    Category,
    Product,
    ProductColor,
    ProductImage,
    ProductVariant,
    Size,
)
from app.utils.money import egp_to_piasters


def photo(photo_id: str) -> str:
    return f"https://images.unsplash.com/photo-{photo_id}?w=1000&h=1250&fit=crop&q=70&fm=webp"


CATEGORIES = [
    ("tops", "Tops", "بلوزات وتيشيرتات"),
    ("outerwear", "Outerwear", "جواكت"),
    ("bottoms", "Bottoms", "بناطيل"),
    ("accessories", "Accessories", "إكسسوارات"),
]

SIZES = [
    # code, en, ar, group
    ("XS", "XS", "XS", "apparel"),
    ("S", "S", "S", "apparel"),
    ("M", "M", "M", "apparel"),
    ("L", "L", "L", "apparel"),
    ("XL", "XL", "XL", "apparel"),
    ("XXL", "XXL", "XXL", "apparel"),
    ("28", "28", "28", "waist"),
    ("30", "30", "30", "waist"),
    ("32", "32", "32", "waist"),
    ("34", "34", "34", "waist"),
    ("36", "36", "36", "waist"),
]


@dataclass
class Seed:
    slug: str
    name_en: str
    name_ar: str
    desc_en: str
    desc_ar: str
    category: str
    price: int
    compare_at: int | None
    # color name_en, name_ar, hex, [photo ids]
    colors: list[tuple[str, str, str, list[str]]]
    sizes: list[str] = field(default_factory=list)
    featured: bool = False
    stock: dict[str, int] = field(default_factory=dict)  # size code -> stock, default 6


PRODUCTS = [
    Seed(
        "essential-cotton-tee", "Essential Cotton Tee", "تيشيرت قطن أساسي",
        "Heavyweight Egyptian cotton, cut for an easy, slightly boxy fit. Pre-washed so it keeps its shape.",
        "قطن مصري ثقيل بقصّة مريحة وواسعة قليلاً. مغسول مسبقاً ليحافظ على شكله.",
        "tops", 450, None,
        [("White", "أبيض", "#F4F2EE", ["1521572163474-6864f9cf17ab", "1586790170083-2f9ceadc732d"]),
         ("Black", "أسود", "#1C1B19", ["1583743814966-8936f5b7be1a", "1618354691373-d851c5c3a990"])],
        ["S", "M", "L", "XL"], featured=True, stock={"XL": 2},
    ),
    Seed(
        "suede-bomber-jacket", "Suede-Touch Bomber", "جاكيت بومبر ملمس شمواه",
        "A lightweight bomber with a soft suede-touch finish, ribbed cuffs and a full-length zip.",
        "جاكيت بومبر خفيف بملمس الشمواه الناعم، أساور مضلّعة وسحاب كامل.",
        "outerwear", 1850, 2200,
        [("Rust", "طوبي", "#B4532A", ["1591047139829-d91aecb6caea"])],
        ["S", "M", "L"], featured=True,
    ),
    Seed(
        "relaxed-jogger", "Relaxed Jogger", "بنطلون جوجر مريح",
        "Flowing jogger with an elastic waist and cuffed hems. Dress it up or keep it easy.",
        "بنطلون جوجر بخصر مطاطي وأطراف مضمومة. يناسب الخروج والراحة.",
        "bottoms", 650, 800,
        [("Blush", "وردي فاتح", "#E8C4B8", ["1594633312681-425c7b97ccd1"])],
        ["XS", "S", "M", "L"], featured=True, stock={"XS": 0, "L": 1},
    ),
    Seed(
        "fringe-knit-poncho", "Fringe Knit Poncho", "بونشو تريكو بشراشيب",
        "Open-knit cotton poncho with a fringed hem. One size, layers over anything.",
        "بونشو قطن تريكو مفرّغ بأطراف شراشيب. مقاس واحد يناسب الجميع.",
        "tops", 900, None,
        [("Cream", "كريمي", "#EDE3D1", ["1434389677669-e08b4cac3105"])],
        [], featured=True,
    ),
    Seed(
        "crewneck-sweatshirt", "Crewneck Sweatshirt", "سويتشيرت رقبة دائرية",
        "Brushed-back fleece with a clean crew neck. Warm without the bulk.",
        "سويتشيرت قطن من الداخل ناعم برقبة دائرية. دافئ وخفيف.",
        "tops", 750, None,
        [("White", "أبيض", "#F4F2EE", ["1620799140408-edc6dcb6d633"])],
        ["S", "M", "L", "XL"],
    ),
    Seed(
        "denim-trucker-jacket", "Denim Trucker Jacket", "جاكيت جينز كلاسيك",
        "Rigid indigo denim with a corduroy collar. Gets better every time you wear it.",
        "جينز نيلي متين بياقة قطيفة. يزداد جمالاً مع كل استخدام.",
        "outerwear", 1600, None,
        [("Indigo", "نيلي", "#2E3A56", ["1611312449408-fcece27cdbb7"])],
        ["S", "M", "L", "XL"], featured=True,
    ),
    Seed(
        "straight-leg-jeans", "Straight-Leg Jeans", "جينز مستقيم",
        "Mid-rise, straight through the leg, in a deep rinse wash.",
        "جينز بخصر متوسط وقصّة مستقيمة بلون غامق.",
        "bottoms", 1100, None,
        [("Dark wash", "غامق", "#1F2A3A", ["1624378439575-d8705ad7ae80"])],
        ["28", "30", "32", "34", "36"], featured=True, stock={"36": 0},
    ),
    Seed(
        "leather-backpack", "Leather Day Backpack", "شنطة ظهر جلد",
        "Full-grain leather backpack with a padded laptop sleeve. Handmade in Cairo.",
        "شنطة ظهر من الجلد الطبيعي بجيب مبطّن للابتوب. مصنوعة يدوياً في القاهرة.",
        "accessories", 2400, None,
        [("Cognac", "عسلي", "#7A3E2A", ["1622560480605-d83c853bc5c3"])],
        [], featured=True,
    ),
    Seed(
        "dot-print-shirt", "Dot Print Shirt", "قميص منقّط",
        "Soft chambray with a small dot print and three-quarter sleeves.",
        "قميص شامبراي ناعم بنقشة نقاط صغيرة وأكمام ثلاثة أرباع.",
        "tops", 700, None,
        [("Chambray", "أزرق شامبراي", "#5B7894", ["1596755094514-f87e34085b2c"])],
        ["S", "M", "L"],
    ),
    Seed(
        "biker-jacket", "Biker Jacket", "جاكيت بايكر",
        "Classic biker silhouette in supple faux leather with silver hardware.",
        "جاكيت بايكر كلاسيكي من الجلد الصناعي الناعم بإكسسوارات فضية.",
        "outerwear", 2100, 2600,
        [("Black", "أسود", "#1C1B19", ["1551028719-00167b16eac5"])],
        ["S", "M", "L"],
    ),
]


def _sku(slug: str, color: str, size: str | None) -> str:
    parts = [slug[:20].upper(), color[:8].upper().replace(" ", "")]
    if size:
        parts.append(size)
    return "-".join(parts) + "-" + secrets.token_hex(2).upper()


async def seed(reset: bool) -> None:
    async with SessionLocal() as db:
        if reset:
            for model in (ProductImage, ProductVariant, ProductColor, Product, Category, Size):
                await db.execute(delete(model))
            await db.commit()
        if await db.scalar(select(func.count()).select_from(Product)):
            print("Catalog not empty; use --reset to reload. Nothing done.")
            return

        categories = {}
        for i, (slug, en, ar) in enumerate(CATEGORIES):
            categories[slug] = Category(slug=slug, name_en=en, name_ar=ar, sort_order=i)
            db.add(categories[slug])
        sizes = {}
        for i, (code, en, ar, group) in enumerate(SIZES):
            sizes[code] = Size(code=code, label_en=en, label_ar=ar, size_group=group, sort_order=i)
            db.add(sizes[code])
        await db.flush()

        for order, s in enumerate(PRODUCTS):
            product = Product(
                slug=s.slug,
                name_en=s.name_en,
                name_ar=s.name_ar,
                description_en=s.desc_en,
                description_ar=s.desc_ar,
                category_id=categories[s.category].id,
                price_piasters=egp_to_piasters(s.price),
                compare_at_piasters=egp_to_piasters(s.compare_at) if s.compare_at else None,
                is_featured=s.featured,
                sort_order=order,
            )
            db.add(product)
            await db.flush()
            position = 0
            for c_index, (c_en, c_ar, hex_, photos) in enumerate(s.colors):
                color = ProductColor(
                    product_id=product.id, name_en=c_en, name_ar=c_ar, hex=hex_, sort_order=c_index
                )
                db.add(color)
                await db.flush()
                for pid in photos:
                    db.add(
                        ProductImage(
                            product_id=product.id,
                            color_id=color.id if len(s.colors) > 1 else None,
                            url=photo(pid),
                            alt_en=f"{s.name_en} in {c_en}",
                            alt_ar=f"{s.name_ar} - {c_ar}",
                            width=1000,
                            height=1250,
                            sort_order=position,
                        )
                    )
                    position += 1
                for code in s.sizes or [None]:
                    db.add(
                        ProductVariant(
                            product_id=product.id,
                            color_id=color.id,
                            size_id=sizes[code].id if code else None,
                            sku=_sku(s.slug, c_en, code),
                            stock=s.stock.get(code or "", 6),
                        )
                    )
        await db.commit()
        print(f"Seeded {len(CATEGORIES)} categories, {len(SIZES)} sizes, {len(PRODUCTS)} products.")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete catalog data first")
    asyncio.run(seed(parser.parse_args().reset))
