"""Pydantic DTOs mirroring the strategy registry SQL schema."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Status(StrEnum):
    """Strategy lifecycle status values. Must match the DB CHECK constraint verbatim."""

    HYPOTHESIS = "hypothesis"
    BACKTESTING = "backtesting"
    PAPER = "paper"
    AWAITING_APPROVAL = "awaiting-approval"
    LIVE = "live"
    RETIRED = "retired"


class Mode(StrEnum):
    """Strategy run mode. Note: DB uses 'backtest' (not 'backtesting') for run mode."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Strategy(BaseModel):
    id: uuid.UUID
    slug: str
    status: Status
    parameters: dict[str, Any] = Field(default_factory=dict)
    wiki_path: str | None = None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    max_exposure_gbp: Decimal = Decimal("1000")


@dataclass(frozen=True)
class LiabilityComponents:
    """Aggregated open-order components for a single (strategy, venue, market, selection) group.

    Invariant: for every distinct (venue, market_id, selection_id) present,
    get_open_liability(strategy_id) >= get_market_liability_components(...).market_liability.
    This makes projected-total arithmetic sound:
    projected_total = total_before - market_liability_before + market_liability_after.
    """

    back_stake: Decimal
    lay_stake: Decimal
    back_winnings: Decimal
    lay_liability: Decimal

    @property
    def market_liability(self) -> Decimal:
        """Worst-case loss for this selection group.

        loss_outcome = back_stake - lay_stake  (back-heavy; lay winnings offset)
        win_outcome  = lay_liability - back_winnings  (lay-heavy; back profits offset)
        market_liability = max(0, loss_outcome, win_outcome)
        """
        loss_outcome = self.back_stake - self.lay_stake
        win_outcome = self.lay_liability - self.back_winnings
        return max(Decimal("0"), loss_outcome, win_outcome)


class StrategyRun(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    mode: Mode
    started_at: datetime
    ended_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
