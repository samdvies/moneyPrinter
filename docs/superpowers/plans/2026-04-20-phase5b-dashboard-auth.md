# Phase 5b — Dashboard Auth and Operator Identity

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **Promotion-gate skill:** The `approve_strategy` route is the live-capital gate. Invoke `promotion-gate-auditor` before merging Task 5 (the route change) and before any strategy-registry state-transition code is edited.

**Goal:** Replace the unauthenticated `approve_strategy` route — which currently trusts a client-supplied `approved_by` string — with a cookie-session login flow backed by a single-operator `operators` table. After this phase, the value written to `strategies.approved_by` is the **server-side authenticated operator's email**, not a request body field. All dashboard write endpoints require an authenticated session; reads remain open (local-network deployment assumption).

**Architecture:** Small, opinionated single-operator model. New `operators` table (`0004_operators.sql`), argon2id password hashing (`argon2-cffi`), opaque session tokens in Redis (`SETEX` with configurable TTL), double-submit CSRF cookie for state-changing requests, and a FastAPI dependency `require_operator` that resolves the session cookie to an `Operator` row. A CLI bootstrap script (`scripts/create_operator.py`) is the only way to create the first account — no self-registration.

**Tech Stack:** Python 3.12, FastAPI, `algobet_common`, `asyncpg`, `redis.asyncio`, `argon2-cffi`, `pytest`, `pytest-asyncio`, `httpx.AsyncClient`. SQL: PostgreSQL ≥ 13.

---

## Scope and Constraints

- **In scope:**
  - Migration `0004_operators.sql`: `operators(id uuid pk, email text unique not null citext, password_hash text not null, created_at timestamptz default now())`. The `email` column uses `citext` so lookup is case-insensitive.
  - Dependency: add `argon2-cffi ^23` to the workspace `pyproject.toml`.
  - New package module `services/dashboard/src/dashboard/auth/` containing:
    - `passwords.py` — argon2id hasher wrapper (`hash_password`, `verify_password`, `needs_rehash`).
    - `sessions.py` — Redis-backed session store (`create_session`, `lookup_session`, `destroy_session`, `destroy_all_sessions_for_operator`).
    - `crud.py` — operator CRUD helpers (`get_operator_by_email`, `get_operator_by_id`, `create_operator`, `update_password`).
    - `csrf.py` — double-submit cookie helpers (`issue_csrf_token`, `validate_csrf_header`).
    - `models.py` — `Operator` pydantic model.
    - `dependencies.py` — `require_operator` FastAPI dependency + `require_csrf` dependency.
    - `routes.py` — `/auth/login`, `/auth/logout`, `/auth/me` FastAPI router.
  - Bootstrap script: `scripts/create_operator.py` — invoked via `uv run python -m scripts.create_operator --email X`; prompts interactively for a password (hidden input, typed twice).
  - Wire the new router into `dashboard.app.create_app()`.
  - Gate `POST /strategies/{id}/approve` behind `require_operator` + `require_csrf`; **delete** `ApproveBody.approved_by` and pass `operator.email` straight to `crud.transition(..., approved_by=operator.email)`.
  - Settings additions in `algobet_common.config.Settings`:
    - `session_ttl_seconds: int = 28800`
    - `cookie_secure: bool = True` — **fail-closed default**. Tests opt out via `COOKIE_SECURE=false` in the test fixture env, never in the shipped default. (S1-b)
    - `cookie_samesite: Literal["lax","strict"] = "lax"`
    - `dashboard_allowed_origins: list[str] = []` — **fail-closed default**. Operator must set `DASHBOARD_ALLOWED_ORIGINS` explicitly; startup raises if empty. Consulted by `require_csrf` for Origin/Referer validation. (S1-a)
    - `login_rate_limit_ip: tuple[int, int] = (5, 300)` — `(max_attempts, window_seconds)` keyed by source IP. Default: 5 attempts per 5 minutes.
    - `login_rate_limit_email: tuple[int, int] = (10, 900)` — keyed by lowercased email. Default: 10 attempts per 15 minutes. (S1-c)
  - Unit and integration tests per the task breakdown.
  - Update `wiki/20-Risk/open-debts.md` with three residual threats (MFA, rate-limit, audit log) — these are explicitly deferred.

- **Out of scope:**
  - Multi-operator / RBAC — single account only. A future phase can add roles.
  - Password reset flow (self-service). The only path is re-running `scripts/create_operator.py --rotate`.
  - Account lockout / rate-limit on `/auth/login`. Tracked in debt ledger.
  - MFA / WebAuthn. Tracked in debt ledger.
  - API tokens / bearer-token access for non-browser clients. Cookie only.
  - Audit log beyond `approved_by`. Tracked.
  - HTTPS / TLS — assume a reverse proxy terminates TLS; `cookie_secure=True` is the operator's config burden.
  - Gating read endpoints (`GET /strategies/`, `GET /risk/alerts`) — deferred; local-network assumption holds.

