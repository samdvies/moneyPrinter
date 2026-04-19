# Phase 3b — Strategy Registry (Python package + lifecycle state machine)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

## Goal

Deliver the Python-side registry layer over the existing `strategies` / `strategy_runs` / `orders` Postgres tables so that the simulator (Phase 3a), the research orchestrator (Phase 4), and the dashboard (Phase 5) all speak through a single typed CRUD surface. Embed the lifecycle state machine in Python — this is the last software layer before live capital and it must be the single hard gate that enforces the `awaiting-approval → live` rule.

## Scope and Constraints

- **In scope:** new `services/strategy_registry/` uv-workspace member (library, not a running service yet); typed DTOs for `Strategy`, `StrategyRun`; async CRUD functions over the existing DB pool; lifecycle state-machine with explicit allowed transitions; approval semantics (`approved_by` + `approved_at` required to enter `live`); unit + integration tests.
- **Out of scope:** FastAPI admin router (Phase 5 / dashboard); automatic promotion based on metrics (Phase 4 research orchestrator); migrations — the existing `scripts/db/migrations/0002_strategy_registry.sql` is authoritative and MUST NOT be modified.
- **Safety invariants:**
  - The only legal path to `status="live"` is `awaiting-approval → live`, and ONLY when `approved_by` is non-null and matches a caller-supplied identifier. No other code path may write `status="live"`.
  - Every state transition goes through a single `transition(strategy_id, to_status, *, approved_by=None)` function — no module may `UPDATE strategies SET status=...` directly.
  - The promotion gate is covered by `promotion-gate-auditor` sub-agent review before merge (see CLAUDE.md agents).

## Existing-schema note

The `strategies.status` CHECK constraint in `scripts/db/migrations/0002_strategy_registry.sql` allows: `hypothesis`, `backtesting`, `paper`, `awaiting-approval`, `live`, `retired`. The lifecycle in CLAUDE.md reads `hypothesis → backtest → paper → awaiting-approval → live`. **Use the DB values verbatim** (`backtesting`, not `backtest`) and document the alias in the package README. Do not migrate the constraint in this phase.

## File Responsibilities

- `services/strategy_registry/pyproject.toml` — new uv-workspace member, depends on `algobet-common`.
- Root `pyproject.toml` — add `strategy_registry` to workspace members, `[tool.uv.sources]`, and root `dependencies`; extend `testpaths` to include `services/strategy_registry/tests`.
- `services/strategy_registry/src/strategy_registry/__init__.py` — re-export the public API: `Strategy`, `StrategyRun`, `Status`, `Mode`, `create_strategy`, `get_strategy`, `list_strategies`, `transition`, `start_run`, `end_run`.
- `services/strategy_registry/src/strategy_registry/models.py`
  - Pydantic DTOs mirroring the SQL columns. Use `StrEnum` for `Status` (six values matching the CHECK constraint) and `Mode` (three values: `backtest`, `paper`, `live`).
  - `Strategy` includes `approved_at: datetime | None` and `approved_by: str | None`.
- `services/strategy_registry/src/strategy_registry/transitions.py`
  - Declarative transition map:
    - `hypothesis → backtesting`
    - `backtesting → paper`
    - `backtesting → retired`
    - `paper → awaiting-approval`
    - `paper → retired`
    - `awaiting-approval → live` *(requires `approved_by`)*
    - `awaiting-approval → retired`
    - `live → retired`
  - Pure function `validate_transition(current, to, *, approved_by) -> None` raises `InvalidTransitionError` on any disallowed edge; raises `ApprovalRequiredError` if `to == "live"` and `approved_by` is falsy.
  - No DB access in this module — it is pure so the promotion-gate auditor can reason about it.
- `services/strategy_registry/src/strategy_registry/crud.py`
  - Async CRUD using the existing `algobet_common.db.Database` pool.
  - `transition(pool, strategy_id, to_status, *, approved_by=None)` calls `validate_transition`, then within a single transaction: `SELECT ... FOR UPDATE` the current status, re-validate (guard against TOCTOU), `UPDATE` with the new status, and when `to_status == "live"` also set `approved_by` + `approved_at = now()`.
  - All `SELECT` / `UPDATE` use parameterised queries. No f-string SQL.
