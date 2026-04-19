"""Risk alert route: tail recent alerts from Redis Streams."""

from __future__ import annotations

import redis.asyncio as redis
from algobet_common.bus import Topic
from algobet_common.schemas import RiskAlert
from fastapi import APIRouter, Depends, Query

from ..dependencies import get_redis
from ..schemas import RiskAlertOut

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/alerts", response_model=list[RiskAlertOut])
async def get_risk_alerts(
    count: int = Query(default=20, ge=1, le=500),
    redis_client: redis.Redis = Depends(get_redis),  # noqa: B008
) -> list[RiskAlertOut]:
    response = await redis_client.xread(
        streams={Topic.RISK_ALERTS.value: "0"},
        count=count,
    )
    if not response:
        return []

    results: list[RiskAlertOut] = []
    for _stream, entries in response:
        for entry_id, fields in entries:
            alert = RiskAlert.model_validate_json(fields["json"])
            results.append(
                RiskAlertOut(
                    stream_id=entry_id,
                    source=alert.source,
                    severity=alert.severity,
                    message=alert.message,
                    timestamp=alert.timestamp,
                )
            )
    return results
