"""Thin async wrapper around Redis Streams for service-to-service messaging.

The bus is the only path between services. Every service constructs one
BusClient with its service_name; publish() emits to a topic, consume()
reads via consumer-group semantics so multiple replicas share work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import TypeVar

import redis.asyncio as redis
from pydantic import BaseModel


class Topic(StrEnum):
    MARKET_DATA = "market.data"
    ORDER_SIGNALS = "order.signals"
    ORDER_SIGNALS_APPROVED = "order.signals.approved"
    EXECUTION_RESULTS = "execution.results"
    RESEARCH_EVENTS = "research.events"
    RISK_ALERTS = "risk.alerts"


M = TypeVar("M", bound=BaseModel)


class BusClient:
    def __init__(self, url: str, service_name: str) -> None:
        self._url = url
        self._service = service_name
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("BusClient not connected — call connect() first")
        return self._client

    async def publish(self, topic: Topic, message: BaseModel) -> str:
        client = self._require()
        payload = {"json": message.model_dump_json()}
        return await client.xadd(topic.value, payload)

    async def _ensure_group(self, topic: Topic) -> None:
        client = self._require()
        try:
            await client.xgroup_create(
                name=topic.value,
                groupname=self._service,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self,
        topic: Topic,
        model: type[M],
        count: int = 10,
        block_ms: int = 5000,
    ) -> AsyncIterator[M]:
        """Yield parsed messages from topic. Exits after one XREADGROUP batch."""
        client = self._require()
        await self._ensure_group(topic)
        consumer = f"{self._service}-0"
        response = await client.xreadgroup(
            groupname=self._service,
            consumername=consumer,
            streams={topic.value: ">"},
            count=count,
            block=block_ms,
        )
        if not response:
            return
        for _stream, entries in response:
            for entry_id, fields in entries:
                try:
                    yield model.model_validate_json(fields["json"])
                finally:
                    await client.xack(topic.value, self._service, entry_id)
