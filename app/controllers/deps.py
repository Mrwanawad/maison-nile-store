"""Shared helpers for controllers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import is_htmx
from app.core.i18n import url

DB = Annotated[AsyncSession, Depends(get_session)]


def redirect(path: str, *, localize: bool = True, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url(path) if localize else path, status_code=status_code)


def hx_redirect(request: Request, path: str, *, localize: bool = True) -> Response:
    """Full-page navigation that also works for HTMX requests."""
    target = url(path) if localize else path
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)
