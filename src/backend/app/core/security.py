"""CSRF, signed order links, password hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

import bcrypt
from fastapi import HTTPException, Request, status

from app.core.config import get_settings

CSRF_SESSION_KEY = "csrf"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# --- CSRF (synchronizer token stored in the signed session cookie) ----------


def has_session(request: Request) -> bool:
    """False while rendering the last-resort 500 page (runs outside the session layer)."""
    return "session" in request.scope


def csrf_token(request: Request) -> str:
    if not has_session(request):
        return ""
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency for HTML routes that change state."""
    if request.method not in UNSAFE_METHODS:
        return
    expected = request.session.get(CSRF_SESSION_KEY)
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            value = form.get(CSRF_FORM_FIELD)
            sent = value if isinstance(value, str) else None
    if not expected or not sent or not hmac.compare_digest(str(expected), sent):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf")


# --- Signed order links -----------------------------------------------------


def order_token(order_id: uuid.UUID | str) -> str:
    key = get_settings().secret_key.encode()
    digest = hmac.new(key, f"order:{order_id}".encode(), hashlib.sha256).hexdigest()
    return digest[:32]


def verify_order_token(order_id: uuid.UUID | str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(order_token(order_id), token or "")


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
