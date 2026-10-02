"""Admin login backed by the `admin_users` table (bcrypt). Session-cookie based."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import hash_password, verify_password
from app.models import AdminUser

SESSION_KEY = "admin_id"
# Same cost as a real check, so unknown usernames take as long as wrong passwords.
_DUMMY_HASH = hash_password("not-a-real-password")


async def authenticate(db: AsyncSession, username: str, password: str) -> AdminUser | None:
    user = await db.scalar(select(AdminUser).where(AdminUser.username == username.strip().lower()))
    if user is None or not user.is_active:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


def login(request: Request, user: AdminUser) -> None:
    # Keep the cart, drop anything else, rotate CSRF token.
    cart = request.session.get("cart")
    request.session.clear()
    if cart:
        request.session["cart"] = cart
    request.session[SESSION_KEY] = str(user.id)


def logout(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


async def current_admin(request: Request, db: AsyncSession = Depends(get_session)) -> AdminUser:
    """Dependency for admin routes: redirect to login when not signed in."""
    raw = request.session.get(SESSION_KEY)
    user = None
    if isinstance(raw, str):
        try:
            user = await db.get(AdminUser, uuid.UUID(raw))
        except ValueError:
            user = None
    if user is None or not user.is_active:
        request.session.pop(SESSION_KEY, None)
        if request.headers.get("hx-request") == "true":
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/admin/login"}
            )
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return user


def actor(user: AdminUser) -> str:
    return f"admin:{user.username}"
