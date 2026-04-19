# Phase 4c — Research Orchestrator Scaffold

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver a runnable `research_orchestrator` service scaffold under `services/research_orchestrator/` that wires the strategy registry and message bus without any live Claude API calls — producing a CLI-driven stub workflow that can be exercised end-to-end and later replaced with real hypothesis generation.

**Architecture:** A Python package with a simple CLI (`python -m research_orchestrator`) that runs a single iteration of the research loop: call `hypothesize()` (returns a fixed dict), call `run_backtest()` (logs and returns a fake result), then call `promote()` to advance the strategy through the lifecycle using `strategy_registry.crud.transition`. The `promote()` function enforces the constraint that the research orchestrator MUST NOT attempt the `awaiting-approval → live` transition — that gate belongs exclusively to the dashboard. All state changes go through `strategy_registry.crud`; no raw SQL is written in this service.

**Tech Stack:** Python 3.12, `algobet_common` (BusClient, Database, Settings, Topic), `strategy_registry` (crud, models, errors), `typer` (CLI), `pytest`, `pytest-asyncio`, shared `conftest.py` fixtures.

---

## Scope and Constraints

- **In scope:** package scaffold, CLI entrypoint, three stub workflow functions (`hypothesize`, `run_backtest`, `promote`), state-machine wiring to strategy registry, bus event publishing for research events, unit tests for state-machine wiring.
- **Out of scope:** Claude API / Anthropic SDK integration (Phase 5); real backtesting logic; real hypothesis generation; paper trading result evaluation; metrics-based auto-promotion from `paper` to `awaiting-approval` (that judgment must involve a human check); Betfair or Kalshi data access.
- **Safety invariants:**
  - `promote()` MUST raise `OrchestratorError` if called with `to_status=Status.LIVE` or `to_status=Status.AWAITING_APPROVAL` after `Status.PAPER`. The only transitions the orchestrator may request are: `hypothesis → backtesting`, `backtesting → paper`, `backtesting → retired`, `paper → retired`. The `paper → awaiting-approval` and `awaiting-approval → live` transitions are reserved for humans via the dashboard; attempting either from the orchestrator MUST raise `OrchestratorError` before any DB call.
  - Publishing to `Topic.RESEARCH_EVENTS` must occur after a successful `transition` call, never before — to avoid misleading events if the transition fails.
  - Reuse `algobet_common.bus.BusClient` and `algobet_common.db.Database`; never re-implement bus or DB primitives.
  - UK venues only — the scaffold does not reference venues, which is correct for a hypothesis/backtest loop.

## File Responsibilities

- `services/research_orchestrator/pyproject.toml` — uv workspace member; depends on `algobet-common`, `strategy-registry`, `typer`.
- Root `pyproject.toml` — add `research-orchestrator` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, and `testpaths`.
- `services/research_orchestrator/src/research_orchestrator/__init__.py` — empty package marker.
- `services/research_orchestrator/src/research_orchestrator/errors.py` — single exception `OrchestratorError(RuntimeError)` used when the orchestrator attempts a forbidden transition.
- `services/research_orchestrator/src/research_orchestrator/workflow.py` — three async functions:
  - `hypothesize() -> dict` — returns a fixed stub dict `{"name": "stub-hypothesis", "description": "placeholder", "venue": "betfair"}`. Logs at INFO. Does NOT write to DB or bus.
  - `run_backtest(hypothesis: dict) -> dict` — logs at INFO with hypothesis name. Returns a fixed stub dict `{"sharpe": 0.0, "total_pnl_gbp": 0.0, "n_trades": 0, "status": "stub"}`. Does NOT write to DB or bus.
  - `promote(db: Database, bus: BusClient, strategy_id: uuid.UUID, to_status: Status) -> Strategy` — validates that `to_status` is not `Status.LIVE` and not `Status.AWAITING_APPROVAL`, raising `OrchestratorError` for either; then calls `strategy_registry.crud.transition(db, strategy_id, to_status)`; on success publishes a `ResearchEvent` message to `Topic.RESEARCH_EVENTS`; returns the updated `Strategy`.
- `services/research_orchestrator/src/research_orchestrator/schemas.py` — `ResearchEvent` Pydantic model: `event_type: str`, `strategy_id: str`, `from_status: str`, `to_status: str`, `timestamp: datetime`. Subclasses `algobet_common.schemas._BaseMessage` (or replicates its `model_config` if `_BaseMessage` is private — check visibility before referencing).
- `services/research_orchestrator/src/research_orchestrator/runner.py` — async `run_once(db: Database, bus: BusClient, settings: Settings) -> None`:
  1. Call `hypothesize()`.
  2. Create a strategy in the registry via `strategy_registry.crud.create_strategy(db, slug=f"{hypothesis['name']}-{uuid4().hex[:8]}")` to avoid unique-key collisions in repeated runs.
  3. Call `run_backtest(hypothesis)`.
  4. If `result["status"] == "stub"`, call `promote(db, bus, strategy.id, Status.BACKTESTING)` then `promote(db, bus, strategy.id, Status.PAPER)`.
  5. Log a summary at INFO with the final strategy status.
  6. Does NOT attempt `paper → awaiting-approval`; that is a human decision.