- **Safety invariants:**
  - `crud.transition(..., approved_by=X)` MUST be called with `operator.email`, never with a client-supplied value. The Pydantic request body for `approve_strategy` MUST NOT contain an `approved_by` field after this phase.
  - Session tokens MUST be created with `secrets.token_urlsafe(32)` (≥ 256-bit entropy) and stored in Redis as opaque keys — never encoded JWTs.
  - Session cookies MUST be `HttpOnly=True`, `SameSite` per setting, `Secure` per setting. CSRF cookies MUST be `HttpOnly=False` (so JS can read) and **not** marked `Secure` in dev.
  - Password hashes MUST use argon2id via `argon2-cffi`'s `PasswordHasher` with library defaults (memory_cost=65536 KiB, time_cost=3, parallelism=4). Rehash on login if `needs_rehash(hash)` returns True.
  - `lookup_session` MUST refuse to return an `Operator` for a token that is missing, expired, or whose stored `operator_id` has no matching row.
  - On successful login, any previous session for the same operator is **not** destroyed (multiple concurrent browser sessions are allowed). On password change via `scripts/create_operator.py --rotate`, all sessions for that operator are destroyed via `destroy_all_sessions_for_operator`.
  - Session TTL is enforced server-side via `SETEX`. The session cookie's client-side `max_age` must match `session_ttl_seconds` exactly.
  - The login handler MUST return the same generic error message + same response time for "user does not exist" and "wrong password". No timing-oracle or user-enumeration leaks. Call `PasswordHasher.verify` against a known dummy hash when the user row is missing.
  - CSRF defence is **layered**: (a) `X-CSRF-Token` header equals `csrf` cookie via `hmac.compare_digest`; (b) `Origin` header (falling back to `Referer`) is in `settings.dashboard_allowed_origins`. Both checks must pass — this closes the cookie-tossing weakness of naïve double-submit (OWASP CSRF Prevention Cheat Sheet, "Disallowed Patterns"). Missing / mismatched on **either** check → 403. (S1-a)
  - `require_operator` is declared **before** `require_csrf` in gated route signatures so a missing session returns 401 (authentication required) in preference to 403 (CSRF mismatch). FastAPI evaluates dependencies in declaration order. (S3-a)
  - Login route is the **only** route that rotates the session token. No session fixation: if a client presents a pre-auth `sess` cookie — whether garbage or a valid token belonging to another operator — login issues a fresh token, and only the old token *that was presented* is invalidated. Other valid sessions for that other operator remain valid (concurrent sessions are allowed per earlier invariant).
  - Login rate-limit is enforced in front of password verification — even a malformed request counts. Keys: `dashboard:login_rl:ip:<ip>` and `dashboard:login_rl:email:<lower(email)>`. Fixed-window via `INCR` + `EXPIRE NX`. On breach, return 429 with the generic auth failure message body (do not leak that the limit exists — mirrors OWASP "generic failure" guidance). (S1-c)
  - Redis key namespace: `dashboard:session:<token>` → JSON `{"operator_id": "...", "issued_at": "..."}`. Distinct from any other Redis key used elsewhere in the system to avoid accidental collision.
  - Argon2 dummy hash for the "user not found" branch must be generated **once at import time** (module-level constant); never regenerated per request.

## Data Model

Migration `scripts/db/migrations/0004_operators.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE operators (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email citext UNIQUE NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_password_change_at timestamptz NOT NULL DEFAULT now()
);
```

No changes to `strategies`. `approved_by` remains `text` and receives the operator's email string — FK to `operators.email` is deliberately **not** added so that historical values (`"test-automation"`, `"bootstrap"`) remain valid.

## Session Storage Contract

```
Key:     dashboard:session:<token>
Value:   JSON {"operator_id": uuid_str, "issued_at": iso8601_str}
TTL:     settings.session_ttl_seconds (default 28800 = 8 h)
```

Secondary index for `destroy_all_sessions_for_operator`:

```
Key:     dashboard:operator_sessions:<operator_id>
Type:    SET of session tokens
TTL:     none (pruned opportunistically on lookup)
```

On `create_session`, both the primary key and a `SADD` to the secondary index are written inside a single `MULTI/EXEC`. On `destroy_session`, `DEL` primary + `SREM` secondary. On `destroy_all_sessions_for_operator`, iterate the SET, `DEL` each primary, then `DEL` the SET.

## File Responsibilities

