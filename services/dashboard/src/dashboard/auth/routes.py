"""Auth routes: /auth/login, /auth/logout, /auth/me.

Login is the only route that issues session cookies. Logout is idempotent
and does not require CSRF validation. `/auth/me` is read-only and gated
only by the session cookie.
"""

from __future__ import annotations

import redis.asyncio as redis
from algobet_common.config import Settings
from algobet_common.db import Database
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from ..dependencies import get_db, get_redis
from . import crud
from .csrf import issue_csrf_token
from .dependencies import get_settings, require_operator
from .models import Operator
from .passwords import _DUMMY_HASH, hash_password, needs_rehash, verify_password
from .rate_limit import check_and_increment
from .sessions import create_session, destroy_session, get_session_operator_id

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    operator: Operator


_GENERIC_AUTH_FAILURE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="authentication failed",
)


def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


def _set_auth_cookies(
    response: Response,
    *,
    sess_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        key="sess",
        value=sess_token,
        httponly=True,
        path="/",
        max_age=settings.session_ttl_seconds,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    response.set_cookie(
        key="csrf",
        value=csrf_token,
        httponly=False,
        path="/",
        max_age=settings.session_ttl_seconds,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),  # noqa: B008
    r: redis.Redis = Depends(get_redis),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> LoginResponse:
    ip_max, ip_window = settings.login_rate_limit_ip
    email_max, email_window = settings.login_rate_limit_email
    ip_key = f"dashboard:login_rl:ip:{_client_ip(request)}"
    email_key = f"dashboard:login_rl:email:{body.email.lower()}"

    ip_ok = await check_and_increment(r, key=ip_key, max_attempts=ip_max, window_seconds=ip_window)
    email_ok = await check_and_increment(
        r, key=email_key, max_attempts=email_max, window_seconds=email_window
    )
    if not (ip_ok and email_ok):
        raise _GENERIC_AUTH_FAILURE

    record = await crud.get_operator_record_by_email(db, body.email)
    if record is None:
        # Preserve timing parity: always run verify against _something_.
        verify_password(_DUMMY_HASH, body.password)
        raise _GENERIC_AUTH_FAILURE

    if not verify_password(record["password_hash"], body.password):
        raise _GENERIC_AUTH_FAILURE

    if needs_rehash(record["password_hash"]):
        await crud.update_password(
            db,
            id=record["id"],
            old_hash=record["password_hash"],
            new_hash=hash_password(body.password),
        )

    old_token = request.cookies.get("sess")
    if old_token:
        # Only destroy the presented token if it belongs to the operator
        # who just authenticated. Otherwise an attacker could DoS another
        # operator by injecting their session cookie into a login attempt.
        existing_op_id = await get_session_operator_id(r, token=old_token)
        if existing_op_id == record["id"]:
            await destroy_session(r, token=old_token)

    sess_token = await create_session(r, settings, operator_id=record["id"])
    csrf_token = issue_csrf_token()
    _set_auth_cookies(response, sess_token=sess_token, csrf_token=csrf_token, settings=settings)

    return LoginResponse(
        operator=Operator(
            id=record["id"],
            email=record["email"],
            created_at=record["created_at"],
        )
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    r: redis.Redis = Depends(get_redis),  # noqa: B008
) -> None:
    token = request.cookies.get("sess")
    if token:
        await destroy_session(r, token=token)
    response.delete_cookie("sess", path="/")
    response.delete_cookie("csrf", path="/")


@router.get("/me", response_model=LoginResponse)
async def me(operator: Operator = Depends(require_operator)) -> LoginResponse:  # noqa: B008
    return LoginResponse(operator=operator)
