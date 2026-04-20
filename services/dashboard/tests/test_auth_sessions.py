"""Integration tests for the Redis-backed session store."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from dashboard.auth import crud, sessions
from dashboard.auth.models import Operator
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
async def r(redis_url: str, require_redis: None, _flush_redis: None) -> AsyncIterator[redis.Redis]:
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def cleanup_operators(db: Database) -> AsyncIterator[list[uuid.UUID]]:
    created: list[uuid.UUID] = []
    yield created
    if created:
        async with db.acquire() as conn:
            await conn.execute("DELETE FROM operators WHERE id = ANY($1::uuid[])", created)


def _settings(ttl: int = 28800) -> Settings:
    return Settings(service_name="dashboard-test", session_ttl_seconds=ttl)


async def _make_operator(db: Database, cleanup: list[uuid.UUID], tag: str = "s") -> Operator:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    op = await crud.create_operator(db, email=email, password_hash=hash_password("pw"))
    cleanup.append(op.id)
    return op


async def test_create_then_lookup_returns_operator(
    db: Database, r: redis.Redis, cleanup_operators: list[uuid.UUID]
) -> None:
    op = await _make_operator(db, cleanup_operators)
    token = await sessions.create_session(r, _settings(), operator_id=op.id)
    looked_up = await sessions.lookup_session(r, db, token=token)
    assert looked_up is not None
    assert looked_up.id == op.id


async def test_lookup_missing_token_returns_none(db: Database, r: redis.Redis) -> None:
    assert await sessions.lookup_session(r, db, token="does-not-exist") is None


async def test_lookup_empty_token_returns_none(db: Database, r: redis.Redis) -> None:
    assert await sessions.lookup_session(r, db, token="") is None


@pytest.mark.slow
async def test_lookup_respects_ttl(
    db: Database, r: redis.Redis, cleanup_operators: list[uuid.UUID]
) -> None:
    op = await _make_operator(db, cleanup_operators, tag="ttl")
    token = await sessions.create_session(r, _settings(ttl=1), operator_id=op.id)
    await asyncio.sleep(1.5)
    assert await sessions.lookup_session(r, db, token=token) is None


async def test_lookup_returns_none_when_operator_deleted(
    db: Database, r: redis.Redis, cleanup_operators: list[uuid.UUID]
) -> None:
    op = await _make_operator(db, cleanup_operators, tag="del")
    token = await sessions.create_session(r, _settings(), operator_id=op.id)
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM operators WHERE id = $1", op.id)
    cleanup_operators.remove(op.id)
    assert await sessions.lookup_session(r, db, token=token) is None


async def test_destroy_session_removes_primary_and_secondary(
    db: Database, r: redis.Redis, cleanup_operators: list[uuid.UUID]
) -> None:
    op = await _make_operator(db, cleanup_operators, tag="destroy")
    token = await sessions.create_session(r, _settings(), operator_id=op.id)
    await sessions.destroy_session(r, token=token)
    assert await r.get(f"dashboard:session:{token}") is None
    still_in_set: int = await r.sismember(  # type: ignore[misc]
        f"dashboard:operator_sessions:{op.id}", token
    )
    assert not still_in_set


async def test_destroy_all_sessions_for_operator_affects_only_that_operator(
    db: Database, r: redis.Redis, cleanup_operators: list[uuid.UUID]
) -> None:
    op_a = await _make_operator(db, cleanup_operators, tag="a")
    op_b = await _make_operator(db, cleanup_operators, tag="b")
    t_a1 = await sessions.create_session(r, _settings(), operator_id=op_a.id)
    t_a2 = await sessions.create_session(r, _settings(), operator_id=op_a.id)
    t_b1 = await sessions.create_session(r, _settings(), operator_id=op_b.id)
    t_b2 = await sessions.create_session(r, _settings(), operator_id=op_b.id)

    await sessions.destroy_all_sessions_for_operator(r, operator_id=op_a.id)

    assert await sessions.lookup_session(r, db, token=t_a1) is None
    assert await sessions.lookup_session(r, db, token=t_a2) is None
    b1 = await sessions.lookup_session(r, db, token=t_b1)
    b2 = await sessions.lookup_session(r, db, token=t_b2)
    assert b1 is not None and b1.id == op_b.id
    assert b2 is not None and b2.id == op_b.id
