"""CLI entrypoint for the research orchestrator.

Usage:
    SERVICE_NAME=research-orchestrator uv run python -m research_orchestrator run
"""

from __future__ import annotations

import asyncio
import logging

import typer
from algobet_common.bus import BusClient
from algobet_common.config import Settings
from algobet_common.db import Database

from .runner import run_once

logging.basicConfig(level=logging.INFO)

app = typer.Typer(help="Research Orchestrator — single-iteration research loop.")


@app.command()
def run() -> None:
    """Run one iteration of the research loop (hypothesis → backtest → paper)."""
    settings = Settings(service_name="research-orchestrator")
    db = Database(settings.postgres_dsn)
    bus = BusClient(settings.redis_url, service_name=settings.service_name)

    async def _main() -> None:
        await db.connect()
        await bus.connect()
        try:
            await run_once(db, bus, settings)
        finally:
            await db.close()
            await bus.close()

    asyncio.run(_main())


if __name__ == "__main__":
    app()
