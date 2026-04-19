"""Risk manager service entrypoint."""

from __future__ import annotations

import asyncio
import logging

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
    bus = BusClient(settings.redis_url, settings.service_name)
    db = Database(settings.postgres_dsn)
    await bus.connect()
    await db.connect()
    try:
        await run(bus=bus, db=db, settings=settings)
    finally:
        await bus.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
