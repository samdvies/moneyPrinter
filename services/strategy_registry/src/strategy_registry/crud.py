"""Async CRUD operations for the strategy registry.

All state transitions go through `transition()`. No other function in this
module may write `status` directly. This is the single enforcement point for
the lifecycle gate.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from algobet_common.db import Database

from .errors import StrategyNotFoundError
from .models import LiabilityComponents, Mode, Status, Strategy, StrategyRun
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


async def upsert_strategy(
    db: Database,
    *,
    slug: str,
    parameters: dict[str, Any],
    wiki_path: str,
) -> Strategy:
    """Insert a new strategy or update parameters/wiki_path on an existing slug.

    On a fresh slug, inserts a row at ``status='hypothesis'`` — identical shape
    to ``create_strategy``. On an existing slug, updates ``parameters``,
    ``wiki_path`` and ``updated_at`` only. **Never** touches ``status``: the
    lifecycle state machine (``transition``) owns that column and loading a
    wiki file must not clobber a strategy that has already advanced.

    Used by ``wiki_loader.load_strategy_from_wiki`` so re-reading a wiki file
    is idempotent.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO strategies (slug, status, parameters, wiki_path)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (slug) DO UPDATE
               SET parameters = EXCLUDED.parameters,
                   wiki_path  = EXCLUDED.wiki_path,
                   updated_at = now()
            RETURNING *
            """,
            slug,
            Status.HYPOTHESIS.value,
            json.dumps(parameters),
            wiki_path,
        )
    if row is None:
        raise RuntimeError("UPSERT returned no row")
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


async def get_open_liability(db: Database, strategy_id: uuid.UUID) -> Decimal:
    """Return the total open liability for a strategy across all markets.

    Queries the open_order_liability view and sums market_liability per selection group.
    Returns Decimal("0") when there are no open orders.

    Invariant: for every distinct (v, m, s) in open orders,
    get_open_liability >= get_market_liability_components(...).market_liability.
    This makes projected-total arithmetic in check_exposure sound.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT back_stake, lay_stake, back_winnings, lay_liability
            FROM open_order_liability
            WHERE strategy_id = $1
            """,
            strategy_id,
        )
    total = Decimal("0")
    for row in rows:
        components = LiabilityComponents(
            back_stake=Decimal(str(row["back_stake"])),
            lay_stake=Decimal(str(row["lay_stake"])),
            back_winnings=Decimal(str(row["back_winnings"])),
            lay_liability=Decimal(str(row["lay_liability"])),
        )
        total += components.market_liability
    return total


async def get_market_liability_components(
    db: Database,
    strategy_id: uuid.UUID,
    venue: str,
    market_id: str,
    selection_id: str | None,
) -> LiabilityComponents:
    """Return aggregated liability components for a (strategy, venue, market, selection) group.

    When selection_id is None (legacy Kalshi or unidentified signals), no existing
    NULL-selection rows will match (stored as 'order:<uuid>'). A fresh signal with
    selection_id=None on a market with no historical orders returns zero components.

    Returns zero-valued LiabilityComponents when no open orders match.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT back_stake, lay_stake, back_winnings, lay_liability
            FROM open_order_liability
            WHERE strategy_id = $1
              AND venue = $2
              AND market_id = $3
              AND selection_id_key = COALESCE($4, '__none__')
            """,
            strategy_id,
            venue,
            market_id,
            selection_id,
        )
    if row is None:
        return LiabilityComponents(
            back_stake=Decimal("0"),
            lay_stake=Decimal("0"),
            back_winnings=Decimal("0"),
            lay_liability=Decimal("0"),
        )
    return LiabilityComponents(
        back_stake=Decimal(str(row["back_stake"])),
        lay_stake=Decimal(str(row["lay_stake"])),
        back_winnings=Decimal(str(row["back_winnings"])),
        lay_liability=Decimal(str(row["lay_liability"])),
    )
