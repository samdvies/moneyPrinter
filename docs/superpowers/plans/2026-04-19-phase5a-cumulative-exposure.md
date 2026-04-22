# Phase 5a — Cumulative Exposure Enforcement in Risk Manager

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the per-signal stake gate in `risk_manager` with a **cumulative open-liability** check that correctly models Betfair's asymmetric lay liability and Kalshi's symmetric stake risk, nets back/lay at the **selection** level, and rejects any signal whose approval would push a strategy's projected exposure above its configured cap. Retain a per-signal liability ceiling as a secondary hard stop. Serialise per-strategy exposure checks via a Postgres advisory lock to close the cross-replica race.

**Architecture:** Rules stay I/O-free (`rules.py`). The engine (`engine.py`) pre-fetches the strategy row (now including `max_exposure_gbp`), its latest run mode, its current open liability, and the `LiabilityComponents` for the signal's `(venue, market_id, selection_id)` group inside a single advisory-locked transaction per strategy. Open liability is computed by a new Postgres view `open_order_liability` over the existing `orders` table. A migration adds `max_exposure_gbp` on `strategies` and `selection_id` on `orders`.

**Tech Stack:** Python 3.12, `algobet_common`, `asyncpg`, `pytest`, `pytest-asyncio`. SQL: PostgreSQL ≥ 11 (compose uses TimescaleDB on PG16).

---

## Scope and Constraints

- **In scope:**
  - Migration `0003_open_exposure.sql`: adds `strategies.max_exposure_gbp numeric(12,4) NOT NULL DEFAULT 1000`, adds `orders.selection_id text NULL`, creates view `open_order_liability` aggregating worst-case liability per `(strategy_id, venue, market_id, selection_id)`.
  - Add `selection_id: str | None = None` to `OrderSignal` in `algobet_common.schemas`. Kalshi YES/NO signals may leave it `NULL`; Betfair signals should populate it (enforced in Phase 6 ingestion / strategy emitters — not this phase).
  - `Strategy` model gains `max_exposure_gbp: Decimal` (default `Decimal("1000")`).
  - New `crud.get_open_liability(db, strategy_id) -> Decimal` and `crud.get_market_liability_components(db, strategy_id, venue, market_id, selection_id)` plus `LiabilityComponents` dataclass.
  - Replacement `rules.check_exposure(signal, *, strategy_total_liability_before, market_components_before, max_exposure_gbp, per_signal_cap_gbp) -> RuleResult`.
  - Engine wires pre-fetched values into `check_exposure`, wraps exposure-check + publish in a per-strategy Postgres advisory lock transaction.
  - New setting `risk_max_signal_liability_gbp: Decimal = Decimal("1000")` (keeps the existing `risk_max_strategy_exposure_gbp` for backward compat; the new setting is what the per-signal ceiling reads).
  - Unit and integration tests per the task breakdown.

- **Out of scope:**
  - `order_id` in `OrderSignal` + risk manager writing `orders` rows on approval (one remediation option for the approved-but-unplaced race) — tracked as Phase 6 debt in `wiki/20-Risk/open-debts.md`.
  - `liability_reservations` table (the other remediation option) — tracked in the same ledger.
  - Rust-side independent hard exposure cap — carried over from Phase 4 review; tracked in ledger.
  - Schema change to persist `filled_stake` (to replace the worst-case partial-fill assumption) — deferred.
  - Per-market notional caps distinct from per-strategy. Venue-level cap already exists in Phase 4.
  - Multi-currency conversion (GBP only).
  - Historical / closed-order exposure. Only `status IN ('pending', 'placed', 'partially_filled')` counts.

- **Safety invariants:**
  - The engine MUST NOT republish to `order.signals.approved` on any rule failure.
  - `check_exposure` MUST be called with pre-fetched values; `rules.py` stays I/O-free so unit tests remain offline.
  - Projected liability comparison uses `>`, not `>=`.
  - A partially-filled order contributes its FULL `stake` to open liability (over-counts → safe). The schema does not persist `filled_stake`, so eliminating this slack is a schema change deferred to a later phase.
  - Back/lay netting happens at the **selection** level — `(strategy_id, venue, market_id, selection_id)`. Rows with `selection_id IS NULL` are grouped as standalone rows by using `COALESCE(selection_id, 'order:' || id::text)` as the group key, so legacy NULL-selection rows never net against each other (over-counts → safe for multi-runner markets).
  - Exposure check + publish runs inside a transaction holding `pg_advisory_xact_lock(hashtext('risk:exposure:' || strategy_id::text))`. This serialises concurrent checks for the same strategy across replicas.
  - The service holds a process-lifetime advisory lock on `hashtext('risk:singleton')` at startup and aborts if already held — asserts single-replica operation (the approved-but-unplaced remediation depends on this).
  - Lay liability formula: `(price - 1) * stake`. Back, YES, NO liability: `stake`. Kalshi YES/NO `stake` is interpreted as USD at risk = contracts × price_per_contract_usd.

