"""Image storage: local disk (development) or Supabase Storage (production)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import IntegrationError

log = logging.getLogger("app.storage")

MEDIA_ROOT = Path("media")
MEDIA_URL = "/media"


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def delete(self, url: str) -> None: ...


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _remove(path: Path) -> None:
    if path.resolve().is_relative_to(MEDIA_ROOT.resolve()):
        path.unlink(missing_ok=True)


class LocalStorage:
    async def put(self, key: str, data: bytes, content_type: str) -> str:
        await asyncio.to_thread(_write, MEDIA_ROOT / key, data)
        return f"{MEDIA_URL}/{key}"

    async def delete(self, url: str) -> None:
        if url.startswith(MEDIA_URL + "/"):
            await asyncio.to_thread(_remove, MEDIA_ROOT / url.removeprefix(MEDIA_URL + "/"))


class SupabaseStorage:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.supabase_url.rstrip("/")
        self.bucket = s.supabase_bucket
        self.headers = {
            "Authorization": f"Bearer {s.supabase_service_key}",
            "apikey": s.supabase_service_key,
        }

    @property
    def public_prefix(self) -> str:
        return f"{self.base}/storage/v1/object/public/{self.bucket}/"

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        url = f"{self.base}/storage/v1/object/{self.bucket}/{key}"
        headers = {
            **self.headers,
            "Content-Type": content_type,
            "x-upsert": "true",
            "Cache-Control": "max-age=31536000",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.post(url, content=data, headers=headers)
        except httpx.HTTPError as exc:
            raise IntegrationError("storage unreachable") from exc
        if response.status_code >= 400:
            log.error("supabase upload failed", extra={"ctx": {"status": response.status_code}})
            raise IntegrationError("upload failed")
        return self.public_prefix + key

    async def delete(self, url: str) -> None:
        if not url.startswith(self.public_prefix):
            return
        key = url.removeprefix(self.public_prefix)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                await client.request(
                    "DELETE",
                    f"{self.base}/storage/v1/object/{self.bucket}",
                    json={"prefixes": [key]},
                    headers=self.headers,
                )
        except httpx.HTTPError:
            log.warning("supabase delete failed", extra={"ctx": {"key": key}})


def get_storage() -> Storage:
    if get_settings().storage_backend == "supabase":
        return SupabaseStorage()
    return LocalStorage()