- `services/strategy_registry/src/strategy_registry/errors.py`
  - Custom exceptions: `StrategyNotFoundError`, `InvalidTransitionError`, `ApprovalRequiredError`.
- `services/strategy_registry/tests/test_transitions.py` — pure unit tests (offline, no markers) covering every edge in the transition matrix and both error types.
- `services/strategy_registry/tests/test_crud.py` — integration tests hitting Postgres via the existing `postgres_dsn` / `require_postgres` fixtures. Tag with `pytestmark = pytest.mark.integration`. Use unique `slug` values per test to avoid cross-test bleed; rely on the test DB that `scripts.migrate` has already populated.
- `services/strategy_registry/tests/conftest.py` — reuse fixtures via `pytest_plugins = ["services.common.tests.conftest"]` or local re-import, same pattern the simulator plan uses.
- `services/strategy_registry/README.md` — one short page: public API, lifecycle diagram, the `backtesting` vs `backtest` naming note.

## Task Breakdown

### Task 1 — Workspace skeleton + models

- [x] Add the `services/strategy_registry/` package, wire it into workspace + testpaths.
- [x] Implement `models.py` DTOs + `Status` / `Mode` enums.
- [x] `uv sync --all-packages` must pass; mypy must be green.

### Task 2 — Pure transition map

- [x] Implement `transitions.validate_transition`.
- [x] Implement `errors.py` with the three exception types.
- [x] Unit tests in `test_transitions.py`: one test per allowed edge, one per disallowed edge (expect `InvalidTransitionError`), one for `awaiting-approval → live` without `approved_by` (expect `ApprovalRequiredError`).

Why: isolating the state-machine as a pure module lets the promotion-gate auditor verify correctness without spinning up a DB.

### Task 3 — Async CRUD

- [x] Implement `create_strategy`, `get_strategy`, `list_strategies`, `start_run`, `end_run`.
- [x] Implement `transition` with `SELECT ... FOR UPDATE` + TOCTOU re-check.
- [x] `transition` must set `approved_by` + `approved_at` atomically when entering `live`.

### Task 4 — Integration tests

- [x] `test_crud.py`: happy-path create → backtesting → paper → awaiting-approval → live (with `approved_by="operator@test"`), asserting the row in Postgres has both approval columns set.
- [x] Negative test: attempting `paper → live` raises `InvalidTransitionError` and the DB row is unchanged.
- [x] Negative test: `awaiting-approval → live` with `approved_by=None` raises `ApprovalRequiredError`.
- [x] Concurrent-update test (optional if time permits): two coroutines both trying to transition the same strategy, only one succeeds.

### Task 5 — Docs + review

- [x] Write the short README.
- [ ] Invoke `promotion-gate-auditor` via the agents team to audit `transitions.py` + `crud.py::transition` before finalising the PR. Address any NO-GO findings.

## Verification Plan

- `uv run ruff check . && uv run ruff format --check .`
- `uv run mypy services`
- Offline tests: `uv run pytest services/strategy_registry/tests -m "not integration" -v`
- Integration: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/strategy_registry/tests -v`
- Manual: open `psql` against the test DB, manually verify that `UPDATE strategies SET status='live' WHERE ...` executed via the registry's `transition` function populates both `approved_by` and `approved_at`, and that direct status updates are not performed anywhere else in the codebase (grep for `UPDATE strategies SET status`).

Success criteria:
- Every transition except `awaiting-approval → live` can be performed without approval.
- `awaiting-approval → live` requires a non-empty `approved_by` and atomically stamps both approval columns.
- Promotion-gate auditor returns GO.

## Open Dependencies / Operator Inputs

- Operator identity model is out of scope: `approved_by` is a free-form string until the dashboard (Phase 5) introduces real auth. Document this limitation in the README.
- Metric-based auto-promotion (e.g. auto-advance from `backtesting` to `paper` on Sharpe > X) is deferred to the research orchestrator.
- A future migration may want to rename `backtesting → backtest` to match CLAUDE.md; that is a separate plan.
