"""End-to-end smoke test: migrate → publish → consume → assert.

Run with `uv run python scripts/smoke.py`. Exits 0 on success, non-zero on
any failure. Used locally before committing and by CI.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_dummy_tick
from scripts.migrate import apply_migrations


async def _main() -> int:
    settings = Settings()  # type: ignore[call-arg]

    print("1/4 applying migrations...")
    await apply_migrations(settings.postgres_dsn, Path("scripts/db/migrations"))

    print("2/4 verifying strategy registry tables exist...")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT to_regclass('strategies') AS tbl")
            if row["tbl"] != "strategies":
                print("ERROR: strategies table missing", file=sys.stderr)
                return 1
    finally:
        await db.close()

    print("3/4 publishing dummy tick...")
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()
    try:
        await publish_dummy_tick(bus, market_id="smoke.e2e")

        print("4/4 consuming dummy tick...")
        received = [
            m async for m in bus.consume(
                Topic.MARKET_DATA, MarketData, count=10, block_ms=3000
            )
        ]
        if not any(m.market_id == "smoke.e2e" for m in received):
            print("ERROR: smoke tick not received", file=sys.stderr)
            return 1
    finally:
        await bus.close()

    print("OK — scaffolding is wired end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
