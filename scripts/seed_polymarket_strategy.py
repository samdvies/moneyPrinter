"""Seed the Polymarket mean-reversion strategy row from its wiki file.

Usage:
    uv run python -m scripts.seed_polymarket_strategy

Idempotent: `upsert_strategy` preserves `status` on re-run, so the row's
lifecycle (hypothesis/paper/etc.) is never clobbered by re-seeding.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from algobet_common.config import Settings
from algobet_common.db import Database
from strategy_registry.errors import StrategyLoadError
from strategy_registry.wiki_loader import load_strategy_from_wiki

logger = logging.getLogger("seed_polymarket_strategy")


async def main() -> int:
    settings = Settings(service_name="seed-polymarket-strategy")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        wiki_path = (
            Path(__file__).parent.parent
            / "wiki"
            / "30-Strategies"
            / "polymarket-yes-mean-revert.md"
        )
        try:
            strategy = await load_strategy_from_wiki(wiki_path, db)
        except StrategyLoadError:
            logger.exception("failed to load polymarket strategy from %s", wiki_path)
            return 1
        logger.info(
            "seeded strategy slug=%s id=%s status=%s",
            strategy.slug,
            strategy.id,
            strategy.status.value,
        )
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(main()))
