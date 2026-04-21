"""One-shot CLI that loads the reference mean-reversion strategy into the registry.

Usage:
    uv run python -m scripts.seed_reference_strategy

Reads ``wiki/30-Strategies/mean-reversion-ref.md`` and calls
``strategy_registry.wiki_loader.load_strategy_from_wiki`` against the
Postgres pointed to by ``Settings()``. The loader's UPSERT semantics make
this safe to run repeatedly: the first run inserts the row at
``status='hypothesis'``; subsequent runs update ``parameters`` and
``wiki_path`` without clobbering status.

No side effects beyond the registry row — no Redis, no bus traffic, no
order submission.
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

logger = logging.getLogger("seed_reference_strategy")


async def main() -> int:
    settings = Settings(service_name="seed-reference-strategy")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        wiki_path = (
            Path(__file__).parent.parent / "wiki" / "30-Strategies" / "mean-reversion-ref.md"
        )
        try:
            strategy = await load_strategy_from_wiki(wiki_path, db)
        except StrategyLoadError:
            logger.exception("failed to load reference strategy from %s", wiki_path)
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
