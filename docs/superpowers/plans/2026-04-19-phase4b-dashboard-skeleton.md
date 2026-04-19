# Phase 4b — Dashboard Skeleton (FastAPI + strategy approval gate)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver a minimal FastAPI service under `services/dashboard/` that exposes read-only strategy and risk-alert endpoints, plus the single human-approval route that transitions a strategy from `awaiting-approval` to `live` — the last software gate before real capital is deployed.

**Architecture:** Async FastAPI app using `asyncpg` via `algobet_common.db.Database` for Postgres reads and `redis.asyncio` for Redis XREAD polling on the alerts stream. The approval route delegates exclusively to `strategy_registry.crud.transition` so the transition invariant (SELECT FOR UPDATE + approval columns) is never duplicated. No auth is added in this phase — a `TODO(auth)` comment is mandatory on the approval route because it is the live-capital gate.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, `algobet_common` (Database, Settings, BusClient, Topic), `strategy_registry` (crud, models), `redis.asyncio` (for XREAD polling), `pytest`, `pytest-asyncio`, `httpx`, shared `conftest.py` fixtures.

---

## Scope and Constraints

- **In scope:** four routes (list strategies, detail, approve, recent risk alerts); async DB reads; XREAD-based alert tail (no consumer group); integration tests with live DB and Redis; `TODO(auth)` callout.
- **Out of scope:** authentication and authorisation (Phase 5); live P&L charts; WebSocket push; write operations other than approve; order history pagination beyond a simple `LIMIT`.
- **Safety invariants:**
  - The `POST /strategies/{id}/approve` route MUST call `strategy_registry.crud.transition(db, id, Status.LIVE, approved_by=body.approved_by)` and nothing else to write to the `strategies` table. No raw SQL status writes in this service.
  - A `TODO(auth): this route is the live-capital gate; protect with operator authentication before production use` comment MUST be present directly above the approve route handler.
  - Reuse `algobet_common.db.Database` and `algobet_common.bus.BusClient`; never re-implement.
  - UK venues only — the dashboard is read-only for data, so no venue enforcement is needed here beyond displaying what the registry contains.

## File Responsibilities

- `services/dashboard/pyproject.toml` — uv workspace member; depends on `algobet-common`, `strategy-registry`, `fastapi[standard]`, `uvicorn[standard]`, `httpx` (for tests).
- Root `pyproject.toml` — add `dashboard` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, and `testpaths`.
- `services/dashboard/src/dashboard/__init__.py` — empty package marker.
- `services/dashboard/src/dashboard/app.py` — FastAPI application factory `create_app() -> FastAPI`. Registers lifespan context manager that initialises `Database` and `BusClient` (for Redis) on startup and closes on shutdown. Stores both on `app.state`. Includes the strategies router and risk router.
- `services/dashboard/src/dashboard/dependencies.py` — FastAPI dependency callables:
  - `get_db(request: Request) -> Database` — returns `request.app.state.db`.
  - `get_redis(request: Request) -> redis.Redis` — returns `request.app.state.redis` (a bare `redis.asyncio` client, not a BusClient).
- `services/dashboard/src/dashboard/routers/strategies.py` — APIRouter with prefix `/strategies`:
  - `GET /` — calls `strategy_registry.crud.list_strategies(db)`, returns list of `StrategyOut` response models.
  - `GET /{strategy_id}` — calls `strategy_registry.crud.get_strategy(db, UUID(strategy_id))`, plus a parameterised query for the 10 most recent `strategy_runs` rows and 20 most recent `orders` rows; returns `StrategyDetailOut`.
  - `POST /{strategy_id}/approve` — body `ApproveBody(approved_by: str)`; calls `strategy_registry.crud.transition(db, UUID(strategy_id), Status.LIVE, approved_by=body.approved_by)`; returns the updated `StrategyOut`. `TODO(auth)` comment required.
- `services/dashboard/src/dashboard/routers/risk.py` — APIRouter with prefix `/risk`:
  - `GET /alerts` — accepts optional query param `count: int = 20`; uses `redis.asyncio` XREAD (no consumer group) on `Topic.RISK_ALERTS.value` with `count` and no `BLOCK` parameter so requests return immediately; returns list of `RiskAlertOut` response models parsed from the stream entries.
