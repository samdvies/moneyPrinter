# Phase 2 Betfair Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal

Replace the Phase 1 dummy market-data publisher with a real Betfair Exchange streaming ingestion path that maps incoming runner ladders into `algobet_common.schemas.MarketData` and publishes them to Redis stream `market.data` using `algobet_common.bus.BusClient`.

## Scope and Constraints

- In scope: Betfair authentication, streaming subscription lifecycle, runner book-to-schema mapping, service wiring, and tests with mocked SDK objects.
- Out of scope: Kalshi ingestion, Risk Manager logic, Execution Engine logic, order placement, paper/live API implementation.
- Safety invariants:
  - No live capital or strategy lifecycle promotion logic is changed.
  - No credentials are committed; runtime credentials are environment-only.
  - TODO notes should preserve the design invariant that paper/live execution APIs must remain identical later.

## File Responsibilities

- `services/common/src/algobet_common/config.py`
  - Add ingestion-safe Betfair configuration fields (username, password, app key, cert paths, stream filter options).
  - Keep credential defaults non-sensitive (empty/optional), validated at runtime.
- `services/ingestion/pyproject.toml`
  - Add `betfairlightweight` dependency for the ingestion service.
- `services/ingestion/src/ingestion/__main__.py`
  - Replace dummy-only flow with a real ingestion runtime:
    - Build Betfair client from settings.
    - Perform cert login (or fail fast with actionable message if missing config).
    - Open stream, subscribe to market updates, and iterate updates.
    - Map updates to `MarketData` and publish on `Topic.MARKET_DATA`.
    - Handle reconnect/backoff and graceful shutdown.
  - Retain a small pure mapping unit suitable for deterministic tests.
  - Add TODO referencing the design spec section requiring identical paper/live execution APIs, without implementing those APIs now.
- `services/ingestion/tests/test_betfair_adapter.py` (new)
  - Unit tests for Betfair-to-`MarketData` mapping and ingestion loop behavior with mocked SDK surfaces.
  - Assert stream publication through a mocked `BusClient`; no external network access.
- `services/ingestion/tests/test_hello.py`
  - Replace/rename dummy publisher assertions to target the real ingestion adapter entry points (while keeping tests fast and deterministic).
- `scripts/smoke.py`
  - Keep smoke stable by using ingestion helper(s) that do not require Betfair credentials (e.g., retained synthetic publish helper), so CI remains green without live auth.

## Task Breakdown

### Task 1 — Configuration contracts for Betfair runtime

- [ ] Define Betfair settings keys in shared config with clear names and non-secret defaults.
- [ ] Validate required credential combination at runtime (not import time), so tests can run with mocked clients.
- [ ] Document expected environment variables in `.env.example` without real values.

Why: configuration must be explicit and typed so the ingestion service can fail safely and predictably when credentials are unavailable.

### Task 2 — Betfair stream adapter implementation

- [ ] Introduce an adapter layer in ingestion for:
  - client construction/login,
  - stream creation + subscription,
  - iteration over stream updates,
  - runner book conversion to internal message schema.
- [ ] Map Betfair market book data into `MarketData`:
  - `venue = betfair`,
  - `market_id` from Betfair market id,
  - `timestamp` from publish time when present (fallback to current UTC),
  - `bids`/`asks` from available-to-back/available-to-lay ladders,
  - `last_trade` from traded volume signal when derivable.
- [ ] Publish each mapped record using `BusClient.publish(Topic.MARKET_DATA, message)`.
- [ ] Implement defensive handling for empty books, non-runner changes, and malformed ladder rows (skip bad rows, continue stream).
- [ ] Add reconnect/backoff loop and shutdown-safe resource cleanup.

Why: this creates the first real market feed path while preserving the reusable bus/schema boundary established in Phase 1.

### Task 3 — Tests with mocked betfairlightweight SDK

- [ ] Add unit tests for mapping behavior:
  - full ladder mapping,
  - empty ladder mapping,
  - timestamp derivation fallback,
  - invalid/missing price-size rows ignored safely.
- [ ] Add adapter loop tests using mocked stream listeners:
  - publishes mapped messages to `market.data`,
  - ignores updates that cannot produce `MarketData`,
  - handles stream exceptions and exits/retries according to policy.
- [ ] Ensure no test performs network I/O or requires real Betfair credentials.

Why: Phase 2 must be reliable and CI-safe; SDK-mocked tests provide deterministic coverage of contract and failure behavior.

### Task 4 — Smoke/CI compatibility and guardrails

- [ ] Preserve the existing smoke path so CI can run in containerized test services without Betfair credentials.
- [ ] Keep a synthetic publish helper (or equivalent) used only for smoke/testing bootstrap.
- [ ] Add a clear startup failure message in ingestion runtime when credentials are missing, instructing operator to inject env vars securely.

Why: CI and local developer flows must continue working while real external credentials remain intentionally unavailable in automation.

## Verification Plan

- Lint: `uv run ruff check .` and `uv run ruff format --check .`
- Types: `uv run mypy services`
- Tests: `uv run pytest -v`
- Smoke: `uv run python -m scripts.smoke`
- Optional local runtime dry-check:
  - start Redis/Postgres,
  - run ingestion with mocked/offline mode or expect clear credential error when Betfair env is absent.

Success criteria:
- All existing checks remain green.
- New ingestion tests cover mapping + stream loop behavior with mocked SDK.
- Ingestion service no longer relies on dummy-only publishing for primary runtime flow.

## Open Dependencies / Operator Inputs

- Betfair developer credentials are expected from operator-managed secure channels:
  - username/password,
  - app key,
  - client cert and key file paths.
- If these are not available, implementation still proceeds with mocked tests and clear runtime error messaging; no secrets are committed.
