# Phase 3a — Simulator service (paper trading)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

## Goal

Stand up the paper-trading simulator service so strategies can emit `OrderSignal` messages and receive `ExecutionResult` fills that are bit-for-bit compatible with what the future Rust execution-engine will emit. The simulator is the first consumer of the bus end-to-end and it enforces the core project invariant: **paper and live must be a config change, not a code change**.

## Scope and Constraints

- **In scope:** new `services/simulator/` uv-workspace member; consumer of `Topic.MARKET_DATA` to maintain an in-memory order book per `(venue, market_id)`; consumer of `Topic.ORDER_SIGNALS` restricted to `mode="paper"`; deterministic fill engine; publisher of `Topic.EXECUTION_RESULTS`; persistence of orders to the existing `orders` table via `algobet_common.database`; unit + integration tests.
- **Out of scope:** live Rust execution-engine; risk manager gating (handled in Phase 3c); strategy registry CRUD (Phase 3b); dashboard/approval UI; slippage / queue-position modelling (leave deterministic-cross-the-spread as v0 and call out extensions in Open Dependencies).
- **Safety invariants:**
  - The simulator MUST refuse any `OrderSignal` where `mode != "paper"`. `mode="live"` signals must log a `RiskAlert` with severity `critical` and be dropped. This guards against accidental routing.
  - The paper-order API surface (input schema + output schema) MUST be identical to the schema the live execution-engine will consume/emit — i.e. `OrderSignal` in, `ExecutionResult` out, no simulator-only fields.
  - No network I/O beyond Redis + Postgres. No venue adapters are imported.

## File Responsibilities

- `services/simulator/pyproject.toml` — new workspace member. Depend on `algobet-common`. Mirror the `services/ingestion/pyproject.toml` layout (hatchling, packages=`src/simulator`).
- `pyproject.toml` (root) — add `simulator` to `[tool.uv.workspace].members` and to root `dependencies`.
- `services/simulator/src/simulator/__init__.py` — package marker.
- `services/simulator/src/simulator/book.py`
  - In-memory order book keyed by `(venue, market_id) -> MarketData`.
  - Updated on every `Topic.MARKET_DATA` message, last-write-wins on timestamp. Stale messages (older timestamp than cached) are ignored.
- `services/simulator/src/simulator/fills.py`
  - Pure function `match_order(signal: OrderSignal, book: MarketData) -> ExecutionResult` plus partial-fill helper.
  - Matching rules (v0, deterministic):
    - BACK / YES: fills if `book.asks[0].price <= signal.price`. Fill price = top of `asks`. Fill size = `min(signal.stake, asks[0].size)`; remainder walks the ladder until stake exhausted or no more crossing levels.
    - LAY / NO: mirror using `book.bids`.
    - Fully unfilled: return `status="placed"` (resting) with `filled_stake=0`.
    - Fully filled: `status="filled"`. Partial: `status="partially_filled"` with volume-weighted average `filled_price`.
  - No randomness, no latency modelling.
- `services/simulator/src/simulator/engine.py`
  - Async `run(bus, db, settings)` entrypoint.
  - Two concurrent consumers on `BusClient`: `MARKET_DATA` → update `book`; `ORDER_SIGNALS` → filter `mode=="paper"`, dispatch to `fills.match_order`, publish `ExecutionResult` to `EXECUTION_RESULTS`, persist order + result rows.
  - Rejects `mode=="live"` signals with a `RiskAlert` to `RISK_ALERTS`.
- `services/simulator/src/simulator/persistence.py`
  - Insert order row into `orders` table on first sight; update on fill/partial/cancel. Reuse existing `algobet_common.db.Database` pool; no new migrations.
  - `strategy_id` + `run_id` must already exist; if the registry row is missing, drop the signal and emit a `RiskAlert` (`severity="warn"`) instead of inserting a dangling order.
- `services/simulator/src/simulator/__main__.py` — `asyncio.run` entrypoint, matching the shape of `services/ingestion/src/ingestion/__main__.py`.
- `services/simulator/tests/test_fills.py`
  - Unit tests for: exact-cross full fill, no-cross rest, multi-level partial fill, LAY/NO mirror, stale book ignored, zero-size level skipped.