- `services/dashboard/src/dashboard/schemas.py` — Pydantic response models:
  - `StrategyOut` — mirrors `strategy_registry.models.Strategy` fields; all fields, UUID serialised as str.
  - `StrategyRunOut` — mirrors `strategy_registry.models.StrategyRun`.
  - `OrderOut` — id, strategy_id, side, stake, price, status, created_at.
  - `StrategyDetailOut` — extends `StrategyOut` with `recent_runs: list[StrategyRunOut]` and `recent_orders: list[OrderOut]`.
  - `ApproveBody` — `approved_by: str` (non-empty, min_length=1).
  - `RiskAlertOut` — stream_id, source, severity, message, timestamp.
- `services/dashboard/src/dashboard/__main__.py` — launches `uvicorn dashboard.app:create_app` factory with host/port from `Settings`.
- `services/dashboard/tests/conftest.py` — async `client` fixture using `httpx.AsyncClient(app=create_app(), base_url="http://test")` with ASGI transport; shares `require_postgres` and `require_redis` from `services/common/tests/conftest.py` via `pytest_plugins`.
- `services/dashboard/tests/test_routes.py` — integration tests (see Task 4).

## Task Breakdown

### Task 1 — Workspace skeleton

**Files:**
- Create: `services/dashboard/pyproject.toml`
- Create: `services/dashboard/src/dashboard/__init__.py`
- Modify: root `pyproject.toml`

- [ ] Create `services/dashboard/pyproject.toml` as a uv workspace member with `name = "dashboard"`, `requires-python = ">=3.12,<3.13"`, dependencies: `algobet-common`, `strategy-registry`, `fastapi[standard]`, `uvicorn[standard]`; dev dependency: `httpx`.
- [ ] Create `services/dashboard/src/dashboard/__init__.py` as an empty file.
- [ ] Add `dashboard` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, and `testpaths` in root `pyproject.toml`.
- [ ] Run `uv sync --all-packages` and confirm no errors.
- [ ] Commit: `feat(dashboard): workspace skeleton`

### Task 2 — Application factory + dependencies

**Files:**
- Create: `services/dashboard/src/dashboard/app.py`
- Create: `services/dashboard/src/dashboard/dependencies.py`
- Create: `services/dashboard/src/dashboard/__main__.py`

- [ ] Implement `create_app()` in `app.py`. Use `@asynccontextmanager` lifespan: on enter, read `Settings()` (pass `service_name="dashboard"`), connect `Database` and a bare `redis.asyncio.from_url(settings.redis_url)` client, store both on `app.state` as `app.state.db` and `app.state.redis`. On exit, close both. Return the FastAPI instance with the lifespan attached.
- [ ] Implement `get_db` and `get_redis` in `dependencies.py` as synchronous callables (FastAPI dependency injection does not require async for simple attribute reads).
- [ ] Implement `__main__.py`: import `create_app`, call `uvicorn.run("dashboard.app:create_app", factory=True, host="0.0.0.0", port=8080, reload=False)`.
- [ ] Run `SERVICE_NAME=dashboard uv run python -c "from dashboard.app import create_app; app = create_app()"` to verify importability with required settings.
- [ ] Run `uv run mypy services/dashboard/src`.
- [ ] Commit: `feat(dashboard): app factory and dependencies`

### Task 3 — Response schemas + routes

**Files:**
- Create: `services/dashboard/src/dashboard/schemas.py`
- Create: `services/dashboard/src/dashboard/routers/__init__.py`
- Create: `services/dashboard/src/dashboard/routers/strategies.py`
- Create: `services/dashboard/src/dashboard/routers/risk.py`
- Modify: `services/dashboard/src/dashboard/app.py`

- [ ] Implement all Pydantic response models in `schemas.py`. Use `model_config = ConfigDict(from_attributes=True)` so they can be constructed from asyncpg `Record` objects and from `strategy_registry` model instances. All UUID fields should be typed as `uuid.UUID` (FastAPI serialises them to strings automatically).
- [ ] Create `services/dashboard/src/dashboard/routers/__init__.py` as an empty file.
- [ ] Implement `routers/strategies.py`:
  - `GET /` handler calls `list_strategies(db)` and returns `list[StrategyOut]`.
  - `GET /{strategy_id}` handler: UUID-validate the path param (let FastAPI raise 422 on malformed UUID); call `get_strategy` inside a try/except `StrategyNotFoundError` → return HTTP 404; run two parameterised queries for recent runs and recent orders; return `StrategyDetailOut`.
  - `POST /{strategy_id}/approve` handler: include `# TODO(auth): this route is the live-capital gate; protect with operator authentication before production use` comment directly above the function body; call `crud.transition`; catch `StrategyNotFoundError` → 404, `InvalidTransitionError` → 422 with detail, `ApprovalRequiredError` → 422 with detail; return updated `StrategyOut`.
