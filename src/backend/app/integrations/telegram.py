"""Telegram Bot API: alerts to the shop owners."""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("app.telegram")


async def send(text: str) -> None:
    """Send an HTML-formatted message to every configured chat. Never raises."""
    s = get_settings()
    if not s.telegram_ready:
        log.info("telegram disabled; message not sent", extra={"ctx": {"preview": text[:120]}})
        return
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        for chat_id in s.telegram_chat_id_list:
            try:
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if response.status_code != 200:
                    log.warning(
                        "telegram send failed",
                        extra={"ctx": {"chat": chat_id, "status": response.status_code}},
                    )
            except httpx.HTTPError as exc:
                log.warning("telegram unreachable", extra={"ctx": {"error": str(exc)}})
