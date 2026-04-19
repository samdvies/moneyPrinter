"""Async CRUD operations for the strategy registry.

All state transitions go through `transition()`. No other function in this
module may write `status` directly. This is the single enforcement point for
the lifecycle gate.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from algobet_common.db import Database

from .errors import StrategyNotFoundError
from .models import Mode, Status, Strategy, StrategyRun
from .transitions import validate_transition


def _parse_jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)  # type: ignore[no-any-return]
    return dict(value)


def _row_to_strategy(row: Any) -> Strategy:
    return Strategy(
        id=row["id"],
        slug=row["slug"],
        status=Status(row["status"]),
        parameters=_parse_jsonb(row["parameters"]),
        wiki_path=row["wiki_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        max_exposure_gbp=row["max_exposure_gbp"],
    )


def _row_to_run(row: Any) -> StrategyRun:
    return StrategyRun(
        id=row["id"],
        strategy_id=row["strategy_id"],
        mode=Mode(row["mode"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        metrics=_parse_jsonb(row["metrics"]),
    )


async def create_strategy(
    db: Database,
    *,
    slug: str,
    parameters: dict[str, Any] | None = None,
    wiki_path: str | None = None,
) -> Strategy:
    """Insert a new strategy in 'hypothesis' status."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO strategies (slug, status, parameters, wiki_path)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING *
            """,
            slug,
            Status.HYPOTHESIS.value,
            json.dumps(parameters or {}),
            wiki_path,
        )
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _row_to_strategy(row)


async def get_strategy(db: Database, strategy_id: uuid.UUID) -> Strategy:
    """Fetch a single strategy by ID."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM strategies WHERE id = $1",
            strategy_id,
        )
    if row is None:
        raise StrategyNotFoundError(f"Strategy {strategy_id} not found")
    return _row_to_strategy(row)


async def list_strategies(
    db: Database,
    *,
    status: Status | None = None,
) -> list[Strategy]:
    """List strategies, optionally filtered by status."""
    async with db.acquire() as conn:
        if status is not None:
            rows = await conn.fetch(
                "SELECT * FROM strategies WHERE status = $1 ORDER BY created_at",
                status.value,
            )
        else:
            rows = await conn.fetch("SELECT * FROM strategies ORDER BY created_at")
    return [_row_to_strategy(r) for r in rows]


async def transition(
    db: Database,
    strategy_id: uuid.UUID,
    to_status: Status | str,
    *,
    approved_by: str | None = None,
) -> Strategy:
    """Transition a strategy to a new lifecycle status.

    Enforces the lifecycle gate:
    - Validates the edge in the pure transitions module first (fast-fail).
    - Opens a transaction, locks the row with SELECT FOR UPDATE to guard
      against TOCTOU races, re-validates with the locked current status,
      then performs the UPDATE.
    - When transitioning to 'live', atomically sets approved_by + approved_at.

    Raises:
        StrategyNotFoundError: strategy does not exist.
        InvalidTransitionError: transition not allowed from current status.
        ApprovalRequiredError: 'live' requires non-empty approved_by.
    """
    to_status = Status(to_status)

    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM strategies WHERE id = $1 FOR UPDATE",
            strategy_id,
        )
        if row is None:
            raise StrategyNotFoundError(f"Strategy {strategy_id} not found")

        current_status = Status(row["status"])
        # Re-validate under the lock (TOCTOU guard)
        validate_transition(current_status, to_status, approved_by=approved_by)

        if to_status == Status.LIVE:
            updated = await conn.fetchrow(
                """
                UPDATE strategies
                   SET status      = $1,
                       approved_by = $2,
                       approved_at = $3,
                       updated_at  = $3
                 WHERE id = $4
                 RETURNING *
                """,
                to_status.value,
                approved_by,
                datetime.now(UTC),
                strategy_id,
            )
        else:
            updated = await conn.fetchrow(
                """
                UPDATE strategies
                   SET status     = $1,
                       updated_at = $2
                 WHERE id = $3
                 RETURNING *
                """,
                to_status.value,
                datetime.now(UTC),
                strategy_id,
            )

    if updated is None:
        raise RuntimeError("UPDATE returned no row")
    return _row_to_strategy(updated)


async def start_run(
    db: Database,
    strategy_id: uuid.UUID,
    mode: Mode | str,
    *,
    metrics: dict[str, Any] | None = None,
) -> StrategyRun:
    """Create a new strategy run record."""
    mode = Mode(mode)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO strategy_runs (strategy_id, mode, metrics)
            VALUES ($1, $2, $3::jsonb)
            RETURNING *
            """,
            strategy_id,
            mode.value,
            json.dumps(metrics or {}),
        )
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _row_to_run(row)


async def end_run(
    db: Database,
    run_id: uuid.UUID,
    *,
    metrics: dict[str, Any] | None = None,
) -> StrategyRun:
    """Mark a strategy run as ended, optionally updating metrics."""
    now = datetime.now(UTC)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE strategy_runs
               SET ended_at = $1,
                   metrics  = COALESCE($2::jsonb, metrics)
             WHERE id = $3
             RETURNING *
            """,
            now,
            json.dumps(metrics) if metrics is not None else None,
            run_id,
        )
    if row is None:
        raise RuntimeError("UPDATE returned no row — run_id not found")
    return _row_to_run(row)
