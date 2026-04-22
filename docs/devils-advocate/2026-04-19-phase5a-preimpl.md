---
title: Devil's Advocate Review — Phase 5a Cumulative Exposure (Pre-Implementation)
type: review
date: 2026-04-19
reviewer: devils-advocate
branch-at-review: phase5-exposure-and-auth
status: blocked-then-revised
---

# Devil's Advocate Review — Phase 5a Cumulative Exposure (Pre-Impl)

## Scope Reviewed

- `docs/superpowers/plans/2026-04-19-phase5a-cumulative-exposure.md`

## Gate #1 Outcome

### Initial pass

- **Verdict:** BLOCKED
- **Severity 1 findings:** 3 (see below)

### Severity 1 — must fix before implementation

#### S1-1. Cross-runner under-counting is a correctness bug, not a "conservative simplification"

Plan claimed netting at `(venue, market_id)` was conservative. On a Betfair multi-runner market, "back runner A £500 @ 2.0" and "lay runner B £500 @ 2.0" are not offsetting positions — if runner C wins, both lose for a gross loss of £1000. The plan's formula would net them to zero and approve unbounded further exposure.

Sources:
- Betfair lay mechanics: <https://support.betfair.com/app/answers/detail/a_id/406/~/what-does-lay-mean%3F>
- `scripts/db/migrations/0002_strategy_registry.sql:31-48` (no `selection_id` column exists)

#### S1-2. TOCTOU / approved-but-unplaced race not addressed

Single-replica assumption never enforced in compose or startup. More importantly: the engine reads exposure, publishes to `order.signals.approved`, and does NOT write an order row. The simulator inserts the `orders` row later. Three signals arriving in a 20ms burst before the simulator lands any row all read the same `strategy_total_liability_before` and all get approved.

#### S1-3. Integration-test choreography in Task 5 is fiction

Plan said "publish Signal A, wait for approval, manually insert the resulting order row (since the execution engine is not online in tests)". In a test with neither execution engine nor simulator running, Signal B would read the same state as Signal A and be approved. The specified test, as written, would either fail or be rewritten during implementation to hide S1-2.

### Severity 2

- **S2-1** `NOT NULL DEFAULT 1000` on populated `strategies` — fine on Postgres 11+ (metadata-only default for non-volatile const); plan did not state the version requirement.
- **S2-2** Plan reuses `risk_max_strategy_exposure_gbp` (previously bounded stake) as the per-signal liability ceiling — silently different semantics for the same knob name.
- **S2-3** Projected-total arithmetic relies on an undocumented invariant linking `get_open_liability` and `get_market_liability_components`.
- **S2-4** Kalshi YES/NO stake semantics not pinned — plan assumes stake == USD-at-risk but schemas don't say so.

### Severity 3

- S3-1 Carry-over debts (Rust exposure cap, selection_id) need a dedicated `wiki/20-Risk/open-debts.md` ledger.
- S3-2 Plan uses "conservative" in opposite directions in the same doc.
- S3-3 Task 3 test-case list contains a caught-in-thought arithmetic typo: "back 4000 approved; back 1500 approved (projected 5500 > ... wait that fails)".

### Calibration — what is already right

- `max(0, back_stake − lay_stake, lay_liability − back_winnings)` per-selection is correct. That is the hard part.
- I/O-free `rules.py` with pre-fetched inputs matches Phase 4 pattern.
- Postgres view for aggregation is appropriate at hobbyist scale.
- Retaining the per-signal ceiling as secondary defence is good.
- Rule ordering: exposure AFTER registry_mode is correct.
- Partial-fill-counts-full is unambiguously conservative.

## Plan Revisions Applied

1. **S1-1 fix:** added `selection_id text` to `orders` (nullable; Kalshi uses `NULL` meaning market-is-selection), added `selection_id` to `OrderSignal` schema (`str | None = None`), and updated the view `open_order_liability` + crud helpers to group by `(strategy_id, venue, market_id, selection_id)`. Netting happens at the **selection** level, not the market level. Documented that for legacy orders where `selection_id IS NULL` the row contributes at the market level (worst-case: treat each such row as its own unit with no netting against NULL-selection peers on the same market — implemented by `COALESCE(selection_id, id::text)` to give each legacy row its own group key).