- `scripts/db/migrations/0004_operators.sql` — additive migration per Data Model.
- `services/common/src/algobet_common/config.py` — add the three new settings with defaults as above.
- `services/dashboard/src/dashboard/auth/__init__.py` — re-exports.
- `services/dashboard/src/dashboard/auth/passwords.py` — `PasswordHasher` singleton, `hash_password`, `verify_password`, `needs_rehash`, module-level `_DUMMY_HASH`.
- `services/dashboard/src/dashboard/auth/sessions.py` — token creation + Redis I/O. All functions take a `redis.asyncio.Redis` + `Settings`. Return types are `str` (token) / `Operator | None` / `None`.
- `services/dashboard/src/dashboard/auth/crud.py` — thin DB helpers over `operators`. `get_operator_by_email(db, email) -> Operator | None`, `get_operator_by_id(db, id) -> Operator | None`, `create_operator(db, *, email, password_hash)`, `update_password(db, *, id, password_hash)`.
- `services/dashboard/src/dashboard/auth/csrf.py` — `issue_csrf_token() -> str`, `validate_csrf_header(cookie_value: str | None, header_value: str | None) -> bool` (constant-time equality; False on any None), `validate_origin(origin: str | None, referer: str | None, allowed: list[str]) -> bool` (exact match on scheme+host+port; True only if Origin OR Referer matches the allow-list).
- `services/dashboard/src/dashboard/auth/rate_limit.py` — fixed-window Redis counter helpers: `async def check_and_increment(redis, *, key: str, max_attempts: int, window_seconds: int) -> bool` (returns False = limit exceeded). Uses `INCR` + `EXPIRE NX` atomically.
- `services/dashboard/src/dashboard/auth/models.py` — frozen Pydantic `Operator(id, email, created_at)`. No `password_hash` in the public model.
- `services/dashboard/src/dashboard/auth/dependencies.py`:
  - `async def require_operator(request: Request, db=Depends(get_db), redis=Depends(get_redis)) -> Operator` — reads `sess` cookie, calls `lookup_session`, 401 on miss.
  - `async def require_csrf(request: Request, settings=Depends(get_settings)) -> None` — validates BOTH `validate_csrf_header(cookie, header)` AND `validate_origin(origin, referer, settings.dashboard_allowed_origins)`; 403 on either miss. (S1-a)
- `services/dashboard/src/dashboard/auth/routes.py`:
  - `POST /auth/login` — body `{email, password}`; sets `sess` + `csrf` cookies on success; returns `{operator: Operator}`. Generic 401 on any failure.
  - `POST /auth/logout` — requires `sess` cookie (not `require_csrf` — logout is idempotent and a safe GET/POST); clears cookies, destroys the session in Redis.
  - `GET /auth/me` — requires `require_operator`; returns `{operator: Operator}`.
- `services/dashboard/src/dashboard/app.py` — include the auth router.
- `services/dashboard/src/dashboard/schemas.py` — **remove** `approved_by` from `ApproveBody`. If `ApproveBody` becomes empty, delete it and change the route to accept no body (FastAPI: `async def approve_strategy(strategy_id: uuid.UUID, db=..., operator=Depends(require_operator), _csrf=Depends(require_csrf))`).
- `services/dashboard/src/dashboard/routers/strategies.py` — remove the `TODO(auth)` comment, add the two dependencies to `approve_strategy`, pass `operator.email` into `crud.transition`.
- `scripts/create_operator.py` — interactive bootstrap. Two modes:
  - Default: create. Fails if email exists.
  - `--rotate`: update password of an existing account. Destroys all sessions for that operator.
