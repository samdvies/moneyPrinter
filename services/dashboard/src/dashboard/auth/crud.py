"""Operator CRUD helpers over the `operators` table.

The public `Operator` model never carries `password_hash`. The login handler
reads a hash via `get_operator_record_by_email`, which returns an internal
TypedDict; no other caller should use it.
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from algobet_common.db import Database

from .models import Operator


class _OperatorRecord(TypedDict):
    id: uuid.UUID
    email: str
    password_hash: str
    created_at: object  # datetime — kept loose to avoid re-import cost


async def get_operator_by_email(db: Database, email: str) -> Operator | None:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, created_at FROM operators WHERE email = $1",
            email,
        )
    if row is None:
        return None
    return Operator.model_validate(dict(row))


async def get_operator_by_id(db: Database, operator_id: uuid.UUID) -> Operator | None:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, created_at FROM operators WHERE id = $1",
            operator_id,
        )
    if row is None:
        return None
    return Operator.model_validate(dict(row))


async def get_operator_record_by_email(db: Database, email: str) -> _OperatorRecord | None:
    """Login-path-only: returns the row including `password_hash`."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, created_at FROM operators WHERE email = $1",
            email,
        )
    if row is None:
        return None
    return _OperatorRecord(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


async def create_operator(db: Database, *, email: str, password_hash: str) -> Operator:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO operators (email, password_hash)
            VALUES ($1, $2)
            RETURNING id, email, created_at
            """,
            email,
            password_hash,
        )
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return Operator.model_validate(dict(row))


async def update_password(
    db: Database,
    *,
    id: uuid.UUID,
    old_hash: str,
    new_hash: str,
) -> bool:
    """Compare-and-swap password update.

    Returns True iff exactly one row was updated (the caller's view of the
    current hash matched what's in the DB). Returns False when a concurrent
    rehash won the race — that's a no-op, not an error.
    """
    async with db.acquire() as conn:
        result: str = await conn.execute(
            """
            UPDATE operators
               SET password_hash = $3,
                   last_password_change_at = now()
             WHERE id = $1 AND password_hash = $2
            """,
            id,
            old_hash,
            new_hash,
        )
    # asyncpg returns e.g. "UPDATE 1" or "UPDATE 0"
    return result.endswith(" 1")