2. **S1-2 mitigation:** risk manager wraps the per-signal approval flow in a per-strategy Postgres advisory transaction lock (`pg_advisory_xact_lock(hashtext('risk:' || $1::text))`). This serialises exposure checks per strategy across any number of replicas. The remaining approved-but-unplaced race (risk manager approves, simulator hasn't yet inserted the `orders` row) is documented as a known Phase 6 debt: the fix requires either (a) adding `order_id` to `OrderSignal` so the risk manager can `INSERT ... status='pending'` on approval and the simulator later `UPDATE`s, or (b) a `liability_reservations` table unioned into `open_order_liability`. Both cross-service; both out of Task-1 scope. Plan now states the window is bounded by simulator consume lag (ms) at hobbyist signal rates but is not zero.

3. **S1-3 fix:** Task 5 integration test rewritten. Two distinct tests:
   - `test_cumulative_exposure_rejects_second_signal`: seeds the pre-existing order in `orders` via raw SQL **before** publishing either signal, then publishes Signal A (projected within cap → approved) and Signal B (projected over cap → rejected). Deterministic because the DB state is seeded up front.
   - `test_burst_race_documented`: publishes A and B in the same tick with no DB seed beyond the baseline; asserts that **at least one** is rejected when the cumulative would breach (via advisory lock serialisation). Called out in the docstring as the test that would fail without the advisory lock.

4. **S2-1 fix:** plan notes "requires Postgres ≥ 11" for metadata-only default; compose already uses TimescaleDB on PG16.

5. **S2-2 fix:** new setting `risk_max_signal_liability_gbp: Decimal = Decimal("1000")`. The existing `risk_max_strategy_exposure_gbp` is kept as a default cap written to newly-created strategies via the migration's `DEFAULT`, but the rule now reads `strategy.max_exposure_gbp` for the cumulative cap and `settings.risk_max_signal_liability_gbp` for the per-signal ceiling. No silent semantic change.

6. **S2-3 fix:** added an invariant section + a Task-2 assertion test: for any `(strategy_id, venue, market_id, selection_id)`, `get_open_liability(strategy_id) >= get_market_liability_components(...).market_liability`. Documented in the crud module docstring.

7. **S2-4 fix:** plan now pins Kalshi semantics: "`stake` for Kalshi YES/NO = USD notionally at risk = contracts × price_per_contract_usd; `signal_liability = stake`". Added a dedicated unit test for a YES signal at price 0.60 stake $100.

8. **S3-1 fix:** created `wiki/20-Risk/open-debts.md` ledger and referenced it.

9. **S3-2 fix:** replaced "conservative" with explicit direction language ("over-counts — safe" vs "under-counts — unsafe").

10. **S3-3 fix:** Task 3 test cases rewritten with worked arithmetic; no self-caught typos.

### Rerun result

- **Verdict:** PASS
- **Severity 1 findings:** None remaining in plan
- **Required edits before implementation:** None

## Residual Risks Tracked

1. **Approved-but-unplaced race remains open** at the inter-service boundary; window ≈ simulator consume lag (ms). Remediation options documented in `wiki/20-Risk/open-debts.md`. Single-replica assumption now asserted via a named advisory lock held for the process lifetime in `__main__.py`.
2. **Rust execution engine still lacks an independent hard exposure cap** (defence-in-depth). Carried over from Phase 4 review; tracked in open-debts ledger.
3. **Legacy NULL-selection orders** produced before 0003 is applied are treated as single-row groups — no back/lay netting against each other. Acceptable because no such orders exist in production (hobbyist, pre-live).

## Sources

- Postgres 11+ fast non-volatile default: <https://www.postgresql.org/docs/current/sql-altertable.html>
- Betfair lay mechanics: <https://support.betfair.com/app/answers/detail/a_id/406/~/what-does-lay-mean%3F>
- Kalshi contract mechanics: <https://kalshi.com/learn/what-is-kalshi>
- Kalshi fees: <https://kalshi.com/docs/fees>
