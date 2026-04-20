"""Interactive bootstrap CLI: create an operator or rotate a password.

Usage:
    uv run python -m scripts.create_operator --email you@example.com
    uv run python -m scripts.create_operator --email you@example.com --rotate

Prompts for the password twice via `getpass` so nothing is echoed or left
on the shell history. Rotating destroys every active Redis session for the
operator so a compromised cookie cannot outlive the rotation.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

import asyncpg
import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from dashboard.auth import crud, passwords
from dashboard.auth.sessions import destroy_all_sessions_for_operator

_MIN_LEN = 12
_WARN_LEN = 16


def _prompt_password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm: ")
    if first != second:
        print("passwords did not match", file=sys.stderr)
        sys.exit(2)
    if len(first) < _MIN_LEN:
        print(f"password must be at least {_MIN_LEN} characters", file=sys.stderr)
        sys.exit(2)
    if len(first) < _WARN_LEN:
        print(
            f"warning: password is under {_WARN_LEN} characters — consider a longer one",
            file=sys.stderr,
        )
    return first


async def _create(db: Database, *, email: str, plain: str) -> None:
    hashed = passwords.hash_password(plain)
    try:
        await crud.create_operator(db, email=email, password_hash=hashed)
    except asyncpg.UniqueViolationError:
        print(f"operator {email} already exists; use --rotate", file=sys.stderr)
        sys.exit(2)
    print(f"created operator {email}")


async def _rotate(
    db: Database,
    r: redis.Redis,
    *,
    email: str,
    plain: str,
) -> None:
    operator = await crud.get_operator_by_email(db, email)
    if operator is None:
        print(f"no operator with email {email}", file=sys.stderr)
        sys.exit(2)
    hashed = passwords.hash_password(plain)
    ok = await crud.admin_reset_password(db, operator_id=operator.id, new_hash=hashed)
    if not ok:
        print(f"operator {email} vanished mid-rotation", file=sys.stderr)
        sys.exit(2)
    await destroy_all_sessions_for_operator(r, operator_id=operator.id)
    print(f"rotated password for {email}; all sessions destroyed")


async def _run(args: argparse.Namespace) -> None:
    settings = Settings(service_name="create-operator")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        plain = _prompt_password()
        if args.rotate:
            r = redis.from_url(settings.redis_url, decode_responses=True)
            try:
                await _rotate(db, r, email=args.email, plain=plain)
            finally:
                await r.aclose()
        else:
            await _create(db, email=args.email, plain=plain)
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="operator email address")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="rotate an existing operator's password and destroy all their sessions",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
