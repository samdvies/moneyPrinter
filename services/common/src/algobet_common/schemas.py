"""Pydantic schemas for Redis Streams bus messages.

These mirror the contracts in docs/superpowers/specs/2026-04-18-algo-betting-design.md.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Venue(StrEnum):
    BETFAIR = "betfair"
    KALSHI = "kalshi"


class OrderSide(StrEnum):
    BACK = "back"
    LAY = "lay"
    YES = "yes"
    NO = "no"


class _BaseMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketData(_BaseMessage):
    venue: Venue
    market_id: str
    timestamp: datetime
    bids: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    asks: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    last_trade: Decimal | None = None


class OrderSignal(_BaseMessage):
    strategy_id: str
    mode: Literal["paper", "live"]
    venue: Venue
    market_id: str
    side: OrderSide
    stake: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)


class ExecutionResult(_BaseMessage):
    order_id: str
    strategy_id: str
    mode: Literal["paper", "live"]
    status: Literal["placed", "partially_filled", "filled", "cancelled", "rejected"]
    filled_stake: Decimal = Decimal("0")
    filled_price: Decimal | None = None
    timestamp: datetime


class RiskAlert(_BaseMessage):
    source: str
    severity: Literal["info", "warn", "critical"]
    message: str
    timestamp: datetime