- `services/research_orchestrator/src/research_orchestrator/__main__.py` — `typer` CLI with a single command `run` that calls `asyncio.run(run_once(db, bus, settings))`. Constructs `Settings(service_name="research-orchestrator")`, `BusClient`, `Database`, connects both in a `try/finally`.
- `services/research_orchestrator/tests/conftest.py` — re-uses shared fixtures via `pytest_plugins`; provides a `db` async fixture (Database connected to test Postgres) and a `bus` async fixture (BusClient connected to test Redis).
- `services/research_orchestrator/tests/test_workflow.py` — unit tests for state-machine wiring (see Task 3).
- `services/research_orchestrator/tests/test_runner_integration.py` — integration test for `run_once` end-to-end (see Task 4).

## Task Breakdown

### Task 1 — Workspace skeleton

**Files:**
- Create: `services/research_orchestrator/pyproject.toml`
- Create: `services/research_orchestrator/src/research_orchestrator/__init__.py`
- Modify: root `pyproject.toml`

- [ ] Create `services/research_orchestrator/pyproject.toml` as a uv workspace member with `name = "research-orchestrator"`, `requires-python = ">=3.12,<3.13"`, and dependencies on `algobet-common`, `strategy-registry`, `typer`.
- [ ] Create `services/research_orchestrator/src/research_orchestrator/__init__.py` as an empty file.
- [ ] Add `research-orchestrator` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, and `testpaths` in root `pyproject.toml`.
- [ ] Run `uv sync --all-packages` and confirm no errors.
- [ ] Commit: `feat(orchestrator): workspace skeleton`

### Task 2 — Errors, schemas, and workflow stubs

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/errors.py`
- Create: `services/research_orchestrator/src/research_orchestrator/schemas.py`
- Create: `services/research_orchestrator/src/research_orchestrator/workflow.py`

- [ ] Implement `errors.py` with `class OrchestratorError(RuntimeError): pass`.
- [ ] Check whether `algobet_common.schemas._BaseMessage` is exported in `algobet_common.__init__`. If not, define `ResearchEvent` in `schemas.py` with its own `model_config = ConfigDict(frozen=True, extra="forbid")` rather than subclassing a private class.
- [ ] Implement `ResearchEvent` in `schemas.py`: `event_type: str`, `strategy_id: str`, `from_status: str`, `to_status: str`, `timestamp: datetime`.
- [ ] Implement `hypothesize()` in `workflow.py`. Log at INFO. Return the fixed stub dict.
- [ ] Implement `run_backtest(hypothesis)` in `workflow.py`. Log the hypothesis name at INFO. Return the fixed stub result dict.
- [ ] Implement `promote(db, bus, strategy_id, to_status)` in `workflow.py`. Guard against `to_status in {Status.LIVE, Status.AWAITING_APPROVAL}` — raise `OrchestratorError(f"orchestrator may not request transition to {to_status}; use the dashboard approval route")`. Fetch current strategy status before transitioning (via `crud.get_strategy`) to populate `from_status` on the `ResearchEvent`. Call `crud.transition`. Publish `ResearchEvent` to `Topic.RESEARCH_EVENTS`. Return updated `Strategy`.
- [ ] Run `SERVICE_NAME=research-orchestrator uv run python -c "from research_orchestrator.workflow import hypothesize, run_backtest, promote"` to confirm importability with required settings.
- [ ] Run `uv run mypy services/research_orchestrator/src`.
- [ ] Commit: `feat(orchestrator): errors, schemas, workflow stubs`

### Task 3 — Unit tests for state-machine wiring

**Files:**
- Create: `services/research_orchestrator/tests/conftest.py`
- Create: `services/research_orchestrator/tests/test_workflow.py`

- [ ] Create `tests/conftest.py` with `pytest_plugins` pulling in the shared `postgres_dsn`, `require_postgres`, `redis_url`, `require_redis` fixtures.
- [ ] Write `tests/test_workflow.py`. These tests must be OFFLINE (no DB, no Redis). Use `unittest.mock.AsyncMock` and `unittest.mock.MagicMock` to stub `db`, `bus`, and `crud` calls:
  - `test_hypothesize_returns_stub`: call `hypothesize()` and assert the returned dict has keys `"name"`, `"description"`, `"venue"`.
  - `test_run_backtest_returns_stub`: call `run_backtest({"name": "x"})` and assert the returned dict has `"status" == "stub"` and `"sharpe"` key.
  - `test_promote_blocks_live_transition`: construct a mock `db` and `bus`; call `promote(db, bus, uuid4(), Status.LIVE)` and assert `OrchestratorError` is raised without any DB call being made (assert mock not called).
  - `test_promote_blocks_awaiting_approval_transition`: same as above for `Status.AWAITING_APPROVAL`.
  - `test_promote_allowed_backtesting`: mock `crud.get_strategy` to return a `Strategy` with `status=Status.HYPOTHESIS` and mock `crud.transition` to return a `Strategy` with `status=Status.BACKTESTING`; mock `bus.publish` to be an `AsyncMock`; call `promote(db, bus, uuid4(), Status.BACKTESTING)`; assert `crud.transition` was called once with `to_status=Status.BACKTESTING`; assert `bus.publish` was called once with `Topic.RESEARCH_EVENTS` and a `ResearchEvent` instance.
  - `test_promote_allowed_paper`: same pattern for `Status.BACKTESTING → Status.PAPER`.
- [ ] Run `uv run pytest services/research_orchestrator/tests/test_workflow.py -v` and confirm all pass.
- [ ] Run `uv run ruff check services/research_orchestrator && uv run mypy services/research_orchestrator/src`.
- [ ] Commit: `feat(orchestrator): state-machine unit tests`

### Task 4 — Runner, CLI, and integration test

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/runner.py`
- Create: `services/research_orchestrator/src/research_orchestrator/__main__.py`
- Create: `services/research_orchestrator/tests/test_runner_integration.py`

