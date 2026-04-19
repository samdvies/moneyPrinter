"""Risk manager service entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg
from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database

from risk_manager.engine import run

logger = logging.getLogger(__name__)


async def _main() -> None:
    settings = Settings(service_name="risk-manager")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("[risk-manager] starting")

    # Acquire a process-lifetime session advisory lock.  A second instance
    # attempting to start will find the lock already held and exit fast.
    # We use a dedicated asyncpg connection (not the pool) because we must
    # hold this connection open for the entire process lifetime — releasing a
    # pooled connection would drop the session lock.
    singleton_conn = await asyncpg.connect(settings.postgres_dsn)
    got_lock: bool = await singleton_conn.fetchval(
        "SELECT pg_try_advisory_lock(hashtext('risk:singleton'))"
    )
    if not got_lock:
        logger.critical("another risk manager is already running")
        await singleton_conn.close()
        sys.exit(2)

    bus = BusClient(settings.redis_url, settings.service_name)
    db = Database(settings.postgres_dsn)
    try:
        await bus.connect()
        await db.connect()
        await run(bus=bus, db=db, settings=settings)
    finally:
        await bus.close()
        await db.close()
        await singleton_conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
