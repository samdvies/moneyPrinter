# Polymarket CLOB Book-Depth Ingestion

**Branch to create:** `polymarket-clob-book-depth`
**Branch cut from:** `main` at `d2c3db0`
**Intended executor:** Either a cloud agent or the operator locally. Read CLAUDE.md + this file + referenced files before touching code.
**Estimated size:** 3-6 hours. Single-service change plus contract updates.

---

## Context

The current `services/ingestion/src/ingestion/polymarket_adapter.py` polls `https://gamma-api.polymarket.com/markets` every 5 s and emits one `MarketData` per CLOB `token_id`. **It does not fetch real book depth.** The emitted `bids` and `asks` are synthetic single-level entries derived from Gamma's `outcomePrices` midpoint with `size=Decimal("0")` sentinels:

- YES side: `bids=[(best_bid, 0)], asks=[(best_ask, 0)]`
- NO side: both empty lists — Gamma does not expose the NO book

Downstream consequences, confirmed in the prior paper-trade trace:

1. The simulator cannot fill any Polymarket signal. Orders rest at `status='placed', filled_stake=0`.
2. Paper P&L is therefore identically zero.
3. The validation framework (`backtest_engine.validate`) cannot evaluate any strategy whose mechanism depends on depth or NO-side price — which is every strategy in:
   - [[../../wiki/30-Strategies/polymarket-book-imbalance]]
   - [[../../wiki/30-Strategies/polymarket-yes-mean-revert]] (partially — it only needs a mid, but exits require real book)
   - and any negRisk-basket or YES/NO-complement arbitrage listed in [[../../wiki/30-Strategies/polymarket-strategy-shortlist]]

This plan adds a **second** polling path in the adapter — `clob.polymarket.com/book?token_id=<tid>` — and merges real depth into the `MarketData` payload so the simulator (and real-execution adapters later) see actual `(price, size)` levels on both YES and NO sides.