## Liability Model

For a set of open orders on `(strategy_id, venue, market_id, selection_id_key)` where `selection_id_key = COALESCE(selection_id, 'order:' || id::text)`:

```
S_back_stake     = SUM(stake)             over side ∈ {back, yes, no}
S_lay_stake      = SUM(stake)             over side = lay
S_back_winnings  = SUM(stake * (price-1)) over side ∈ {back, yes, no}
S_lay_liability  = SUM(stake * (price-1)) over side = lay

loss_outcome     = S_back_stake - S_lay_stake
win_outcome      = S_lay_liability - S_back_winnings

market_liability = max(0, loss_outcome, win_outcome)
```

Strategy open liability = `SUM(market_liability)` over all `(venue, market_id, selection_id_key)` groups with open orders.

**Signal's own contribution:**

| side             | signal_liability   | Adds to back_stake? | Adds to lay_stake? | back_winnings δ | lay_liability δ |
|------------------|--------------------|---------------------|--------------------|-----------------|-----------------|
| `back`, `yes`, `no` | `stake`            | yes (`+stake`)      | no                 | `+stake*(price-1)` | 0              |
| `lay`            | `(price-1)*stake`  | no                  | yes (`+stake`)     | 0                  | `+stake*(price-1)` |

**Invariant (enforced by tests):** for any `(strategy_id, venue, market_id, selection_id_key)`, `get_open_liability(strategy_id) >= get_market_liability_components(...).market_liability`. This makes the `projected_total = total_before − market_liability_before + market_liability_after` arithmetic sound.

**Projected liability** for a signal's group:

```
Re-compute S_* with the signal's contribution added:
  market_liability_after = max(0, loss_after, win_after)
projected_total = strategy_total_liability_before
                - market_components_before.market_liability
                + market_liability_after
```

## Database Objects

Migration `scripts/db/migrations/0003_open_exposure.sql`:

```sql
ALTER TABLE strategies
    ADD COLUMN max_exposure_gbp numeric(12, 4) NOT NULL DEFAULT 1000;

ALTER TABLE orders
    ADD COLUMN selection_id text;
CREATE INDEX idx_orders_venue_market_selection
    ON orders (venue, market_id, selection_id);

CREATE VIEW open_order_liability AS
SELECT
    strategy_id,
    venue,
    market_id,
    COALESCE(selection_id, 'order:' || id::text) AS selection_id_key,
    COALESCE(SUM(stake)             FILTER (WHERE side IN ('back','yes','no')), 0) AS back_stake,
    COALESCE(SUM(stake)             FILTER (WHERE side = 'lay'),                 0) AS lay_stake,
    COALESCE(SUM(stake*(price-1))   FILTER (WHERE side IN ('back','yes','no')), 0) AS back_winnings,
    COALESCE(SUM(stake*(price-1))   FILTER (WHERE side = 'lay'),                 0) AS lay_liability
FROM orders
WHERE status IN ('pending', 'placed', 'partially_filled')
GROUP BY strategy_id, venue, market_id, COALESCE(selection_id, 'order:' || id::text);
```

`NOT NULL DEFAULT 1000` on a populated `strategies` table is metadata-only on Postgres ≥ 11 (non-volatile default), so no table rewrite.

## File Responsibilities

- `scripts/db/migrations/0003_open_exposure.sql` — additive migration as above.
- `services/common/src/algobet_common/schemas.py` — add `selection_id: str | None = None` to `OrderSignal`. Non-breaking; existing tests remain valid.
- `services/common/src/algobet_common/config.py` — add `risk_max_signal_liability_gbp: Decimal = Decimal("1000")`. Keep `risk_max_strategy_exposure_gbp` untouched (used as the strategy-row default in migration comments; the engine no longer reads it directly for per-signal logic).
- `services/strategy_registry/src/strategy_registry/models.py` — add `max_exposure_gbp: Decimal` to `Strategy`; add `LiabilityComponents` dataclass (frozen, 4 Decimal fields + `market_liability` property).
- `services/strategy_registry/src/strategy_registry/crud.py`:
  - `_row_to_strategy` reads `max_exposure_gbp`.
  - `get_open_liability(db, strategy_id) -> Decimal`.
  - `get_market_liability_components(db, strategy_id, venue, market_id, selection_id) -> LiabilityComponents`. Note `selection_id` parameter may be `None`.
