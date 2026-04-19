"""Shared fixtures for risk_manager tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from algobet_common.bus import BusClient


@pytest.fixture
async def bus(
    redis_url: str,
    _flush_redis: None,
    require_redis: None,
) -> AsyncIterator[BusClient]:
    """Publisher / reader bus with isolated consumer group."""
    client = BusClient(redis_url, service_name="test-risk-manager")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def engine_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """BusClient used by the risk manager engine consumer group."""
    client = BusClient(redis_url, service_name="risk-manager")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def alert_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """Reader for risk alerts stream with separate consumer group."""
    client = BusClient(redis_url, service_name="risk-manager-alert-reader")
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def approved_bus(redis_url: str) -> AsyncIterator[BusClient]:
    """Reader for approved signals stream with separate consumer group."""
    client = BusClient(redis_url, service_name="risk-manager-approved-reader")
    await client.connect()
    yield client
    await client.close()