- `services/dashboard/tests/conftest.py` — new fixtures: `operator_factory` (creates an operator row), `auth_client` (issues a real login and returns an `httpx.AsyncClient` with cookies set), `csrf_header` (reads the `csrf` cookie from the client's jar and returns `{"X-CSRF-Token": value}`).
- `services/dashboard/tests/test_auth.py` — new file: auth route tests (login happy path, login wrong password, login unknown email, login timing-equality smoke, logout, session expiry, `/auth/me`).
- `services/dashboard/tests/test_routes.py` — update existing approve tests to use `auth_client`; add CSRF-missing test; add unauthenticated-approve-returns-401 test; assert `approved_by == operator.email`.
- `wiki/20-Risk/open-debts.md` — append three new debts as per "Open Dependencies" below.

## Task Breakdown

### Task 1 — Migration 0004, settings, and `Operator` model

**Files:**
- Create: `scripts/db/migrations/0004_operators.sql`
- Modify: `services/common/src/algobet_common/config.py`
- Create: `services/dashboard/src/dashboard/auth/__init__.py` (empty placeholder)
- Create: `services/dashboard/src/dashboard/auth/models.py`
- Modify: root `pyproject.toml` (add `argon2-cffi`) and `services/dashboard/pyproject.toml` if deps are declared there

- [ ] Write `0004_operators.sql` per Data Model section. Enable `citext` extension with `IF NOT EXISTS`.
- [ ] Add `session_ttl_seconds`, `cookie_secure`, `cookie_samesite` to `Settings`. Import `Literal` from `typing`.
- [ ] Add `argon2-cffi ~= 23.1` to the appropriate `pyproject.toml` (align with where other runtime deps live — likely root workspace `pyproject.toml`). Run `uv sync`.
- [ ] Create `Operator` pydantic model with fields `id: uuid.UUID`, `email: str`, `created_at: datetime`. Frozen. `ConfigDict(from_attributes=True)` so it can accept asyncpg Records.
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate`.
- [ ] Verify: `docker compose exec postgres psql -U algobet -d algobet -c "\d operators"` shows the five columns, `citext` type on `email`, unique index on `email`.
- [ ] Run `uv run mypy services/common services/dashboard` and `uv run ruff check services/common services/dashboard`. Both green.
- [ ] Commit: `feat(dashboard): migration 0004 operators table + auth settings scaffold`

### Task 2 — Password hashing + operator CRUD (pure)

**Files:**
- Create: `services/dashboard/src/dashboard/auth/passwords.py`
- Create: `services/dashboard/src/dashboard/auth/crud.py`
- Create: `services/dashboard/tests/test_auth_passwords.py` (unit-tagged)
- Create: `services/dashboard/tests/test_auth_crud.py` (integration-tagged)

- [ ] `passwords.py`: instantiate a module-level `PasswordHasher()` from `argon2.PasswordHasher`. Expose:
  - `hash_password(plain: str) -> str`
  - `verify_password(hashed: str, plain: str) -> bool` — wraps `PasswordHasher.verify`, returns False on `argon2.exceptions.VerifyMismatchError` or `InvalidHashError`; re-raises all other exceptions.
  - `needs_rehash(hashed: str) -> bool`
  - Module-level `_DUMMY_HASH` = `hash_password(secrets.token_hex(16))` computed at import time, referenced by the login handler's "user not found" branch.
- [ ] Unit tests for `passwords.py`:
  - `test_hash_and_verify_roundtrip` — hash P, verify returns True.
  - `test_verify_wrong_password` — verify against wrong plain returns False (not raises).
  - `test_verify_malformed_hash` — verify against `"not-a-hash"` returns False.
  - `test_needs_rehash_default_params` — hash produced by default `PasswordHasher` returns False from `needs_rehash`.
  - `test_dummy_hash_is_stable` — `_DUMMY_HASH` has the argon2id prefix (`$argon2id$`).
- [ ] `crud.py`: five async helpers against `operators`. All take `db: Database` as first positional. Use `db.acquire()` + `fetchrow` pattern matching `strategy_registry.crud`. Return `Operator | None` or `None` consistently. `create_operator` raises `asyncpg.UniqueViolationError` on duplicate email — let it propagate (the CLI script catches it). Helpers:
  - `get_operator_by_email(db, email) -> Operator | None`
  - `get_operator_by_id(db, id) -> Operator | None`
  - `get_operator_record_by_email(db, email) -> _OperatorRecord | None` — internal TypedDict including `password_hash`. Used by the login handler only. Keeps the public `Operator` model hash-free.
  - `create_operator(db, *, email, password_hash) -> Operator`
  - `update_password(db, *, id, old_hash, new_hash) -> bool` — compare-and-swap: `UPDATE operators SET password_hash=$new, last_password_change_at=now() WHERE id=$1 AND password_hash=$old`. Returns True if exactly one row was updated; False if the CAS failed (concurrent rehash won, or hash moved out from under us). Losing the CAS is **not** an error — the other writer already rehashed. (S2-c)
- [ ] Integration tests for `crud.py` (pytest marker `integration`):
  - `test_create_and_get_by_email`
  - `test_get_by_email_case_insensitive` — create with `"OP@X.com"`, fetch by `"op@x.COM"`.
  - `test_duplicate_email_raises`
  - `test_update_password_cas_success_changes_hash_and_bumps_last_password_change_at` — pass the current hash as `old_hash`, assert returns True.
  - `test_update_password_cas_failure_returns_false_without_change` — pass a wrong `old_hash`, assert returns False and row is unchanged.
  - `test_get_by_id_missing_returns_none`
  - Each test cleans up the row it created in a `finally` / fixture teardown.
- [ ] Run `uv run pytest services/dashboard/tests/test_auth_passwords.py -v -m unit` — green.
- [ ] Run `uv run pytest services/dashboard/tests/test_auth_crud.py -v -m integration` — green.
- [ ] Run `uv run mypy services/dashboard/src` and `uv run ruff check services/dashboard`. Green.
- [ ] Commit: `feat(dashboard): argon2id password hashing + operator CRUD`

### Task 3 — Redis-backed session store + CSRF helpers + rate limiter

**Files:**
- Create: `services/dashboard/src/dashboard/auth/sessions.py`
- Create: `services/dashboard/src/dashboard/auth/csrf.py`
- Create: `services/dashboard/src/dashboard/auth/rate_limit.py`
- Create: `services/dashboard/tests/test_auth_sessions.py` (integration-tagged, needs Redis)
- Create: `services/dashboard/tests/test_auth_csrf.py` (unit-tagged)
- Create: `services/dashboard/tests/test_auth_rate_limit.py` (integration-tagged, needs Redis)

- [ ] `sessions.py` exposes four async functions, all taking a `redis.asyncio.Redis` + `Settings`:
  - `create_session(redis, settings, *, operator_id: uuid.UUID) -> str` — mints a `secrets.token_urlsafe(32)` token, `SETEX` the primary key with the JSON payload, `SADD` the secondary index. Returns the token.
  - `lookup_session(redis, db, *, token: str) -> Operator | None` — `GET` the primary key, decode JSON, call `crud.get_operator_by_id`. Returns None if the key is missing, JSON decode fails, or the operator row has been deleted. Does **not** refresh TTL — a cookie used for 8 consecutive hours then goes stale is correct.
  - `destroy_session(redis, *, token: str) -> None` — reads `operator_id` from the value (best-effort) to `SREM`, then `DEL`s the primary.
  - `destroy_all_sessions_for_operator(redis, *, operator_id: uuid.UUID) -> None` — iterates the secondary SET, `DEL`s each primary, `DEL`s the SET.
- [ ] Key-namespace constants as module-level strings: `_SESSION_KEY_FMT = "dashboard:session:{token}"`, `_OPERATOR_SESSIONS_KEY_FMT = "dashboard:operator_sessions:{operator_id}"`.
- [ ] Integration tests for `sessions.py` (use a real Redis container from the existing fixtures; each test flushes the two key namespaces):
  - `test_create_then_lookup_returns_operator`
  - `test_lookup_missing_token_returns_none`
  - `test_lookup_respects_ttl` — use `settings.session_ttl_seconds = 1`, sleep 1.5 s, expect None. Mark test `@pytest.mark.slow` or accept the 1.5 s cost.
  - `test_lookup_returns_none_when_operator_deleted`
  - `test_destroy_session_removes_primary_and_secondary`
  - `test_destroy_all_sessions_for_operator_affects_only_that_operator` — two operators, two sessions each; destroy one operator's → other's sessions remain valid.
- [ ] `csrf.py` exposes:
  - `issue_csrf_token() -> str` — `secrets.token_urlsafe(32)`.
  - `validate_csrf_header(cookie_value: str | None, header_value: str | None) -> bool` — returns False if either is None/empty; otherwise `hmac.compare_digest(cookie_value, header_value)`.
  - `validate_origin(origin: str | None, referer: str | None, allowed: list[str]) -> bool` — returns True if `origin` appears in `allowed` OR (origin is None and `referer` starts with one of the allowed origins + `/`); otherwise False. Normalises trailing slashes. Exact scheme+host+port match is required.
- [ ] Unit tests for `csrf.py`:
  - `validate_csrf_header`: happy path, mismatch, either-None, both-None, empty-string.
  - `validate_origin`: matching Origin, matching Referer-no-Origin (CSRF from fetch without Origin header), both None, Origin on a different port, Origin scheme mismatch (`http://` vs `https://`), Referer with path suffix after an allowed origin.
- [ ] `rate_limit.py` exposes `async def check_and_increment(redis, *, key, max_attempts, window_seconds) -> bool`:
  - Atomic via pipeline: `INCR key` then `EXPIRE key window_seconds NX`. Returns `True` if the current count ≤ `max_attempts`, else `False`.
  - Pure function; no application-specific keys — the caller supplies the full namespaced key.
- [ ] Integration tests for `rate_limit.py` (needs Redis):
  - `test_increment_under_limit_returns_true`
  - `test_increment_at_limit_returns_false`
  - `test_window_expiry_resets_counter` — set `window_seconds=1`, exhaust, sleep 1.1 s, expect True again. Accept the small sleep cost.
  - `test_concurrent_increments_race_safe` — spawn 20 concurrent `check_and_increment` calls with limit=10; assert exactly 10 return True.
- [ ] Run `uv run pytest services/dashboard/tests/test_auth_sessions.py services/dashboard/tests/test_auth_rate_limit.py -v -m integration`. Green.
- [ ] Run `uv run pytest services/dashboard/tests/test_auth_csrf.py -v -m unit`. Green.
- [ ] Run `uv run mypy services/dashboard/src` and `uv run ruff check services/dashboard`. Green.
- [ ] Commit: `feat(dashboard): redis session store + csrf helpers (origin+double-submit) + login rate limiter`

### Task 4 — Auth routes + dependencies

**Files:**
- Create: `services/dashboard/src/dashboard/auth/dependencies.py`
- Create: `services/dashboard/src/dashboard/auth/routes.py`
- Modify: `services/dashboard/src/dashboard/app.py`
- Create: `services/dashboard/tests/test_auth_routes.py` (integration-tagged)

- [ ] `dependencies.py`:
  - `async def require_operator(request, db, redis) -> Operator` — reads `request.cookies.get("sess")`; if absent or `lookup_session` returns None, raises `HTTPException(401, "authentication required")`. Otherwise returns the `Operator`.
  - `async def require_csrf(request) -> None` — reads `request.cookies.get("csrf")` and `request.headers.get("X-CSRF-Token")`; if `validate_csrf_header` returns False, raises `HTTPException(403, "csrf token mismatch")`.
- [ ] `routes.py` — FastAPI `APIRouter(prefix="/auth", tags=["auth"])`:
  - `POST /login`: body `LoginBody(email: EmailStr, password: str)`. Pseudocode (order matters):
    1. **Rate-limit first** — `ip_ok = await check_and_increment(redis, key=f"dashboard:login_rl:ip:{client_ip}", max_attempts=settings.login_rate_limit_ip[0], window_seconds=settings.login_rate_limit_ip[1])`. Similarly `email_ok` keyed by `lower(body.email)`. If either is False → `raise HTTPException(401, "authentication failed")` (same response body as other failure modes; 429-vs-401 distinction would leak that the limit exists).
    2. `record = await get_operator_record_by_email(db, body.email)` (returns `_OperatorRecord | None` including `password_hash`).
    3. If `record is None`: call `verify_password(_DUMMY_HASH, body.password)` for timing parity; raise 401 with generic message.
    4. If `not verify_password(record["password_hash"], body.password)`: raise 401 (same generic message + status).
    5. If `needs_rehash(record["password_hash"])`: call `update_password(db, id=record["id"], old_hash=record["password_hash"], new_hash=hash_password(body.password))` — fire-and-forget outcome; losing the CAS is a no-op. (S2-c)
    6. If the client sent a pre-auth `sess` cookie, call `destroy_session(redis, token=old_token)`. This invalidates only the presented token; other valid sessions on the system are untouched. (S2-a)
    7. `token = await create_session(redis, settings, operator_id=record["id"])`
    8. `csrf = issue_csrf_token()`
    9. Set `sess` cookie: `HttpOnly=True`, `Secure=settings.cookie_secure`, `SameSite=settings.cookie_samesite`, `Max-Age=settings.session_ttl_seconds`, `Path=/`.
    10. Set `csrf` cookie: same flags **except** `HttpOnly=False` (client JS needs to read it to attach the header).
    11. Return `{"operator": Operator(id=record["id"], email=record["email"], created_at=record["created_at"])}`.
  - `get_operator_record_by_email` is defined in Task 2 `crud.py`; it returns an internal TypedDict that keeps `password_hash` out of the public `Operator` model.
  - `POST /logout`: optional `sess` cookie; if present, `destroy_session`. Clear both cookies. Returns 204.
  - `GET /me`: `Depends(require_operator)`, returns `{"operator": operator}`.
- [ ] `app.py` includes `auth_router`. Wires `create_app` so the router is mounted before the strategies router (deterministic ordering for OpenAPI).
- [ ] Integration tests in `test_auth_routes.py`:
  - `test_login_happy_path` — create operator, POST /auth/login with correct creds → 200 + cookies set + body has operator.
  - `test_login_wrong_password` — → 401 generic message.
  - `test_login_unknown_email` — → 401 generic message (same as above).
  - `test_login_calls_verify_password_on_unknown_email` — deterministic invariant test (S2-b): monkeypatch `auth.passwords.verify_password` with a counter, POST /auth/login for an unknown email, assert the counter == 1 (confirming the `_DUMMY_HASH` branch fires).
  - `test_login_response_time_parity_smoke` — wall-clock smoke: median of 5 trials per branch, assert medians within 150 ms. Marked `@pytest.mark.slow`. Accept that this may flake under extreme CI load; the deterministic test above is the authoritative assertion.
  - `test_logout_clears_session` — login, logout, then `GET /auth/me` → 401.
  - `test_logout_without_session_is_idempotent` — POST /auth/logout with no cookies → 204.
  - `test_me_requires_session` — no cookie → 401.
  - `test_me_returns_operator_on_valid_session` — login, GET /auth/me → 200 with matching email.
  - `test_login_rotates_session_on_garbage_cookie` — client presents a garbage `sess` cookie; login succeeds and issues a **different** token; the garbage token key is not present in Redis after login.
  - `test_login_ignores_attackers_valid_session` (S2-a) — create operators A and B; log A in to get real token `T_A`; inject `T_A` as the `sess` cookie on B's login request; assert (a) B's response has a fresh token `T_B ≠ T_A`; (b) `T_A` **remains valid** for A (GET /auth/me with cookie `T_A` returns A's email, not B's); (c) `T_B` resolves to B. This documents that logging in as B does not disturb A's session.
  - `test_login_rate_limit_by_ip` — exhaust the per-IP limit (5 attempts in a test config with `login_rate_limit_ip=(2, 300)`), assert the 3rd request is 401 with generic body. Raw Redis check: the rate-limit key exists and has TTL ≤ 300.
  - `test_login_rate_limit_by_email` — same email from different `X-Forwarded-For`-simulated IPs (or just bypass the IP limit via test config `login_rate_limit_ip=(1000, 300)`), exhaust the per-email limit, assert lockout.
  - `test_login_rate_limit_does_not_leak_distinction` — assert the rate-limited response body and status are identical to the wrong-password response. Constant-time UX.
- [ ] Run the three new test files integration-tagged. Green.
- [ ] Run `uv run mypy services/dashboard/src` and `uv run ruff check services/dashboard`. Green.
- [ ] Commit: `feat(dashboard): /auth/login /auth/logout /auth/me + require_operator dependency`

### Task 5 — Gate the approve endpoint + end-to-end promotion test

**Files:**
- Modify: `services/dashboard/src/dashboard/routers/strategies.py`
- Modify: `services/dashboard/src/dashboard/schemas.py` (remove `ApproveBody.approved_by`)
- Modify: `services/dashboard/tests/conftest.py` (new fixtures `auth_client`, `csrf_header`, `operator_factory`)
- Modify: `services/dashboard/tests/test_routes.py` (update approve tests; add missing-auth, missing-csrf, approved-by-from-session)
- Modify: `wiki/20-Risk/open-debts.md` (append three new debts)

- [ ] Remove the `TODO(auth)` comment on `approve_strategy`.
- [ ] Change the route signature to accept `operator: Operator = Depends(require_operator)` and `_csrf: None = Depends(require_csrf)`, **in that declaration order** so 401 takes precedence over 403 when both checks would fail (S3-a). Remove the `body: ApproveBody` parameter entirely.
- [ ] Delete `ApproveBody` from `schemas.py` (or convert it to `ApproveBody(notes: str | None = None)` if a notes feature is desired — default is delete; notes can be Phase 6).
- [ ] Pass `approved_by=operator.email` into `crud.transition`.
- [ ] `conftest.py` fixtures:
  - `operator_factory` — async fixture that creates an operator with a generated email + known password, yields a `(operator, plaintext_password)` tuple, cleans up afterwards.
  - `auth_client(operator_factory)` — creates an operator, POSTs `/auth/login`, returns an `httpx.AsyncClient` with the cookie jar populated.
  - `csrf_header(auth_client)` — reads the `csrf` cookie from the client jar, returns `{"X-CSRF-Token": <value>}`.
- [ ] Update `test_approve_happy_path`:
  - Use `auth_client` + `csrf_header`.
  - No longer send `approved_by` in the request body (body is now empty).
  - Assert the refreshed strategy's `approved_by == operator.email`.
- [ ] Update `test_approve_invalid_transition` likewise.
- [ ] New tests:
  - `test_approve_requires_auth` — use an unauthenticated `client` fixture → 401.
  - `test_approve_requires_csrf_header` — `auth_client` **without** `X-CSRF-Token` header → 403.
  - `test_approve_requires_matching_origin` — `auth_client` + CSRF header BUT with `Origin: http://evil.example.com` → 403. Confirms the origin check (S1-a) is not bypassed by an attacker who has the CSRF token via XSS on another origin.
  - `test_approve_accepts_referer_when_origin_missing` — `auth_client` + CSRF header + no Origin + `Referer: http://127.0.0.1:8000/dashboard` → 200. Covers the fetch-without-Origin case.
  - `test_approve_auth_takes_precedence_over_csrf` — unauthenticated client + missing CSRF header → 401 (not 403). Confirms dependency ordering (S3-a).
  - `test_approve_uses_session_email_not_body` — POST an empty body, assert DB `approved_by == operator.email`. If a curious client sends a JSON body with a stray `approved_by` field, FastAPI ignores it because the route declares no body parameter.
  - `test_approve_full_lifecycle_sets_session_email` (S2-d) — create strategy, walk `HYPOTHESIS → BACKTESTING → PAPER → AWAITING_APPROVAL` via CRUD, POST /approve with `auth_client` + CSRF + valid Origin, assert `status == live` and `approved_by == operator.email`. This is the authoritative end-to-end promotion-gate test.
- [ ] Invoke `promotion-gate-auditor` subagent on the diff before committing. Address any NO-GO.
- [ ] Append to `wiki/20-Risk/open-debts.md` two new debts (rate-limit moved in-scope — S1-c):
  1. **No MFA** (severity Low today; Medium if the dashboard is exposed beyond localhost). Remediation: TOTP via `pyotp` on a new `operator_totp_secret` column.
  2. **No audit log** beyond `approved_by`. Remediation: append-only `operator_actions` table writing `(operator_id, action, target_id, ts, payload)` on every auth-gated route call.
- [ ] Run `uv run pytest services/dashboard/tests/ -v -m integration`. All green.
- [ ] Run `uv run pytest -m unit`. Green.
- [ ] Run `uv run mypy services` and `uv run ruff check .`. Green.
- [ ] Commit: `feat(dashboard): gate approve route behind operator session + CSRF`

### Task 6 — Bootstrap CLI script

**Files:**
- Create: `scripts/create_operator.py`

- [ ] Argparse:
  - `--email EMAIL` (required)
  - `--rotate` (flag; default False)
- [ ] Flow:
  1. Parse args.
  2. Prompt for password via `getpass.getpass("Password: ")` then `getpass.getpass("Confirm: ")`; bail if mismatch.
  3. Validate password is ≥ 12 chars (soft policy; print warning under 16 but allow).
  4. `db = Database(settings.postgres_dsn); await db.connect()`.
  5. If `--rotate`:
     - `op = await get_operator_by_email(db, email)`; if None, `sys.exit(2)` with error.
     - `hashed = hash_password(plain)`; `await update_password(db, id=op.id, password_hash=hashed)`.
     - Connect to Redis; call `destroy_all_sessions_for_operator(redis, operator_id=op.id)`.
     - Print `rotated password for {email}; all sessions destroyed`.
  6. Else (create):
     - `hashed = hash_password(plain)`.
     - `await create_operator(db, email=email, password_hash=hashed)`; catch `UniqueViolationError` → `sys.exit(2)` with "operator already exists; use --rotate".
     - Print `created operator {email}`.
- [ ] Manual verification (no automated test — the script is interactive):
  ```
  docker compose up -d
  uv run python -m scripts.migrate
  uv run python -m scripts.create_operator --email test@example.com
  # enter "password123456" twice
  # expect: "created operator test@example.com"
  docker compose exec postgres psql -U algobet -d algobet -c "SELECT email FROM operators"
  # expect one row
  uv run python -m scripts.create_operator --email test@example.com
  # expect: "operator already exists; use --rotate"
  uv run python -m scripts.create_operator --email test@example.com --rotate
  # enter new password; expect "rotated password ..."
  ```
- [ ] Commit: `feat(scripts): interactive operator bootstrap + password rotation`

## Verification Plan

- Lint: `uv run ruff check . && uv run ruff format --check .`
- Typecheck: `uv run mypy services`
- Unit: `uv run pytest -m unit`
- Full suite: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest`
- Manual sanity (run after Task 6):
  1. Create operator via CLI.
  2. POST `/auth/login` with correct creds via `curl` → 200, note the `sess` + `csrf` cookies from `-c cookiejar`.
  3. POST `/strategies/{id}/approve` without the CSRF header → 403.
  4. POST same with `-b cookiejar -H "X-CSRF-Token: <csrf-value>"` → 200.
  5. Verify `approved_by` in the DB equals the operator email.
  6. POST `/auth/logout` → 204; subsequent `/strategies/.../approve` → 401.

Success criteria:
- All new unit and integration tests pass.
- `uv run mypy services` green.
- `promotion-gate-auditor` returns GO on the Task 5 diff.
- Attempting to approve without auth → 401. With auth but no CSRF → 403. With both → 200, and `strategies.approved_by` equals the session operator's email.

## Open Dependencies / Assumptions / Known Limitations

- **Rate-limit on `/auth/login`** — **in scope** (S1-c). Fixed-window via Redis `INCR`+`EXPIRE NX`, keyed by both IP and email. Defaults: 5/5min/IP, 10/15min/email. A lockout returns the same generic 401 body as a wrong password so the limit is not detectable from the response.
- **No MFA** — tracked in debt ledger. Single-factor password auth is the only barrier; operator should pair with OS-level disk encryption and a strong password.
- **No audit log** beyond `approved_by` — tracked. Every approve decision is logged only as the email string in `strategies.approved_by`; login/logout/me calls are not persisted.
- **Reads remain open** — `GET /strategies`, `GET /strategies/{id}`, `GET /risk/alerts` are not gated. Assumption: the dashboard is not exposed to untrusted networks. If this changes, add `require_operator` to those routes as a follow-up.
- **Single-operator** — the `operators` table has no role column. Multi-operator with roles is a future phase and trivially additive (add `role text NOT NULL DEFAULT 'operator'`).
- **No password reset flow** — `scripts/create_operator.py --rotate` is the only path. Acceptable because the sole operator has direct filesystem access to the box running the service.
- **Cookie flags default fail-closed** — `cookie_secure=True` is the shipped default (S1-b). Integration tests and local dev running the app over plain HTTP MUST set `COOKIE_SECURE=false` to flip this (read by test conftest / local dev env, never in production config). Production over HTTPS gets Secure cookies automatically.
- **Historical `approved_by` values** — existing rows with values like `"test-automation"` remain valid; no FK constraint is added. Future analytics queries that want operator identity must tolerate free-form strings.
- **Postgres ≥ 13** required for `gen_random_uuid()` without `pgcrypto`. Compose uses PG16. CI runs the migration.
- **`citext`** extension is CREATE EXTENSION IF NOT EXISTS — requires superuser on first install. The `algobet` role in compose already has this privilege.