- `services/risk_manager/src/risk_manager/rules.py`:
  - Replace `check_exposure(signal, settings)` with the new keyword-argument signature (see Task 3).
- `services/risk_manager/src/risk_manager/engine.py`:
  - Add helper to acquire the per-strategy advisory lock and fetch the three exposure inputs in one transaction.
  - Wire new arguments into `check_exposure`.
  - Ordering: `check_kill_switch` → `check_venue_notional` → `check_registry_mode` → `check_exposure`.
- `services/risk_manager/src/risk_manager/__main__.py`:
  - On startup, acquire a Postgres session advisory lock on `hashtext('risk:singleton')` via a dedicated connection kept open for process lifetime. If `pg_try_advisory_lock` returns `false`, log `critical` and exit non-zero.
- `services/risk_manager/tests/test_rules.py` — replace `TestCheckExposure`.
- `services/risk_manager/tests/test_engine_integration.py` — add two new integration tests.
- `services/strategy_registry/tests/test_liability.py` — new integration-tagged test file covering the crud helpers + invariant.
- `wiki/20-Risk/open-debts.md` — new ledger tracking carry-over risk debt (create in Task 1).

## Task Breakdown

### Task 1 — Migration 0003, schema field, and risk-debt ledger

**Files:**
- Create: `scripts/db/migrations/0003_open_exposure.sql`
- Modify: `services/common/src/algobet_common/schemas.py`
- Modify: `services/strategy_registry/src/strategy_registry/models.py`
- Modify: `services/strategy_registry/src/strategy_registry/crud.py` (only `_row_to_strategy`)
- Create: `wiki/20-Risk/open-debts.md`

