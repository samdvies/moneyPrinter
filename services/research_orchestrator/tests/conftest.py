"""Shared fixtures for research_orchestrator tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from algobet_common.bus import BusClient
from algobet_common.db import Database

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_WIKI_PATH = _REPO_ROOT / "wiki" / "30-Strategies" / "mean-reversion-ref.md"


@pytest.fixture(autouse=True)
def _snapshot_reference_wiki() -> Iterator[None]:
    """Snapshot + restore the reference wiki file around every test.

    Phase 6b.5 adds wiki write-back in ``runner.run_once``.  The
    integration tests dispatch the runner against the real on-disk file,
    so without this fixture an integration run would leave the repo
    file dirty with fabricated backtest numbers.  Restoring after each
    test keeps the working tree clean and lets the tests rely on a
    known starting state.
    """
    snapshot = _REFERENCE_WIKI_PATH.read_bytes() if _REFERENCE_WIKI_PATH.exists() else None
    try:
        yield
    finally:
        if snapshot is not None:
            _REFERENCE_WIKI_PATH.write_bytes(snapshot)


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
