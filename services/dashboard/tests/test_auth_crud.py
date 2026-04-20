"""Integration tests for operator CRUD helpers (requires Postgres)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from algobet_common.db import Database
from dashboard.auth import crud
from dashboard.auth.passwords import hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def cleanup_operators(db: Database) -> AsyncIterator[list[uuid.UUID]]:
    created: list[uuid.UUID] = []
    yield created
    if created:
        async with db.acquire() as conn:
            await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created)


def _email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@example.com"


async def test_create_and_get_by_email(db: Database, cleanup_operators: list[uuid.UUID]) -> None:
    email = _email("roundtrip")
    op = await crud.create_operator(db, email=email, password_hash=hash_password("pw"))
    cleanup_operators.append(op.id)
    fetched = await crud.get_operator_by_email(db, email)
    assert fetched is not None
    assert fetched.id == op.id
    assert fetched.email == email


async def test_get_by_email_case_insensitive(
    db: Database, cleanup_operators: list[uuid.UUID]
) -> None:
    email_upper = _email("CASE").upper()  # "CASE-XXXX@EXAMPLE.COM"
    op = await crud.create_operator(db, email=email_upper, password_hash=hash_password("pw"))
    cleanup_operators.append(op.id)
    fetched = await crud.get_operator_by_email(db, email_upper.lower())
    assert fetched is not None
    assert fetched.id == op.id


async def test_duplicate_email_raises(db: Database, cleanup_operators: list[uuid.UUID]) -> None:
    email = _email("dup")
    op = await crud.create_operator(db, email=email, password_hash=hash_password("pw"))
    cleanup_operators.append(op.id)
    with pytest.raises(asyncpg.UniqueViolationError):
        await crud.create_operator(db, email=email, password_hash=hash_password("pw2"))


async def test_update_password_cas_success(
    db: Database, cleanup_operators: list[uuid.UUID]
) -> None:
    email = _email("cas-ok")
    old_hash = hash_password("old")
    op = await crud.create_operator(db, email=email, password_hash=old_hash)
    cleanup_operators.append(op.id)

    new_hash = hash_password("new")
    async with db.acquire() as conn:
        before_ts = await conn.fetchval(
            "SELECT last_password_change_at FROM operators WHERE id = $1", op.id
        )
    # Give the timestamp a microsecond to advance.
    ok = await crud.update_password(db, id=op.id, old_hash=old_hash, new_hash=new_hash)
    assert ok is True

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password_hash, last_password_change_at FROM operators WHERE id = $1",
            op.id,
        )
    assert row is not None
    assert row["password_hash"] == new_hash
    assert row["last_password_change_at"] >= before_ts


async def test_update_password_cas_failure_returns_false_without_change(
    db: Database, cleanup_operators: list[uuid.UUID]
) -> None:
    email = _email("cas-fail")
    current = hash_password("current")
    op = await crud.create_operator(db, email=email, password_hash=current)
    cleanup_operators.append(op.id)

    attempt = hash_password("attempt")
    ok = await crud.update_password(
        db, id=op.id, old_hash=hash_password("something-else"), new_hash=attempt
    )
    assert ok is False

    async with db.acquire() as conn:
        stored = await conn.fetchval("SELECT password_hash FROM operators WHERE id = $1", op.id)
    assert stored == current


async def test_get_by_id_missing_returns_none(db: Database) -> None:
    assert await crud.get_operator_by_id(db, uuid.uuid4()) is None


async def test_get_operator_record_returns_password_hash(
    db: Database, cleanup_operators: list[uuid.UUID]
) -> None:
    email = _email("rec")
    h = hash_password("pw")
    op = await crud.create_operator(db, email=email, password_hash=h)
    cleanup_operators.append(op.id)
    record = await crud.get_operator_record_by_email(db, email)
    assert record is not None
    assert record["password_hash"] == h
    assert record["id"] == op.id