- [ ] Write migration `0003_open_exposure.sql` exactly as in "Database Objects" above.
- [ ] Add `selection_id: str | None = Field(default=None)` to `OrderSignal`.
- [ ] Add `max_exposure_gbp: Decimal = Decimal("1000")` to `Strategy`.
- [ ] Update `_row_to_strategy` to read `max_exposure_gbp` from the row.
- [ ] Create `wiki/20-Risk/open-debts.md` with frontmatter and three tracked debts:
  1. Approved-but-unplaced race (Phase 5 leaves it; options documented: `order_id` in OrderSignal + risk-manager-writes-orders, OR `liability_reservations` table).
  2. Rust execution engine independent exposure cap (carry-over from Phase 4).
  3. `filled_stake` column to tighten partial-fill conservatism.
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate`; verify: `docker compose exec postgres psql -U algobet -d algobet -c "\d strategies"` shows `max_exposure_gbp`, `"\d orders"` shows `selection_id`, `"SELECT * FROM open_order_liability LIMIT 1"` succeeds (empty result OK).
- [ ] Run `uv run pytest services/strategy_registry/tests services/common/tests -v` to confirm no regressions.
- [ ] Commit: `feat(strategy-registry): migration 0003 exposure view + selection_id + max_exposure_gbp`

### Task 2 — Liability crud helpers + offline invariant tests

**Files:**
- Modify: `services/strategy_registry/src/strategy_registry/models.py` (`LiabilityComponents`)
- Modify: `services/strategy_registry/src/strategy_registry/crud.py`
- Create: `services/strategy_registry/tests/test_liability.py`

- [ ] Define `LiabilityComponents` (frozen dataclass) with four `Decimal` fields: `back_stake`, `lay_stake`, `back_winnings`, `lay_liability`. Provide a `market_liability: Decimal` property computing `max(Decimal("0"), back_stake - lay_stake, lay_liability - back_winnings)`.
- [ ] Implement `async def get_open_liability(db, strategy_id) -> Decimal`:
  - Query `open_order_liability` filtered by `strategy_id`.
  - Build `LiabilityComponents` per row, sum `.market_liability`. Return `Decimal("0")` when empty.
- [ ] Implement `async def get_market_liability_components(db, strategy_id, venue, market_id, selection_id) -> LiabilityComponents`:
  - Match on `selection_id_key = COALESCE($4, 'order:' || <impossible>)` — i.e. pass `selection_id` straight through in the WHERE clause: `WHERE strategy_id=$1 AND venue=$2 AND market_id=$3 AND selection_id_key = COALESCE($4, '__none__')`. Since legacy NULL-selection rows use `order:<uuid>` as their key, they never match a `NULL` input — a fresh signal on a market with no historical orders correctly gets zero components.
  - Return zero-valued components if no row.
- [ ] Write `services/strategy_registry/tests/test_liability.py` with `pytestmark = pytest.mark.integration`. Seed a live strategy via fixtures (copy the `live_strategy` pattern from risk_manager integration tests). Insert orders via raw SQL to isolate from simulator changes. Cases:
  1. No open orders → `get_open_liability == 0`.
  2. Back `stake=100 @ price=3.0`, `selection_id='A'` → `market_liability = max(0, 100-0, 0-200) = 100`; `total = 100`.
  3. Lay `stake=100 @ price=3.0`, `selection_id='A'` → `market_liability = max(0, -100, 200) = 200`; `total = 200`.
  4. Back `100 @ 2.0` + lay `100 @ 2.0`, same `selection_id='A'` → components `back_stake=100, lay_stake=100, back_winnings=100, lay_liability=100`; `market_liability = max(0, 0, 0) = 0`; total = 0.
  5. Back `100 @ 2.0` on `selection_id='A'` + lay `100 @ 2.0` on `selection_id='B'` same market → two separate groups, each contributes 100 → total = 200. (This is the multi-runner safety case.)
  6. Two markets: back `100 @ 2.0` on market A sel='X' + lay `50 @ 4.0` on market B sel='Y' → 100 + 150 = 250.
  7. Orders in status `filled` or `cancelled` do NOT contribute.
  8. Order in status `partially_filled` contributes full `stake`.
  9. Legacy NULL-selection row: back `100 @ 2.0` with `selection_id=NULL` + back `100 @ 2.0` with `selection_id=NULL` on same market → two separate groups (different `order:<uuid>` keys) → total = 200 (no netting against each other). Asserts conservative behaviour for legacy rows.
  10. **Invariant test:** after inserting orders of mixed kinds, assert `get_open_liability(strategy_id) >= get_market_liability_components(strategy_id, v, m, s).market_liability` for every distinct `(v, m, s)` present.
- [ ] Run `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/strategy_registry/tests/test_liability.py -v -m integration`.
- [ ] Run `uv run mypy services/strategy_registry/src` and `uv run ruff check services/strategy_registry`.
- [ ] Commit: `feat(strategy-registry): get_open_liability helpers with selection-level netting`

### Task 3 — Rewrite check_exposure + unit tests

**Files:**
- Modify: `services/risk_manager/src/risk_manager/rules.py`
- Modify: `services/risk_manager/tests/test_rules.py`
- Modify: `services/common/src/algobet_common/config.py` (new setting)

- [ ] Add `risk_max_signal_liability_gbp: Decimal = Decimal("1000")` to `Settings`.
- [ ] Replace `check_exposure` with:
  ```python
  def check_exposure(
      signal: OrderSignal,
      *,
      strategy_total_liability_before: Decimal,
      market_components_before: LiabilityComponents,
      max_exposure_gbp: Decimal,
      per_signal_cap_gbp: Decimal,
  ) -> RuleResult
  ```
- [ ] Compute `signal_liability` and updated components per the Liability Model table.
- [ ] Build `market_components_after = LiabilityComponents(...)` with the deltas added.
- [ ] `market_liability_after = market_components_after.market_liability`.
- [ ] `projected_total = strategy_total_liability_before − market_components_before.market_liability + market_liability_after`.
- [ ] Decision rules, in order:
  1. If `signal_liability > per_signal_cap_gbp` → warn reject with reason `f"signal liability {signal_liability} exceeds per-signal ceiling {per_signal_cap_gbp}"`.
  2. If `projected_total > max_exposure_gbp` → warn reject with reason `f"projected strategy liability {projected_total} would exceed cap {max_exposure_gbp}"`.
  3. Else → `RuleResult.ok()`.
- [ ] Rewrite `TestCheckExposure` with the following cases (worked arithmetic; no typos):
  - `test_two_concurrent_backs_same_market`: existing state `strategy_total=500, market_components_before=(back_stake=500, lay_stake=0, back_winnings=500, lay_liability=0)` (one back @ 2.0 of stake 500). New signal: back 600 @ 2.0. Projected market_after: back_stake=1100, winnings=1100, loss_outcome=1100, win_outcome=-1100, market_liability_after=1100. projected_total = 500 − 500 + 1100 = 1100. Cap 1000. **Rejected.**
  - `test_back_plus_lay_same_selection_nets_to_zero`: existing `strategy_total=500, before=(500, 0, 500, 0)`. Signal: lay 500 @ 2.0 same selection. After: (500, 500, 500, 500) → loss=0, win=0, market_after=0. projected = 500 − 500 + 0 = 0. **Approved** (cap 1000).
  - `test_partial_fill_counts_full_stake`: existing order status `partially_filled` stake 300 @ 2.0. `strategy_total=300, before=(300,0,300,0)`. Signal: back 800 @ 2.0. Projected market_after: (1100, 0, 1100, 0) → market=1100. projected = 300 − 300 + 1100 = 1100. **Rejected.**
  - `test_lay_extreme_price_trips_per_signal_ceiling`: existing zero. Signal: lay 60 @ 20.0. `signal_liability = (20-1)*60 = 1140`. Ceiling 1000. **Rejected with per-signal reason.**
  - `test_strategy_override_allows_higher_cap`: existing zero. Signal: back 4500 @ 2.0. `max_exposure_gbp = 5000`, per-signal ceiling = 5000. signal_liability = 4500 ≤ 5000. projected = 0 − 0 + 4500 = 4500 ≤ 5000. **Approved.** Second signal back 600 @ 2.0 with same override; existing state now `strategy_total=4500, before=(4500,0,4500,0)`. Projected after: (5100, 0, 5100, 0) → market=5100, projected=5100 > 5000. **Rejected.**
  - `test_kalshi_yes_at_60_cents_stake_100`: Signal `side=YES, stake=100, price=0.60` (USD-at-risk semantics). Existing zero. signal_liability = 100. Ceiling 1000, cap 1000. **Approved.**
  - `test_signal_liability_ceiling_independent_of_cumulative`: existing zero, but signal alone breaches per-signal ceiling: back 1500 @ 2.0, ceiling 1000, cap 5000. Even with cap room, **rejected with per-signal reason**.
- [ ] Run `uv run pytest services/risk_manager/tests/test_rules.py -v -m unit`; confirm green.
- [ ] Run `uv run mypy services/risk_manager/src` and `uv run ruff check services/risk_manager`.
- [ ] Commit: `feat(risk-manager): cumulative exposure check with selection-level netting`

### Task 4 — Engine wiring + advisory locking

**Files:**
- Modify: `services/risk_manager/src/risk_manager/engine.py`
- Modify: `services/risk_manager/src/risk_manager/__main__.py`

- [ ] Add `async def _acquire_exposure_context(db, signal) -> tuple[Strategy | None, str | None, Decimal, LiabilityComponents]`. The function:
  1. Opens a transaction on a connection from `db.acquire()`.
  2. Executes `SELECT pg_advisory_xact_lock(hashtext('risk:exposure:' || $1::text))` with `strategy_id` — serialises same-strategy checks across replicas.
  3. Fetches the `Strategy` row (`crud.get_strategy`), latest run mode (existing query), `crud.get_open_liability`, and `crud.get_market_liability_components(..., signal.selection_id)`.
  4. Returns the tuple. The caller publishes the approval/alert inside the same transaction (commits on context exit).
- [ ] `_apply_rules` now receives the extra inputs and calls `check_exposure` with them. Rule ordering: kill-switch → venue-notional → registry-mode → exposure. Rationale: kill-switch and venue-notional are stateless and cheap; registry-mode establishes strategy existence; exposure depends on strategy existing.
- [ ] Engine's main loop: for each signal, call `_acquire_exposure_context`; inside the `async with` transaction block, run `_apply_rules` and publish to `order.signals.approved` or `risk.alerts` before exiting the block (so the lock releases after the downstream publish).
- [ ] `__main__.py`: before `engine.run`, acquire a session advisory lock via a long-lived connection: `SELECT pg_try_advisory_lock(hashtext('risk:singleton'))`. If `false`, log `critical("another risk manager is already running")` and `sys.exit(2)`. If `true`, keep the connection open for the process lifetime (store on the module or in a closure that the finally block closes last).
- [ ] Run `uv run mypy services/risk_manager/src`.
- [ ] Commit: `feat(risk-manager): advisory-locked exposure check + singleton gate`

### Task 5 — Integration tests

**Files:**
- Modify: `services/risk_manager/tests/test_engine_integration.py`

- [ ] Add `test_cumulative_exposure_rejects_second_signal`:
  1. Use `live_strategy` fixture (max_exposure_gbp = 1000).
  2. Seed a `placed` order via raw SQL: stake 700, price 2.0, side back, market 1.99, selection 'A'. This represents a pre-existing open back order.
  3. Publish Signal A: back stake 250 @ 2.0, market 1.99, selection 'A'. Projected market_liability after: 950. Projected total: 950 ≤ 1000 → approve.
  4. Still inside the test: seed the resulting `placed` order for A via raw SQL (matching the simulator's `record_order` shape). This advances DB state to reflect A's approval.
  5. Publish Signal B: back stake 200 @ 2.0, market 1.99, selection 'A'. Projected market_liability after: 1150. Projected total: 1150 > 1000 → reject.
  6. Run engine bounded (`_run_engine_bounded`) after each publish so both messages drain before asserting.
  7. Assert `Topic.ORDER_SIGNALS_APPROVED` contains exactly one message (Signal A).
  8. Assert `Topic.RISK_ALERTS` contains exactly one `warn` alert whose message mentions "projected" and "exceed".

- [ ] Add `test_burst_race_serialised_by_advisory_lock`:
  1. Same fixtures; seed pre-existing back £700 @ 2.0 market 1.99 selection 'A'.
  2. Publish two signals back-to-back with **no** order seeded between them: Signal A (stake 250), Signal B (stake 200).
  3. Run the engine for `_ENGINE_TIMEOUT`. Without writing orders between signals, the strategy_total_liability_before seen by both signals is 700. Signal A projects 950 → approved. Signal B projects 900 (under cap using the same stale state) → would be approved too.
  4. Because the advisory lock only serialises the *check*, it does NOT close the approved-but-unplaced window. This test therefore asserts the current *documented* behaviour: both signals get approved. The test's docstring cites `wiki/20-Risk/open-debts.md` as the ledger for the full fix (risk-manager-writes-orders or reservations table).
  5. This is a **regression guard** — when the approved-but-unplaced fix lands, this test will flip and must be rewritten to assert only one approval. Mark with a TODO comment.

- [ ] Run `docker compose up -d && uv run python -m scripts.migrate && uv run pytest services/risk_manager/tests/test_engine_integration.py -v -m integration`.
- [ ] Commit: `test(risk-manager): integration tests for cumulative exposure + race ledger`

## Verification Plan

- Lint: `uv run ruff check . && uv run ruff format --check .`
- Typecheck: `uv run mypy services`
- Unit: `uv run pytest -m unit`
- Full suite: `docker compose up -d && uv run python -m scripts.migrate && uv run pytest`
- Manual sanity: seed two orders (back 700 @ 2.0, lay 500 @ 2.0 same market+selection) and call `get_open_liability` in a one-liner; expected 200.

Success criteria:
- All Task 3 unit tests pass.
- Both integration tests pass.
- `uv run mypy services` green.
- Starting a second `risk_manager` process fails fast with "another risk manager is already running".

## Open Dependencies / Assumptions / Known Limitations

- **Approved-but-unplaced race** remains open. Window ≈ simulator consume lag (ms). Full fix is cross-service and tracked in `wiki/20-Risk/open-debts.md`. The singleton advisory lock limits exposure to this one process; the per-strategy advisory lock serialises concurrent checks on the same strategy, but neither prevents a burst of signals from reading stale state before the simulator writes the first order row.
- **Rust execution engine** still lacks independent hard cap. Tracked.
- **Partial-fill slack**: `partially_filled` counts full stake until schema adds `filled_stake`. Tracked.
- **Selection identity**: `selection_id` is now a first-class column. Phase 6 ingestion work should populate it from Betfair `selectionId` and from Kalshi ticker/market identifiers.
- **Cross-run aggregation**: liability sums across all open orders for a strategy, regardless of `run_id`. Desired.
- **GBP only**: Kalshi USD amounts are treated as GBP for the cap comparison. Currency conversion deferred; operator must set caps in the relevant currency if running Kalshi (or set per-venue caps).
- **Postgres ≥ 11** required for metadata-only default on `ADD COLUMN ... NOT NULL DEFAULT 1000`. Compose already uses PG16. CI runs the migration so any regression surfaces immediately.
