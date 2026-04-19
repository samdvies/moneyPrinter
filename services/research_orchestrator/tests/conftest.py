"""Shared fixtures for research_orchestrator tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from algobet_common.bus import BusClient
from algobet_common.db import Database


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncIterator[Database]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def bus(
    redis_url: str,
    _flush_redis: None,
    require_redis: None,
) -> AsyncIterator[BusClient]:
    client = BusClient(redis_url, service_name="test-research-orchestrator")
    await client.connect()
    yield client
    await client.close()
