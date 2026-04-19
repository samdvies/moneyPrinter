"""Strategy routes: list, detail, and approval gate."""

from __future__ import annotations

import uuid

import strategy_registry.crud as crud
from algobet_common.db import Database
from fastapi import APIRouter, Depends, HTTPException
from strategy_registry.errors import (
    ApprovalRequiredError,
    InvalidTransitionError,
    StrategyNotFoundError,
)
from strategy_registry.models import Status

from ..dependencies import get_db
from ..schemas import ApproveBody, OrderOut, StrategyDetailOut, StrategyOut, StrategyRunOut

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/", response_model=list[StrategyOut])
async def list_strategies(db: Database = Depends(get_db)) -> list[StrategyOut]:  # noqa: B008
    strategies = await crud.list_strategies(db)
    return [StrategyOut.model_validate(s) for s in strategies]


@router.get("/{strategy_id}", response_model=StrategyDetailOut)
async def get_strategy(
    strategy_id: uuid.UUID,
    db: Database = Depends(get_db),  # noqa: B008
) -> StrategyDetailOut:
    try:
        strategy = await crud.get_strategy(db, strategy_id)
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async with db.acquire() as conn:
        run_rows = await conn.fetch(
            """
            SELECT * FROM strategy_runs
             WHERE strategy_id = $1
             ORDER BY started_at DESC
             LIMIT 10
            """,
            strategy_id,
        )
        order_rows = await conn.fetch(
            """
            SELECT * FROM orders
             WHERE strategy_id = $1
             ORDER BY created_at DESC
             LIMIT 20
            """,
            strategy_id,
        )

    recent_runs = [StrategyRunOut.model_validate(dict(r)) for r in run_rows]
    recent_orders = [OrderOut.model_validate(dict(r)) for r in order_rows]

    return StrategyDetailOut(
        **StrategyOut.model_validate(strategy).model_dump(),
        recent_runs=recent_runs,
        recent_orders=recent_orders,
    )


@router.post("/{strategy_id}/approve", response_model=StrategyOut)
async def approve_strategy(
    strategy_id: uuid.UUID,
    body: ApproveBody,
    db: Database = Depends(get_db),  # noqa: B008
) -> StrategyOut:
    # TODO(auth): this route is the live-capital gate; protect with operator authentication before production use  # noqa: E501
    try:
        updated = await crud.transition(db, strategy_id, Status.LIVE, approved_by=body.approved_by)
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTransitionError, ApprovalRequiredError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return StrategyOut.model_validate(updated)
