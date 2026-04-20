"""Redis-backed session store for dashboard operators.

Primary key:  `dashboard:session:<token>` → JSON `{operator_id, issued_at}`
              TTL = settings.session_ttl_seconds.
Secondary:    `dashboard:operator_sessions:<operator_id>` → SET of tokens,
              used to invalidate every session for one operator (password
              rotation via scripts/create_operator.py --rotate).
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database

from . import crud
from .models import Operator

_SESSION_KEY_FMT = "dashboard:session:{token}"
_OPERATOR_SESSIONS_KEY_FMT = "dashboard:operator_sessions:{operator_id}"


def _session_key(token: str) -> str:
    return _SESSION_KEY_FMT.format(token=token)


def _operator_sessions_key(operator_id: uuid.UUID) -> str:
    return _OPERATOR_SESSIONS_KEY_FMT.format(operator_id=operator_id)


async def create_session(
    r: redis.Redis,
    settings: Settings,
    *,
    operator_id: uuid.UUID,
) -> str:
    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "operator_id": str(operator_id),
            "issued_at": datetime.now(UTC).isoformat(),
        }
    )
    async with r.pipeline(transaction=True) as pipe:
        pipe.setex(_session_key(token), settings.session_ttl_seconds, payload)
        pipe.sadd(_operator_sessions_key(operator_id), token)
        await pipe.execute()
    return token


async def lookup_session(
    r: redis.Redis,
    db: Database,
    *,
    token: str,
) -> Operator | None:
    """Return the `Operator` for a valid session, else None.

    None covers: missing/expired Redis key, malformed JSON, or an
    `operator_id` whose row was deleted. Does NOT refresh the TTL —
    session lifetime is fixed from create.
    """
    if not token:
        return None
    raw = await r.get(_session_key(token))
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes | bytearray) else raw
        payload = json.loads(text)
        operator_id = uuid.UUID(payload["operator_id"])
    except (ValueError, KeyError, TypeError):
        return None
    return await crud.get_operator_by_id(db, operator_id)


async def destroy_session(r: redis.Redis, *, token: str) -> None:
    """Best-effort destroy: removes primary + secondary-index membership."""
    if not token:
        return
    primary = _session_key(token)
    raw = await r.get(primary)
    if raw is not None:
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes | bytearray) else raw
            payload = json.loads(text)
            operator_id = payload["operator_id"]
        except (ValueError, KeyError, TypeError):
            operator_id = None
        async with r.pipeline(transaction=True) as pipe:
            if operator_id is not None:
                pipe.srem(_OPERATOR_SESSIONS_KEY_FMT.format(operator_id=operator_id), token)
            pipe.delete(primary)
            await pipe.execute()
    else:
        await r.delete(primary)


async def destroy_all_sessions_for_operator(
    r: redis.Redis,
    *,
    operator_id: uuid.UUID,
) -> None:
    secondary = _operator_sessions_key(operator_id)
    raw_tokens: set[bytes | str] = await r.smembers(secondary)  # type: ignore[misc]
    tokens: list[str] = [
        t.decode("utf-8") if isinstance(t, bytes | bytearray) else t for t in raw_tokens
    ]
    if not tokens:
        await r.delete(secondary)
        return
    async with r.pipeline(transaction=True) as pipe:
        for t in tokens:
            pipe.delete(_session_key(t))
        pipe.delete(secondary)
        await pipe.execute()