- [ ] Implement `routers/risk.py`. The `GET /alerts` handler calls `redis_client.xread(streams={Topic.RISK_ALERTS.value: "0"}, count=count)` (non-blocking, no consumer group); parse each entry's `"json"` field into `RiskAlert` and convert to `RiskAlertOut` with the stream entry id as `stream_id`; return `list[RiskAlertOut]`.
- [ ] Register both routers in `app.py`: `app.include_router(strategies_router)` and `app.include_router(risk_router)`.
- [ ] Run `uv run mypy services/dashboard/src`.
- [ ] Commit: `feat(dashboard): schemas and route handlers`

### Task 4 — Integration tests

**Files:**
- Create: `services/dashboard/tests/conftest.py`
- Create: `services/dashboard/tests/test_routes.py`

- [ ] Create `tests/conftest.py`. Declare `pytest_plugins` to pull in shared `postgres_dsn`, `require_postgres`, `redis_url`, `require_redis` fixtures. Add an `app` fixture that calls `create_app()`. Add an async `client` fixture using `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`.
- [ ] Write `tests/test_routes.py` with `pytestmark = pytest.mark.integration`. Cover:
  - `test_list_strategies_empty`: call `GET /strategies`, assert HTTP 200 and JSON list (may be empty).
  - `test_get_strategy_not_found`: call `GET /strategies/00000000-0000-0000-0000-000000000000`, assert HTTP 404.
  - `test_approve_happy_path`: use `strategy_registry.crud` to create and advance a strategy to `awaiting-approval`; call `POST /strategies/{id}/approve` with body `{"approved_by": "test-operator"}`; assert HTTP 200, returned `status == "live"`, and query DB directly to confirm `approved_by` and `approved_at` are set.
  - `test_approve_invalid_transition`: create a strategy in `hypothesis` status; call approve; assert HTTP 422.
  - `test_risk_alerts_empty`: call `GET /risk/alerts`, assert HTTP 200 and empty list (Redis DB 15 flushed between tests).
  - `test_risk_alerts_with_data`: publish a `RiskAlert` to `risk.alerts` via a BusClient; call `GET /risk/alerts?count=5`; assert one result with correct fields.
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/dashboard/tests -v -m integration`.
- [ ] Commit: `feat(dashboard): integration tests`

## Verification Plan

- Lint + format: `uv run ruff check . && uv run ruff format --check .`
- Type check: `uv run mypy services`
- Integration tests: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/dashboard/tests -v -m integration`
- Full suite: `uv run pytest`
- Manual smoke: `uv run python -m dashboard` then `curl http://localhost:8080/strategies` and `curl -X POST http://localhost:8080/strategies/<uuid>/approve -H "Content-Type: application/json" -d '{"approved_by":"operator"}'`

Success criteria:
- All six integration tests pass.
- `POST /strategies/{id}/approve` on a strategy in `awaiting-approval` returns HTTP 200 with `status="live"` and DB columns `approved_by`, `approved_at` populated.
- `POST /strategies/{id}/approve` on a strategy not in `awaiting-approval` returns HTTP 422.
- `GET /risk/alerts` returns a list (possibly empty) without error.
- `TODO(auth)` comment present on approve handler — confirm with `rg "TODO(auth)" services/dashboard`.
- `uv run mypy services` returns zero errors.

## Open Dependencies / Assumptions

- `strategy_registry` package (Phase 3b) must be installed and importable with `get_strategy`, `list_strategies`, `transition`, `start_run`, `end_run` callable.
- The `orders` table schema (from `0002_strategy_registry.sql`) must have at least `id`, `strategy_id`, `side`, `stake`, `price`, `status`, `created_at` columns for `OrderOut` to be constructable.
- Redis XREAD with `id="0"` and no `BLOCK` returns currently available entries from the beginning of the stream; in production this should be scoped to a recent time-based ID. This is acceptable for the skeleton; a `since` query param can be added in Phase 5.
- No pagination is implemented for `GET /strategies` — acceptable for Phase 4 (strategy count will be small). Add cursor pagination in Phase 5.
- `Settings` requires `service_name`; the dashboard passes `"dashboard"` explicitly. If `Settings` is instantiated elsewhere without `service_name`, it will raise a validation error — that is intentional and correct.
- The `approved_by` field is a free-form string in this phase. Operator identity verification is deferred to Phase 5 auth work.
- Lifecycle handoff note: this skeleton intentionally implements only the `awaiting-approval -> live` gate endpoint requested in scope. Advancing `paper -> awaiting-approval` remains an operator workflow via strategy-registry tooling in this phase and should be made first-class in a later dashboard iteration.
