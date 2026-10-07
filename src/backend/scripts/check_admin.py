"""Diagnose an admin login: which database is used, which admins exist, and
whether a password matches. Run it from the same folder as the server.

    uv run python -m scripts.check_admin <username> <password>
"""

from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlsplit

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.security import verify_password
from app.models import AdminUser


async def main(username: str, password: str) -> None:
    url = urlsplit(get_settings().database_url)
    print(f"Database       : {url.hostname}:{url.port}{url.path}")
    async with SessionLocal() as db:
        admins = (await db.scalars(select(AdminUser).order_by(AdminUser.username))).all()
        print(f"Admins         : {', '.join(a.username for a in admins) or '(none)'}")
        user = next((a for a in admins if a.username == username.strip().lower()), None)
        if user is None:
            print(f"Result         : no admin named '{username.strip().lower()}' in this database")
        elif not user.is_active:
            print("Result         : account exists but is disabled")
        else:
            ok = verify_password(password, user.password_hash)
            verdict = "MATCHES" if ok else "does NOT match"
            print(f"Result         : password {verdict} (length {len(password)})")
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    print(f"Working folder : {os.getcwd()}")
    print(f".env found     : {os.path.exists('.env')}")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