- [ ] Implement `runner.py` with `async def run_once(db, bus, settings)` as described in File Responsibilities above. The function must NOT attempt `paper → awaiting-approval`. Finish by logging the strategy's final status.
- [ ] Implement `__main__.py` with a `typer` app containing a single `run` command. The command constructs `Settings(service_name="research-orchestrator")`, `BusClient`, `Database`, connects both in `try/finally`, and calls `asyncio.run(run_once(...))`.
- [ ] Write `tests/test_runner_integration.py` with `pytestmark = pytest.mark.integration`. Single test `test_run_once_creates_paper_strategy`:
  1. Use `require_postgres` and `require_redis` fixtures.
  2. Construct a connected `Database` and `BusClient` from fixture URLs.
  3. Call `await run_once(db, bus, settings)`.
  4. Assert that a strategy whose slug starts with `"stub-hypothesis-"` exists in Postgres with `status="paper"` (query via `crud.list_strategies`).
  5. Assert that `Topic.RESEARCH_EVENTS` stream in Redis contains at least two entries (one for `backtesting`, one for `paper`), using `redis.asyncio` XREAD.
  6. Assert that no strategy has `status="awaiting-approval"` or `status="live"` (the orchestrator must not have overstepped its authority).
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/research_orchestrator/tests/test_runner_integration.py -v -m integration`.
- [ ] Commit: `feat(orchestrator): runner, CLI entrypoint, integration test`

## Verification Plan

- Lint + format: `uv run ruff check . && uv run ruff format --check .`
- Type check: `uv run mypy services`
- Unit tests (offline): `uv run pytest services/research_orchestrator/tests/test_workflow.py -v`
- Integration test: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/research_orchestrator/tests/test_runner_integration.py -v -m integration`
- Full suite: `uv run pytest`
- Manual smoke: `uv run python -m research_orchestrator run` (with `SERVICE_NAME=research-orchestrator` or override in the CLI); confirm log output shows `hypothesis → backtesting → paper` and the strategy appears in Postgres.
- Safety check: `rg "Status.LIVE\|Status.AWAITING_APPROVAL\|awaiting-approval\|-> live" services/research_orchestrator/src` — every match in `workflow.py` must be inside the guard block that raises `OrchestratorError`, never in a call to `crud.transition`.

Success criteria:
- All offline unit tests pass without any running infrastructure.
- Integration test creates a strategy at `status="paper"` and publishes two `ResearchEvent` entries to Redis.
- No strategy reaches `awaiting-approval` or `live` via the orchestrator.
- `uv run mypy services` returns zero errors.
- `OrchestratorError` is raised (not swallowed) when `promote` is called with `Status.LIVE` or `Status.AWAITING_APPROVAL`.

## Open Dependencies / Assumptions

- `strategy_registry` package (Phase 3b) must be complete and importable.
- The `strategies.slug` column has a unique constraint in the migration; this plan requires a UUID suffix on stub slugs to make repeated local and CI runs idempotent.
- `Topic.RESEARCH_EVENTS` stream is defined in `algobet_common.bus.Topic` — confirmed present in `bus.py`. No schema change needed.
- `typer` is added as a new dependency not yet in the workspace. Pin to `typer>=0.12` (supports Python 3.12 and `Annotated` params well).
- The `_BaseMessage` class in `algobet_common.schemas` is prefixed with `_` indicating it is private. `ResearchEvent` must NOT subclass it directly; copy the `model_config` instead.
- Real backtest result evaluation, Sharpe thresholds, and auto-advance from `paper` to `awaiting-approval` are deferred. The current stub always advances through `backtesting` to `paper` unconditionally — this is intentional for the scaffold phase and must be clearly documented in the README (not written in this plan phase).
- The CLI `run` command runs a single iteration and exits, not a daemon loop. Scheduling (cron, asyncio periodic loop) is a Phase 5 concern.
