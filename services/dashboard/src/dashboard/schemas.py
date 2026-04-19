"""Pydantic response models for the dashboard API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    status: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    wiki_path: str | None = None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None


class StrategyRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    mode: str
    started_at: datetime
    ended_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    side: str
    stake: float
    price: float
    status: str
    created_at: datetime


class StrategyDetailOut(StrategyOut):
    recent_runs: list[StrategyRunOut] = Field(default_factory=list)
    recent_orders: list[OrderOut] = Field(default_factory=list)


class ApproveBody(BaseModel):
    approved_by: str = Field(min_length=1)


class RiskAlertOut(BaseModel):
    stream_id: str
    source: str
    severity: str
    message: str
    timestamp: datetime
