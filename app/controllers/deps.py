"""Shared helpers for controllers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.i18n import url

DB = Annotated[AsyncSession, Depends(get_session)]


def redirect(path: str, *, localize: bool = True, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url(path) if localize else path, status_code=status_code)
