from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from app.controllers.deps import DB, redirect
from app.core.rate_limit import LOGIN_LIMIT, limiter
from app.core.security import verify_csrf
from app.core.templates import render
from app.services import admin_auth_service

router = APIRouter(prefix="/admin", dependencies=[Depends(verify_csrf)])


@router.get("/login")
async def login_form(request: Request) -> Response:
    if request.session.get(admin_auth_service.SESSION_KEY):
        return redirect("/admin", localize=False)
    return render(request, "admin/login.html", {"error": None})


@router.post("/login")
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: Request,
    db: DB,
    username: str = Form("", max_length=60),
    password: str = Form("", max_length=200),
) -> Response:
    user = await admin_auth_service.authenticate(db, username, password)
    if user is None:
        return render(
            request,
            "admin/login.html",
            {"error": "Wrong username or password.", "username": username},
            status_code=401,
        )
    admin_auth_service.login(request, user)
    return redirect("/admin", localize=False)


@router.post("/logout")
async def logout(request: Request) -> Response:
    admin_auth_service.logout(request)
    return redirect("/admin/login", localize=False)
