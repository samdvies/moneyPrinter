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
from pathlib import Path

from algobet_common.config import Settings
from algobet_common.db import Database
from strategy_registry.wiki_loader import load_strategy_from_wiki


async def main() -> None:
    settings = Settings(service_name="seed-reference-strategy")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        wiki_path = (
            Path(__file__).parent.parent / "wiki" / "30-Strategies" / "mean-reversion-ref.md"
        )
        strategy = await load_strategy_from_wiki(wiki_path, db)
        print(
            f"seeded strategy slug={strategy.slug} id={strategy.id} status={strategy.status.value}"
        )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
