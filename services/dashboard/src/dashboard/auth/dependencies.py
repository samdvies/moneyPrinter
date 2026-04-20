"""FastAPI dependencies for the dashboard auth subsystem."""

from __future__ import annotations

import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from fastapi import Depends, HTTPException, Request, status

from ..dependencies import get_db, get_redis
from .csrf import validate_csrf_header, validate_origin
from .models import Operator
from .sessions import lookup_session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def require_operator(
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
    r: redis.Redis = Depends(get_redis),  # noqa: B008
) -> Operator:
    token = request.cookies.get("sess") or ""
    operator = await lookup_session(r, db, token=token)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return operator


async def require_csrf(
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    cookie = request.cookies.get("csrf")
    header = request.headers.get("X-CSRF-Token")
    if not validate_csrf_header(cookie, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="csrf token mismatch",
        )
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if not validate_origin(origin, referer, settings.dashboard_allowed_origins):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="origin not allowed",
        )
