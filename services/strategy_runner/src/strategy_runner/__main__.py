"""Strategy runner entrypoint.

Loads registered strategies from the strategies table, resolves their
`module` to the `on_tick` callable, opens a `strategy_runs` row per
strategy (mode='paper'), and drives the dispatch loop against
`market.data`. Closes runs cleanly on shutdown.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import uuid
from datetime import UTC, datetime

from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import Venue

from strategy_runner.engine import RegisteredStrategy, run_strategy_runner_loop

LOGGER = logging.getLogger(__name__)

_ACTIVE_SLUGS = ("polymarket-yes-mean-revert",)


async def _load_strategies(db: Database) -> list[RegisteredStrategy]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, slug, parameters
            FROM strategies
            WHERE slug = ANY($1::text[])
            """,
            list(_ACTIVE_SLUGS),
        )
    registered: list[RegisteredStrategy] = []
    for row in rows:
        raw_params = row["parameters"]
        if isinstance(raw_params, str):
            raw_params = json.loads(raw_params)
        params = dict(raw_params)
        module_path = params.get("module") or "backtest_engine.strategies.mean_reversion"
        module = importlib.import_module(module_path)
        on_tick = getattr(module, "on_tick", None)
        if not callable(on_tick):
            raise RuntimeError(f"strategy module {module_path!r} has no callable on_tick")
        venue_str = str(params.get("venue", "")).lower()
        try:
            venue = Venue(venue_str)
        except ValueError as exc:
            raise RuntimeError(
                f"strategy slug={row['slug']} has invalid venue param {venue_str!r}"
            ) from exc
        registered.append(
            RegisteredStrategy(
                strategy_id=str(row["id"]),
                slug=row["slug"],
                venue=venue,
                on_tick=on_tick,
                base_params=params,
            )
        )
    return registered


async def _open_paper_run(db: Database, strategy_id: str) -> str:
    async with db.acquire() as conn:
        row = await conn.fetchval(
            """
            INSERT INTO strategy_runs (strategy_id, mode, started_at)
            VALUES ($1, 'paper', $2)
            RETURNING id
            """,
            uuid.UUID(strategy_id),
            datetime.now(UTC),
        )
    return str(row)


async def _close_paper_run(db: Database, run_id: str) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE strategy_runs SET ended_at = $1 WHERE id = $2",
            datetime.now(UTC),
            uuid.UUID(run_id),
        )


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings()
    db = Database(settings.postgres_dsn)
    await db.connect()
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()

    strategies = await _load_strategies(db)
    if not strategies:
        raise RuntimeError(
            f"no registered strategies found for slugs {list(_ACTIVE_SLUGS)}; "
            f"seed them first (e.g., uv run python -m scripts.seed_polymarket_strategy)"
        )

    run_ids: dict[str, str] = {}
    for strategy in strategies:
        run_ids[strategy.strategy_id] = await _open_paper_run(db, strategy.strategy_id)
        LOGGER.info(
            "opened paper run %s for strategy %s", run_ids[strategy.strategy_id], strategy.slug
        )
    try:
        await run_strategy_runner_loop(bus=bus, strategies=strategies)
    finally:
        for run_id in run_ids.values():
            await _close_paper_run(db, run_id)
        await bus.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
