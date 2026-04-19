"""Pydantic DTOs mirroring the strategy registry SQL schema."""

from __future__ import annotations

import uuid
from datetime import datetime
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


class StrategyRun(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    mode: Mode
    started_at: datetime
    ended_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
