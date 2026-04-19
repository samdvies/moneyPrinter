"""Pydantic schemas for research orchestrator bus messages."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResearchEvent(BaseModel):
    """Published to Topic.RESEARCH_EVENTS after a successful strategy transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    strategy_id: str
    from_status: str
    to_status: str
    timestamp: datetime
