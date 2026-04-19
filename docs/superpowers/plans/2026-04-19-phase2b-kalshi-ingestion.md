# Phase 2b Kalshi Ingestion Scaffolding Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal

Add a Kalshi ingestion scaffold that establishes the data-contract path for `market.data` without wiring a live WebSocket runtime yet. This phase introduces typed configuration, a pure payload-to-`MarketData` mapper, and deterministic tests.

## Scope and Constraints

- In scope: Kalshi environment/config contract, pure mapping helper, mocked tests, and implementation plan documentation.
- Out of scope: live Kalshi REST/WebSocket client loop, ingestion `__main__.py` wiring, order placement, strategy lifecycle transitions, risk/execution services.
- Safety invariants:
  - No live capital path is introduced.
  - No credentials are committed; secrets remain env-only.
  - Kalshi and Betfair both publish into `Topic.MARKET_DATA` with shared `MarketData` schema and venue-specific `venue` values.

## File Responsibilities

- `services/common/src/algobet_common/config.py`
  - Add Kalshi settings fields:
    - `kalshi_api_key: Optional[str]`
    - `kalshi_api_secret: Optional[str]`
    - `kalshi_environment: Optional[str]` default `"demo"`
  - Keep defaults non-sensitive and ingestion-safe.
- `.env.example`
  - Document Kalshi env vars with empty credential defaults.
- `services/ingestion/src/ingestion/kalshi_adapter.py`
  - Add pure mapping function:
    - `kalshi_message_to_market_data(payload: dict[str, Any]) -> MarketData | None`
  - Handle malformed payloads by returning `None` instead of raising.
- `services/ingestion/tests/test_kalshi_adapter.py`
  - Add mocked unit tests for:
    - happy path mapping,
    - empty book mapping,
    - malformed payload ignored.

## Task Breakdown

### Task 1 — Kalshi config contract in shared settings

- [ ] Add optional Kalshi API credential fields to `Settings`.
- [ ] Set `kalshi_environment` default to `"demo"` while keeping type optional.
- [ ] Add `.env.example` placeholders for Kalshi env vars with empty credential values.

Why: this establishes the config boundary before runtime wiring and keeps CI safe without secrets.

### Task 2 — Pure Kalshi payload mapper

- [ ] Implement `kalshi_message_to_market_data(payload)` in `kalshi_adapter.py`.
- [ ] Map `market_ticker` (or fallback key) to `MarketData.market_id`.
- [ ] Parse timestamps from ISO strings or epoch values; default safely when absent.
- [ ] Map bids/asks ladders from payload arrays to `list[tuple[Decimal, Decimal]]`.
- [ ] Set `venue=Venue.KALSHI` and include optional `last_trade` when present.
- [ ] Return `None` for malformed payloads missing required identifiers.

Why: a pure mapper gives a stable contract for future REST/WebSocket integration while remaining fast to test.

### Task 3 — Mocked unit-test coverage

- [ ] Add at least three tests:
  - happy path payload maps all fields,
  - empty book payload maps to empty bids/asks,
  - malformed payload returns `None` (ignored safely).
- [ ] Keep tests network-free and deterministic.

Why: confirms mapper behavior now and protects future WebSocket wiring from regressions.

## Verification Plan

- Lint: `uv run ruff check .` and `uv run ruff format --check .`
- Types: `uv run mypy services`
- Tests: `uv run pytest -v services/ingestion/tests/test_kalshi_adapter.py`

Success criteria:
- Kalshi mapping scaffold is present with deterministic tests.
- Shared settings include Kalshi env contracts.
- No ingestion runtime wiring in `services/ingestion/src/ingestion/__main__.py` yet.

## Open Dependencies / Operator Inputs

- Operator-managed Kalshi credentials are still required for later runtime integration:
  - `KALSHI_API_KEY`
  - `KALSHI_API_SECRET`
- Runtime endpoint selection details (`demo` vs production hosts) will be finalized in the follow-on live integration plan.