- `services/simulator/tests/test_engine.py`
  - Async integration test using `BusClient` against the shared Redis container (use the existing `redis_url` / `_flush_redis` fixtures from `services/common/tests/conftest.py` — extend the testpaths if needed). Tag with `pytestmark = pytest.mark.integration`.
  - Covers: live-mode signal is rejected with `RiskAlert`; paper signal round-trips to `ExecutionResult` with expected fill.
- `services/simulator/tests/conftest.py` — reuse Redis/Postgres fixtures via `pytest_plugins` or import, mirroring `services/common/tests/conftest.py`.
- `pyproject.toml` — extend `[tool.pytest.ini_options].testpaths` to include `services/simulator/tests`.
- `docker-compose.yml` — optional: add a commented-out `simulator` service stanza mirroring `ingestion`, so the operator can bring it up with `docker compose up simulator`. Leave commented for now; call out in Verification.

## Task Breakdown

### Task 1 — Workspace skeleton

- [ ] Add `services/simulator/` uv-workspace member with `pyproject.toml`, `src/simulator/__init__.py`, `src/simulator/__main__.py` (prints `simulator starting` and exits cleanly).
- [ ] Register the package in the root `pyproject.toml` workspace members and `[tool.uv.sources]`.
- [ ] Extend `testpaths` in the root `pyproject.toml` to include `services/simulator/tests`.
- [ ] `uv sync --all-packages` must succeed; CI smoke must still pass.

Why: unblocks subsequent tasks and enforces the one-workspace-member-per-service convention.

### Task 2 — In-memory book

- [ ] Implement `book.Book` with `update(MarketData)` and `get(venue, market_id) -> MarketData | None`.
- [ ] Reject stale updates by timestamp.
- [ ] Unit tests: update/get, stale-ignore, unknown-market returns None.

### Task 3 — Pure fill engine

- [ ] Implement `fills.match_order` per matching rules above.
- [ ] Implement partial-fill + VWAP helpers as private functions in the same module.
- [ ] Unit tests per the list under `test_fills.py`.

### Task 4 — Engine wiring

- [ ] Implement `engine.run` composing book + fills + bus + persistence.
- [ ] Guard live-mode signals with a `RiskAlert`.
- [ ] Structured logging on each decision (accept / reject / fill) using the service_name prefix pattern from ingestion.

### Task 5 — Persistence

- [ ] Implement `persistence.record_order` and `persistence.record_fill`.
- [ ] Missing strategy_id / run_id path emits `RiskAlert` and drops the signal.
- [ ] Tag DB-touching tests with `@pytest.mark.integration`.

### Task 6 — Integration test

- [ ] End-to-end test: publish a `MarketData` tick, publish a paper `OrderSignal` that crosses, assert an `ExecutionResult` is published with the expected fill and that an `orders` row lands in Postgres.
- [ ] Second case: publish a live-mode signal; assert it is NOT executed and that a `RiskAlert` is emitted.

## Verification Plan

- `uv run ruff check . && uv run ruff format --check .`
- `uv run mypy services`
- Unit tests (offline): `uv run pytest services/simulator/tests -m "not integration" -v`
- Full integration: `docker compose up -d && uv run pytest services/simulator/tests -v`
- Manual smoke:
  - `uv run python -m simulator` starts the engine.
  - `uv run python -m ingestion` (synthetic mode) publishes a tick.
  - Use a scratch script under `scripts/` or an ad-hoc `python -c` to publish a paper `OrderSignal` and observe the `EXECUTION_RESULTS` stream via `redis-cli XREAD`.

Success criteria:
- All tests pass.
- Live-mode signals are never fillable by the simulator.
- Simulator emits `ExecutionResult` with the same schema the future execution-engine will.

## Open Dependencies / Operator Inputs

- Strategy registry rows are assumed to exist before orders are routed. Phase 3b delivers CRUD for this; until then integration tests may insert fixtures directly.
- Fill model extensions (queue position, Betfair bet-delay, Kalshi make/take fees) are deferred. Note in the daily log when the first strategy needs them.
- Risk manager pre-flight checks (Phase 3c) are not in scope. The simulator's live-signal rejection is a belt-and-braces guard, not the primary gate.
