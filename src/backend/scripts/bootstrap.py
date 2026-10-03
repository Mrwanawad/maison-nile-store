"""First-boot setup, run by the container after migrations (see docker/Dockerfile).

Render's free plan has no shell, so the steps that would normally be run by hand
are driven by `.env` instead. Both are idempotent and safe on every start:

- SEED_DEMO_DATA=true                 loads the demo catalog if it is empty
- ADMIN_BOOTSTRAP_USERNAME/PASSWORD    creates that admin if it does not exist
                                      (an existing admin's password is never touched)

    uv run python -m scripts.bootstrap
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import AdminUser
from scripts.create_admin import MIN_LENGTH
from scripts.seed import seed

log = logging.getLogger("bootstrap")


async def ensure_admin(username: str, display_name: str, password: str) -> None:
    username = username.strip().lower()
    if len(password) < MIN_LENGTH:
        log.error("ADMIN_BOOTSTRAP_PASSWORD must be at least %d characters; skipped", MIN_LENGTH)
        return
    async with SessionLocal() as db:
        if await db.scalar(select(AdminUser.id).where(AdminUser.username == username)):
            log.info("Admin '%s' already exists; left unchanged", username)
            return
        db.add(
            AdminUser(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                is_active=True,
            )
        )
        await db.commit()
    log.info("Admin '%s' created", username)


async def main() -> None:
    s = get_settings()
    try:
        if s.seed_demo_data:
            await seed(reset=False)
        if s.admin_bootstrap_username and s.admin_bootstrap_password:
            await ensure_admin(
                s.admin_bootstrap_username, s.admin_bootstrap_name, s.admin_bootstrap_password
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
