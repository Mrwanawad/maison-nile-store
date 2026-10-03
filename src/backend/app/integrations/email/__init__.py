"""Transactional email. Provider chosen by EMAIL_PROVIDER (none | brevo | resend)."""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("app.email")

TIMEOUT = httpx.Timeout(15.0)


async def send(*, to: str, subject: str, html: str, text: str) -> None:
    """Send one email. Never raises: a failed email must not break an order."""
    s = get_settings()
    try:
        if s.email_provider == "brevo" and s.email_api_key:
            await _brevo(to, subject, html, text)
        elif s.email_provider == "resend" and s.email_api_key:
            await _resend(to, subject, html, text)
        else:
            log.info("email disabled; not sent", extra={"ctx": {"to": to, "subject": subject}})
    except Exception:
        log.exception("email send failed", extra={"ctx": {"subject": subject}})


async def _brevo(to: str, subject: str, html: str, text: str) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": s.email_api_key, "accept": "application/json"},
            json={
                "sender": {"name": s.email_from_name, "email": s.email_from},
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html,
                "textContent": text,
            },
        )
    if response.status_code >= 400:
        log.warning(
            "brevo error",
            extra={"ctx": {"status": response.status_code, "body": response.text[:300]}},
        )


async def _resend(to: str, subject: str, html: str, text: str) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {s.email_api_key}"},
            json={
                "from": f"{s.email_from_name} <{s.email_from}>",
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )
    if response.status_code >= 400:
        log.warning(
            "resend error",
            extra={"ctx": {"status": response.status_code, "body": response.text[:300]}},
        )
