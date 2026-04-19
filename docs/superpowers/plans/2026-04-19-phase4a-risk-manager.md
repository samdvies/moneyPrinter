# Phase 4a — Risk Manager Service

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deliver a standalone `risk_manager` service that consumes `order.signals`, applies configurable pre-flight safety checks, and either approves the signal by republishing to `order.signals.approved` or rejects it with a `RiskAlert` on `risk.alerts` — acting as the last programmatic gate before the execution engine receives any order.

**Architecture:** The service is a long-running async loop built on `BusClient.consume()` + `BusClient.publish()` from `algobet_common`. All business rules live in a pure `rules.py` module (no I/O) so they can be unit-tested offline. A thin `engine.py` wires rules to DB look-ups and bus publishing. Settings fields for exposure caps, venue notional caps, and the kill-switch live on `algobet_common.config.Settings` via new optional fields with safe defaults.

**Tech Stack:** Python 3.12, `algobet_common` (BusClient, Database, Settings, OrderSignal, RiskAlert, Topic), `asyncpg` (via Database), `pytest`, `pytest-asyncio`, shared `conftest.py` fixtures.

---

## Scope and Constraints

- **In scope:** new `services/risk_manager/` uv-workspace member; four configurable rules (exposure cap, venue notional cap, kill-switch, registry mode check); approval republish; rejection alerts; unit tests per rule; one Redis + Postgres integration test.
- **Out of scope:** persistent exposure tracking across restarts (Phase 5 concern); per-strategy live P&L aggregation; authentication; any write to the `orders` table (execution engine's job).
- **Safety invariants:**
  - A signal with `mode="live"` and kill-switch active MUST emit a `severity="critical"` alert and MUST NOT be republished.
  - A signal that fails any rule MUST NOT be published to `order.signals.approved`.
  - The `order.signals.approved` topic is the ONLY input the execution engine trusts. The risk manager MUST NOT republish a partially-checked signal.
  - Reuse `algobet_common.bus.BusClient` and `algobet_common.db.Database`; never re-implement bus or DB primitives.
  - Default `risk_max_strategy_exposure_gbp` = 1000 as the Phase 4 per-signal stake guard; cumulative open-exposure enforcement is deferred and called out explicitly below.
  - UK venues only — `Venue.BETFAIR` and `Venue.KALSHI` are the only recognised values; signals for unrecognised venues are rejected.

## New Settings Fields

Add the following optional fields to `services/common/src/algobet_common/config.py` (`Settings` class). All have safe defaults so existing services are unaffected:

- `risk_max_strategy_exposure_gbp: Decimal` — default `Decimal("1000")`
- `risk_venue_notionals: dict[str, Decimal]` — default `{}` (no venue-level cap when empty); JSON-encoded env var e.g. `RISK_VENUE_NOTIONALS='{"betfair": "5000"}'`
- `risk_kill_switch: bool` — default `False`; set `RISK_KILL_SWITCH=true` to activate

## File Responsibilities

- `services/risk_manager/pyproject.toml` — uv workspace member; depends on `algobet-common` and `strategy-registry`; no runtime extras.
- Root `pyproject.toml` — add `risk-manager` to `[tool.uv.workspace] members`, `[tool.uv.sources]`, root `dependencies`, and `[tool.pytest.ini_options] testpaths`; register a `unit` pytest marker for offline rule tests.
- `services/common/src/algobet_common/config.py` — add three new optional `Settings` fields with defaults; no breaking changes.
- `services/risk_manager/src/risk_manager/__init__.py` — empty package marker.
- `services/risk_manager/src/risk_manager/rules.py` — pure functions (no I/O):
  - `check_kill_switch(signal, settings) -> RuleResult` — returns REJECT(critical) when `risk_kill_switch=True` and `signal.mode == "live"`, else REJECT(warn) if `risk_kill_switch=True` and mode is `paper` (configurable warn-only), else PASS.
  - `check_exposure(signal, settings) -> RuleResult` — compares `signal.stake` against `risk_max_strategy_exposure_gbp`; returns REJECT(warn) on breach.
  - `check_venue_notional(signal, settings) -> RuleResult` — looks up `signal.venue` in `risk_venue_notionals`; returns REJECT(warn) on breach; PASS if venue absent from config.
  - `check_registry_mode(signal, strategy_status, run_mode) -> RuleResult` — receives pre-fetched values; returns REJECT(warn) if strategy does not exist (caller passes `None`), if `strategy_status` is not `live` when `signal.mode=="live"`, or if `run_mode` does not match `signal.mode`.
  - `RuleResult` is a plain dataclass: `passed: bool`, `severity: Literal["warn","critical"] | None`, `reason: str | None`.
- `services/risk_manager/src/risk_manager/engine.py` — async function `run(bus, db, settings)`:
  - Runs an infinite consume loop on `Topic.ORDER_SIGNALS` using `BusClient.consume(topic, OrderSignal)`.
  - For each signal: fetches strategy row and latest run row from DB (using `strategy_registry.crud.get_strategy` and a direct asyncpg query for the latest run).
  - Calls all four rule functions in order; stops at first failure.
  - On all-pass: `bus.publish(Topic.ORDER_SIGNALS_APPROVED, signal)`.
  - On any failure: constructs `RiskAlert(source="risk_manager", severity=result.severity, message=result.reason, timestamp=datetime.now(UTC))` and `bus.publish(Topic.RISK_ALERTS, alert)`.
- `services/risk_manager/src/risk_manager/__main__.py` — async entrypoint mirroring `services/simulator/src/simulator/__main__.py`; instantiates `Settings`, `BusClient`, `Database`, calls `engine.run`.
- `services/risk_manager/tests/conftest.py` — re-uses fixtures via `pytest_plugins = ["conftest"]` referencing the shared `services/common/tests/conftest.py` (same pattern as strategy_registry).
- `services/risk_manager/tests/test_rules.py` — pure offline unit tests, one test per rule branch (see Task 2).
- `services/risk_manager/tests/test_engine_integration.py` — integration test requiring both Redis and Postgres (see Task 4).

## Task Breakdown

### Task 1 — Workspace skeleton + Settings extension

**Files:**
- Create: `services/risk_manager/pyproject.toml`
- Create: `services/risk_manager/src/risk_manager/__init__.py`
- Modify: `services/common/src/algobet_common/config.py`
- Modify: root `pyproject.toml`

- [ ] Create `services/risk_manager/pyproject.toml` as a uv workspace member declaring `name = "risk-manager"`, `requires-python = ">=3.12,<3.13"`, and dependencies on `algobet-common` and `strategy-registry` from workspace sources.
- [ ] Create `services/risk_manager/src/risk_manager/__init__.py` as an empty file.
- [ ] Add `risk_max_strategy_exposure_gbp`, `risk_venue_notionals`, and `risk_kill_switch` to `Settings` in `services/common/src/algobet_common/config.py`. Use `Decimal` for monetary fields, `bool` for the kill-switch. All must have defaults that leave existing tests unaffected. Add a validator that JSON-parses `risk_venue_notionals` from an env-string if the raw value is a `str`.
- [ ] Add `risk-manager` to `[tool.uv.workspace] members` and `[tool.uv.sources]` in root `pyproject.toml`. Add `"risk-manager"` to root `dependencies`. Add `services/risk_manager/tests` to `testpaths`. Add pytest marker `unit: tests that run offline without infrastructure`.
- [ ] Run `uv sync --all-packages` and verify no errors.
- [ ] Run `uv run mypy services/common/src` and confirm green.
- [ ] Commit: `feat(risk-manager): workspace skeleton and Settings extension`

### Task 2 — Pure rules module + unit tests

**Files:**
- Create: `services/risk_manager/src/risk_manager/rules.py`
- Create: `services/risk_manager/tests/test_rules.py`

- [ ] Define `RuleResult` dataclass in `rules.py` with fields `passed: bool`, `severity: Literal["warn", "critical"] | None`, and `reason: str | None`. A convenience factory `RuleResult.ok()` returns `RuleResult(passed=True, severity=None, reason=None)`.
- [ ] Implement `check_kill_switch(signal: OrderSignal, settings: Settings) -> RuleResult`. When `settings.risk_kill_switch` is `True` and `signal.mode == "live"`, return `RuleResult(passed=False, severity="critical", reason="kill-switch active; live signals blocked")`. When kill-switch is `True` and mode is `"paper"`, return `RuleResult(passed=False, severity="warn", reason="kill-switch active; paper signals paused")`. Otherwise return `RuleResult.ok()`.
- [ ] Implement `check_exposure(signal: OrderSignal, settings: Settings) -> RuleResult`. Compare `signal.stake` to `settings.risk_max_strategy_exposure_gbp`; on breach return `RuleResult(passed=False, severity="warn", reason=f"stake {signal.stake} exceeds cap {settings.risk_max_strategy_exposure_gbp}")`. Otherwise return `RuleResult.ok()`.
- [ ] Implement `check_venue_notional(signal: OrderSignal, settings: Settings) -> RuleResult`. Look up `signal.venue.value` in `settings.risk_venue_notionals`; if absent, return `RuleResult.ok()`. If `signal.stake` exceeds the cap, return warn reject. Accept only `Venue.BETFAIR` and `Venue.KALSHI`; signal for any other venue string returns warn reject with reason `"unrecognised venue"`.
- [ ] Implement `check_registry_mode(signal: OrderSignal, strategy_status: str | None, run_mode: str | None) -> RuleResult`. Return warn reject when `strategy_status is None` (strategy not found). Return warn reject when `signal.mode == "live"` and `strategy_status != "live"`. Return warn reject when `run_mode is not None and run_mode != signal.mode`.
- [ ] Write `tests/test_rules.py` with `pytestmark = pytest.mark.unit` (offline). Tests must cover:
  - `check_kill_switch`: kill-switch off → pass; kill-switch on + live → critical reject; kill-switch on + paper → warn reject.
  - `check_exposure`: stake at cap → pass; stake above cap → warn reject.
  - `check_venue_notional`: no cap configured → pass; cap configured + under → pass; cap configured + over → warn reject; unrecognised venue → warn reject.
  - `check_registry_mode`: strategy not found → warn reject; strategy found, wrong status for live signal → warn reject; run_mode mismatch → warn reject; all match → pass.
- [ ] Run `uv run pytest services/risk_manager/tests/test_rules.py -v` and confirm all pass.
- [ ] Run `uv run ruff check services/risk_manager && uv run mypy services/risk_manager/src`.
- [ ] Commit: `feat(risk-manager): pure rules module and unit tests`

### Task 3 — Engine and entrypoint

**Files:**
- Create: `services/risk_manager/src/risk_manager/engine.py`
- Create: `services/risk_manager/src/risk_manager/__main__.py`

- [ ] Implement `engine.py` with `async def run(bus: BusClient, db: Database, settings: Settings) -> None`. The function must use an explicit outer `while True` loop and, inside it, iterate `async for` over `bus.consume(Topic.ORDER_SIGNALS, OrderSignal)` because `BusClient.consume()` yields one batch per call (follow the simulator engine pattern). For each `OrderSignal`:
  1. Attempt to fetch the strategy via `strategy_registry.crud.get_strategy(db, UUID(signal.strategy_id))` inside a `try/except StrategyNotFoundError`; on exception pass `strategy_status=None, run_mode=None` to `check_registry_mode`.
  2. If strategy found, query `strategy_runs` for the latest run for that strategy_id using a direct parameterised asyncpg query on `db.acquire()`.
  3. Call all four rule functions in sequence; stop at first `not result.passed`.
  4. On all-pass: `await bus.publish(Topic.ORDER_SIGNALS_APPROVED, signal)` and log at INFO.
  5. On any fail: construct `RiskAlert` with `source="risk_manager"`, `severity=result.severity`, `message=result.reason`, `timestamp=datetime.now(UTC)` and `await bus.publish(Topic.RISK_ALERTS, alert)`. Log at WARNING or ERROR based on severity.
- [ ] Implement `__main__.py` following the same pattern as `services/simulator/src/simulator/__main__.py`: instantiate `Settings(service_name="risk-manager")`, configure logging, construct `BusClient` and `Database`, `await bus.connect()`, `await db.connect()`, call `await engine.run(bus, db, settings)` in a `try/finally` that closes both.
- [ ] Run `uv run python -c "from risk_manager.engine import run"` to confirm importability (no runtime needed).
- [ ] Run `uv run mypy services/risk_manager/src`.
- [ ] Commit: `feat(risk-manager): engine and entrypoint`

### Task 4 — Integration test

**Files:**
- Create: `services/risk_manager/tests/conftest.py`
- Create: `services/risk_manager/tests/test_engine_integration.py`

- [ ] Create `services/risk_manager/tests/conftest.py`. Declare `pytest_plugins = ["conftest"]` pointing at the shared fixtures (same pattern as `services/strategy_registry/tests/conftest.py`). Provide a `bus` async fixture that constructs a `BusClient(redis_url, "test-risk-manager")`, calls `connect()`, flushes the test streams, and yields; closes on teardown.
- [ ] Write `tests/test_engine_integration.py` with `pytestmark = pytest.mark.integration`. The single test `test_approve_happy_path` must:
  1. Use `require_postgres` and `require_redis` fixtures.
  2. Create a strategy in `live` status using `strategy_registry.crud` (hypothesis → backtesting → paper → awaiting-approval → live with `approved_by="test"`).
  3. Create a matching `strategy_runs` row with `mode="live"` using `strategy_registry.crud.start_run`.
  4. Publish an `OrderSignal` with `strategy_id=<that id>`, `mode="live"`, `stake=Decimal("10")`, `venue=Venue.BETFAIR`, `market_id="1.23"`, `side=OrderSide.BACK`, `price=Decimal("2.0")` to `Topic.ORDER_SIGNALS`.
  5. Call `engine.run` via `asyncio.wait_for(run(bus, db, settings), timeout=3.0)` with kill-switch off, cap = 1000.
  6. Consume one message from `Topic.ORDER_SIGNALS_APPROVED` and assert it is the same signal.
  7. Assert nothing was published to `Topic.RISK_ALERTS`.
- [ ] Write a second test `test_kill_switch_blocks_live_signal` that activates `risk_kill_switch=True`, publishes a live signal, runs engine, and asserts a critical `RiskAlert` appears on `Topic.RISK_ALERTS` and nothing on `Topic.ORDER_SIGNALS_APPROVED`.
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/risk_manager/tests/test_engine_integration.py -v -m integration`.
- [ ] Commit: `feat(risk-manager): integration tests`

## Verification Plan

- Lint + format: `uv run ruff check . && uv run ruff format --check .`
- Type check: `uv run mypy services`
- Unit tests (offline): `uv run pytest services/risk_manager/tests/test_rules.py -v`
- Integration tests: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/risk_manager/tests -v -m integration`
- Full suite: `uv run pytest` (all testpaths; integration tests auto-skip if infra absent)
- Manual smoke: publish a raw `OrderSignal` JSON to `order.signals` via `redis-cli XADD`; observe `order.signals.approved` or `risk.alerts` stream entries in `redis-cli XREAD COUNT 1 STREAMS order.signals.approved 0`.

Success criteria:
- All unit tests pass offline.
- Happy-path integration test: signal flows from `order.signals` → `order.signals.approved`.
- Kill-switch integration test: live signal produces critical alert on `risk.alerts`, nothing on `order.signals.approved`.
- `uv run mypy services` returns zero errors.

## Open Dependencies / Assumptions

- `strategy_registry` package (Phase 3b) must be complete and importable; `crud.get_strategy` and `crud.start_run` are called directly.
- The `strategy_runs` table exists (created in `0002_strategy_registry.sql`) — no new migration needed.
- Venue-level notional caps are configured in GBP; currency conversion is out of scope.
- The risk manager trusts `signal.strategy_id` as a UUID string. Malformed UUIDs are caught by the `StrategyNotFoundError` path (the `UUID()` cast will raise `ValueError` — the engine should catch `ValueError | StrategyNotFoundError` and treat both as "strategy not found").
- Persistent in-flight exposure aggregation (tracking sum of open stakes per strategy) is deferred; `check_exposure` guards only against the per-signal stake exceeding the cap, not cumulative open exposure.
- Consumer group semantics: the risk manager uses a consumer group named `"risk-manager"` on `order.signals`; only one replica is expected in Phase 4.