Relevant references:
- [Polymarket CLOB docs — `/book`](https://docs.polymarket.com/developers/CLOB/prices-books/get-book)
- Existing Gamma poll loop: `services/ingestion/src/ingestion/polymarket_adapter.py:1-200` (approximate; read the file first)
- Schema: `packages/algobet_common/src/algobet_common/schemas.py` `MarketData`
- Simulator fill semantics: `services/simulator/src/simulator/` (read-through before deciding on depth-awareness changes)

---

## Deliverable — book-depth-aware Polymarket ingestion

### Location

- `services/ingestion/src/ingestion/polymarket_adapter.py` — extended
- `services/ingestion/src/ingestion/polymarket_clob_client.py` — **new**, thin async client around `clob.polymarket.com`
- `services/ingestion/tests/test_polymarket_clob_client.py` — **new**
- `services/ingestion/tests/test_polymarket_adapter_with_depth.py` — **new**
- `packages/algobet_common/src/algobet_common/schemas.py` — **only if** the existing `MarketData` shape cannot already carry multi-level depth (check first; the current shape is `bids: list[tuple[Decimal, Decimal]], asks: list[tuple[Decimal, Decimal]]` which IS multi-level — so no schema change should be needed. Confirm empirically before editing.)

### Behaviour

1. For each CLOB `token_id` emitted from the Gamma poll loop, fetch `/book?token_id=<tid>` with a bounded concurrency (default 8 in-flight requests) and a bounded per-request timeout (default 2 s).
2. Parse the response into typed levels. Polymarket book response shape:
   ```
   {"bids": [{"price": "0.42", "size": "120"}, ...], "asks": [...], "market": "...", "asset_id": "..."}
   ```
   Map into `list[tuple[Decimal, Decimal]]` using existing `parse_decimal`. Preserve book ordering (bids descending, asks ascending) exactly as returned.
3. If `/book` returns an empty book (market paused / uninitialised / just-resolved), emit the existing Gamma-derived fallback (`size=0` sentinel) and log at WARNING with the `token_id` so we can track frequency.
4. If `/book` times out or errors, **do not block the Gamma loop**. Emit the fallback; increment a counter (`polymarket_book_fetch_errors_total` style — see existing log-based metrics in the service, add if absent). The Gamma loop's cadence is the SLA; book is best-effort enrichment.
5. Emit **one** `MarketData` per `token_id` per Gamma cycle with the richer depth populated — do not add a separate message type. Strategies should not care whether depth came from Gamma or CLOB.
6. Preserve all existing fields: `venue=POLYMARKET`, `market_id=<token_id>`, `timestamp=<Gamma poll timestamp>`. Book depth carries the freshest observation but uses the Gamma poll time for cross-market ordering.

### Configuration

Add to `Settings` (under `algobet_common` or ingestion-local — match existing pattern):

| Env var | Default | Purpose |
|---|---|---|
| `POLYMARKET_CLOB_BOOK_ENABLED` | `true` | Kill switch; `false` reverts to Gamma-only |
| `POLYMARKET_CLOB_BOOK_BASE_URL` | `https://clob.polymarket.com` | For tests + future self-hosting |
| `POLYMARKET_CLOB_BOOK_TIMEOUT_S` | `2.0` | Per-request |
| `POLYMARKET_CLOB_BOOK_CONCURRENCY` | `8` | Bounded semaphore |
| `POLYMARKET_CLOB_BOOK_LEVELS` | `10` | Cap on levels preserved per side |

Do **not** bake API keys or L2 credentials into this plan — `/book` is an unauthenticated read endpoint.

### Egress guard

The existing `_BLOCKED_EGRESS_COUNTRIES = {"GB", "US"}` check already blocks the service if the outbound IP is UK/US. The CLOB client must honour the same guard — verify that once at service start, not per request. The VPN/AWS-Dublin arrangement documented in the main plan context is the operator's responsibility.

### Schema / contract check

Before editing `MarketData`, verify with a short REPL / test:
- `MarketData.bids` is already `list[tuple[Decimal, Decimal]]` — multi-level capable.
- The simulator reads `bids[0]` / `asks[0]` for best-level fills; does it iterate deeper? Check `services/simulator/src/simulator/` to see whether depth is used or ignored. If ignored, **this plan does not change simulator fill logic** — that's a follow-up.

### Tests

1. `test_polymarket_clob_client.py`:
   - Happy path: mocked `httpx` response with 5 bid levels + 5 ask levels → parsed into ordered `[(Decimal, Decimal)]`.
   - Empty book: `{"bids": [], "asks": []}` → returns `([], [])`.
   - Timeout: simulate `httpx.ReadTimeout` → client returns `None` or a sentinel, adapter falls back.
   - Malformed JSON: returns `None`; logs.
2. `test_polymarket_adapter_with_depth.py`:
   - Gamma fixture produces 3 markets with `clobTokenIds`. Mock CLOB client returns real depth for one, empty for one, raises timeout for the third. Assert emitted `MarketData`: first has real depth, second + third have `size=0` fallback, no exceptions propagate out of the adapter loop.
   - Assert the egress guard still trips when `ipinfo.io` reports `GB` — do not regress existing behaviour.
3. Existing adapter tests stay green.

### Plan-discipline note

Per project memory: no code bodies in this plan. File contents are the executor's problem. Short contract snippets (one env var row, one response-shape description, one function signature per new module) are allowed and used above. Full function bodies, full JSON fixtures, full workflow YAML are not.

---

## Hard constraints — must not do

- **Do NOT place orders.** `/book` is read-only. This plan does not touch `order.signals` → `execution.results` paths at all.
- **Do NOT bake secrets.** No L2 keys, no wallet addresses, no API keys in code or tests. Fixtures use hard-coded test `token_id`s that are obviously fake.
- **Do NOT add a second Redis Streams topic for book data.** Emit enriched `MarketData` on the existing `market.data` topic. Downstream consumers already subscribe there.
- **Do NOT change simulator fill logic in this PR.** If the simulator currently ignores book depth past `[0]`, file a follow-up plan. Scope creep here delays paper-trading first fills.
- **Do NOT touch risk manager, strategy runner, Rust execution crates, or research orchestrator.** Ingestion only.
- **Do NOT re-open the Polymarket-legality debate.** Accepted by operator 2026-04-24. Venue-strategy invariants apply.
- **Do NOT modify CLAUDE.md or anything under `~/.claude/`.**

---

## Verification checklist

- [ ] `uv run pytest services/ingestion/tests -v` green — all new + existing
- [ ] `uv run ruff check services/ingestion` clean
- [ ] `uv run mypy services` clean
- [ ] With `POLYMARKET_CLOB_BOOK_ENABLED=false`, adapter behaves identically to `main` (regression check; all existing tests pass)
- [ ] With `POLYMARKET_CLOB_BOOK_ENABLED=true` + a `responses` / `httpx.MockTransport` fixture returning real depth, emitted `MarketData.bids[0]` has `size > 0`
- [ ] Egress guard test still trips on `GB` / `US`
- [ ] PR description includes: (a) link to this plan, (b) one run of the integration test output showing non-zero depth in the emitted message, (c) confirmation that no schema change was needed — or an explicit delta if it was
- [ ] No changes to: `CLAUDE.md`, `~/.claude/`, `risk_manager`, `strategy_runner`, `execution/`, `research_orchestrator`, `simulator`

---

## Post-branch: what the operator / follow-up plan does next

With real depth flowing, the immediately-unblocked workstreams are:

1. **Simulator depth-aware fills.** Separate plan. Currently the simulator fills at `bids[0]` / `asks[0]` — with real size, it can walk the book on large orders and compute slippage honestly.
2. **[[../../wiki/30-Strategies/polymarket-book-imbalance]]** graduates from "cannot be validated today" to "run through `backtest_engine.validate`."
3. **[[../../wiki/30-Strategies/polymarket-yes-mean-revert]]** paper-trade finally produces non-zero `filled_stake` — the validation gauntlet's verdict on it becomes load-bearing instead of a degenerate zero-trades artefact.

These are follow-ups, not part of this plan.
