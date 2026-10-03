"""In-process cache of active categories for the header/footer (single worker).

Refreshed at startup and whenever an admin changes categories.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import catalog_repo


@dataclass(frozen=True, slots=True)
class NavCategory:
    slug: str
    name_en: str
    name_ar: str

    def name(self, locale: str) -> str:
        return self.name_ar if locale == "ar" else self.name_en


_categories: list[NavCategory] = []


def nav_categories() -> list[NavCategory]:
    return _categories


async def refresh(db: AsyncSession) -> None:
    global _categories
    rows = await catalog_repo.list_categories(db)
    _categories = [NavCategory(c.slug, c.name_en, c.name_ar) for c in rows]
