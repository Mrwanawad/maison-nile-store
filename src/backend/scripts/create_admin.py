"""Create or update an admin account (also used to reset a password).

    uv run python -m scripts.create_admin <username> "<Display Name>"
    # prompts for the password (min 10 characters)

Non-interactive (CI / Render shell):
    ADMIN_PASSWORD=... uv run python -m scripts.create_admin <username> "<Display Name>"
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import AdminUser

MIN_LENGTH = 10


async def main(username: str, display_name: str, password: str) -> None:
    username = username.strip().lower()
    async with SessionLocal() as db:
        user = await db.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            user = AdminUser(username=username, display_name=display_name, password_hash="")
            db.add(user)
            action = "created"
        else:
            action = "updated"
        user.display_name = display_name
        user.password_hash = hash_password(password)
        user.is_active = True
        await db.commit()
    await engine.dispose()
    print(f"Admin '{username}' {action}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1]
    display = sys.argv[2] if len(sys.argv) > 2 else name
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(pw) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters.")
        sys.exit(1)
    asyncio.run(main(name, display, pw))
