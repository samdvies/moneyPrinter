# Market Data Archiver Service

**Branch to create:** `market-data-archiver`
**Branch cut from:** `main` at the latest commit (currently `d2c3db0` from 2026-04-25 morning).
**Intended executor:** A cloud agent or the operator's local Claude session. Read CLAUDE.md, this file, the referenced files (`scripts/db/migrations/0005_market_data_archive.sql`, `services/ingestion/src/ingestion/historical_loader.py`, `services/common/src/algobet_common/bus.py`) before touching code.
**Estimated size:** 4-6 hours. One new Python service, one schema migration, one Dockerfile, one compose entry, ~10 tests.

---

## Context

Paper trading is running on the eu-west-1 EC2 (Tailscale `algo-betting-primary`, public IP currently `54.154.131.148`, no Elastic IP attached as of writing). State as of 2026-04-25 morning UK time:

- `ingestion` polls Polymarket Gamma every 1 s and publishes ~1,700 `MarketData` entries/sec to the Redis Stream `market.data`. Confirmed by `XLEN` growth.
- `strategy_runner` opened a paper run (`f689c1bc-...`) for `polymarket-yes-mean-revert`; it's consuming `market.data` but emitting zero `OrderSignal`s — the seed strategy's z-score threshold is rarely tripped on slow-moving Polymarket midpoints, and the simulator's `size=0` sentinels would prevent fills anyway.
- Redis is now capped at `maxmemory 1gb` with `allkeys-lru` (runtime CONFIG SET; not yet persisted in compose — see follow-up #3 in earlier review).
- TimescaleDB hypertable `market_data_archive` exists from migration `0005`, but **nothing writes to it**. Current size: 32 KB. The `historical_loader.py` exists but is a one-shot CLI for Betfair TAR files and a library-only `redis_xrange` mode — not a continuous consumer.

**The gap this plan closes:** there is no durable archive of live Polymarket market data. The Redis stream is the only persistence, and it's volatile (LRU evicts under memory pressure). For offline replay (`backtest_engine.validate` with `data_source='archive'`) and for any hypothesis testing that depends on weeks of real depth-aware ticks, we need a service that drains `market.data` into TimescaleDB continuously.

**Out of scope:** the replay-side `data_source='archive'` mode in `backtest_engine.validate` is a follow-up plan, not this one. This plan only produces the durable archive.

---

## Deliverable 1 — Schema migration

### Location

`scripts/db/migrations/0007_market_data_archive_polymarket.sql`

### Behaviour

The existing `market_data_archive` table has `CHECK (venue IN ('betfair', 'kalshi'))` (see `scripts/db/migrations/0005_market_data_archive.sql:7`). Polymarket isn't allowed. The migration must:

1. Drop the existing CHECK constraint on `venue`.
2. Add a new CHECK constraint that includes `'polymarket'` (and `'betfair'`, `'kalshi'` for parity with `0006_polymarket_venue.sql` which extended the `orders` table the same way).
3. Add a column `stream_id text` to record the Redis Stream message ID for end-to-end idempotency. `NULL` allowed (existing rows from `historical_loader` won't have one).
4. Extend the primary key to `(venue, market_id, observed_at, stream_id)` — or add a separate unique constraint on `stream_id` where non-null. The existing PK `(venue, market_id, observed_at)` cannot stay as-is because Polymarket emits multiple ticks per market per second; same `observed_at` to second precision would collide. Either widen the timestamp precision usage or include `stream_id` in the dedupe key. Decide and document the choice in a comment in the migration.
5. Add a `received_at timestamptz NOT NULL DEFAULT now()` column if not already present (used to measure end-to-end ingestion lag). The existing schema already has `ingested_at` — reuse that name; do not add a duplicate column.

### Verification

- `uv run python -m scripts.migrate` applies cleanly on a fresh DB and on the existing prod DB.
- `psql -c "\d+ market_data_archive"` shows the new constraint and column.
- Inserting a row with `venue='polymarket'` succeeds.

---

## Deliverable 2 — `services/market_data_archiver/`

### Location

```
services/market_data_archiver/
├── pyproject.toml
├── src/
│   └── market_data_archiver/
│       ├── __init__.py
│       ├── __main__.py        # entrypoint
│       ├── consumer.py        # XREADGROUP loop with deferred acks
│       └── writer.py          # batched asyncpg insert
└── tests/
    ├── test_consumer.py
    ├── test_writer.py
    └── test_integration.py    # marked @pytest.mark.integration
```

### Behaviour

**Consumer (`consumer.py`):**

- Connect to Redis via the project's `algobet_common.bus.BusClient` for connection setup, BUT use raw `redis.asyncio` `xreadgroup` calls directly — `BusClient.consume` auto-acks inside its `finally` block (`services/common/src/algobet_common/bus.py:97-98`), which loses messages when a downstream batch insert fails. The archiver needs **deferred acks**: read → buffer → write → ack. Document this divergence in a comment.
- Consumer group name: `market_data_archiver`. Consumer name: `${SERVICE_NAME}-${HOSTNAME}` so multiple replicas can share work later.
- Read with `count` = batch_size_target, `block` = 5 s.
- Yield `(stream_id, MarketData)` tuples to the writer.

**Writer (`writer.py`):**

- Accumulate `(stream_id, MarketData)` tuples in an in-memory buffer.
- Flush when **either** buffer reaches `BATCH_SIZE` **or** `FLUSH_INTERVAL_SECONDS` elapses since first row in current batch.
- Insert via `asyncpg`'s `unnest`-based bulk insert pattern (already used in `historical_loader.py:flush_batch` — read it; mirror the pattern). Single SQL statement per batch.
- `INSERT ... ON CONFLICT (venue, market_id, observed_at, stream_id) DO NOTHING` (or whichever dedupe key the migration settles on).
- After successful commit, ack all stream IDs in the batch via `XACK`.
- On insert failure: do NOT ack. Log + retry the batch with exponential backoff. After 5 retries, log a poison-message warning and ack only the offending message ID (probabilistically determined by re-trying with smaller batches), so one bad row doesn't block the queue forever.

**Lifecycle (`__main__.py`):**

- Read settings from `algobet_common.config.Settings` (extend it with archiver-specific keys; see Configuration below).
- Establish DB pool via `algobet_common.db.Database`.
- Run consumer + writer as cooperating asyncio tasks.
- Graceful shutdown on SIGTERM: drain in-flight buffer to DB before exit. Don't ack until persisted.

### Configuration (extend `algobet_common.config.Settings`)

| Env var | Default | Purpose |
|---|---|---|
| `ARCHIVER_BATCH_SIZE` | `1000` | Rows per insert statement |
| `ARCHIVER_FLUSH_INTERVAL_SECONDS` | `5.0` | Max time before forcing a flush |
| `ARCHIVER_READ_COUNT` | `1000` | XREADGROUP COUNT per call |
| `ARCHIVER_BLOCK_MS` | `5000` | XREADGROUP block timeout |
| `ARCHIVER_INSERT_RETRIES` | `5` | Max retry attempts before poison-message handling |
| `ARCHIVER_DB_POOL_MIN` | `2` | asyncpg pool min |
| `ARCHIVER_DB_POOL_MAX` | `4` | asyncpg pool max |

`SERVICE_NAME` is already part of the project's standard env (e.g. `market-data-archiver`).

### Idempotency contract

- Every Redis Stream entry has a unique `stream_id` (e.g. `1714050842123-0`).
- Inserts use `ON CONFLICT DO NOTHING` keyed on the dedupe column from migration 0007.
- A crashed-mid-batch archiver, on restart, will re-read pending entries from Redis (consumer-group remembers ack state). Re-inserting them is a no-op because of the conflict clause.
- Net result: **at-least-once delivery, exactly-once persistence**. This is the contract `backtest_engine.validate` will rely on for replay reproducibility.

### Backpressure

- If the DB is slow / unreachable: buffer fills → archiver stops reading from Redis → consumer-group lag grows on the Redis side. Redis maxmemory + LRU will evict older entries from `market.data` first; that's an accepted behaviour (data is volatile by definition until persisted).
- A future improvement would be to alert on consumer-group lag > N seconds, but that's out of scope for this plan.

### Tests

1. `test_writer.py`: unit tests for the bulk insert SQL builder against a fixture with 1, 100, 1,000 rows. Use `pytest-postgresql` or a Docker postgres fixture per project convention.
2. `test_consumer.py`: mock `redis.asyncio` client, verify `xreadgroup` arguments, deferred-ack semantics, and that yielded tuples preserve order.
3. `test_integration.py` (`@pytest.mark.integration`): publish 100 `MarketData` entries to a real Redis (compose-managed test fixture per existing project patterns), run the archiver against a real Postgres + the migration applied, verify all 100 rows are present and dedupe works on re-insert.

Match existing project test conventions (`pytest`, async fixtures, `pytest-asyncio` mode) — read `services/strategy_runner/tests/` for pattern.

---

## Deliverable 3 — Container + compose

### Dockerfile

`services/market_data_archiver/Dockerfile` mirroring `services/ingestion/Dockerfile` (uv multi-stage build; substitute `ingestion` → `market-data-archiver` and `ingestion` → `market_data_archiver` for hyphenated/underscored names).

### Compose entry

In `deploy/docker-compose.prod.yml`, add a new service:

- Build context: same as other services
- Dockerfile path: `services/market_data_archiver/Dockerfile`
- `restart: unless-stopped`
- `depends_on: [redis, postgres]` (start order; healthchecks can come later)
- Env: standard `SERVICE_NAME`, `REDIS_HOST`, `POSTGRES_HOST`, `POSTGRES_PASSWORD`, plus the archiver-specific knobs above
- No published ports (internal-only, like all other services)

The compose file should also pin Redis with `--maxmemory 1gb --maxmemory-policy allkeys-lru` while you're in there — that's follow-up #2 from the earlier review and belongs in the same PR since it's a single-file edit.

---

## Hard constraints — must not do

- **Do NOT modify the live `ingestion`, `simulator`, `risk_manager`, or `strategy_runner` services.** This plan only adds a new archiver service alongside them. Their behaviour must be unchanged.
- **Do NOT bypass `algobet_common.config.Settings` or `algobet_common.db.Database`.** Reuse the project's standard config and connection-pool wrappers; do not re-implement them.
- **Do NOT add a second Redis Stream topic.** Read from the existing `market.data` topic. Use a separate consumer group name (`market_data_archiver`) so the archiver's read position is independent of the strategy_runner's.
- **Do NOT publish anything back to Redis.** The archiver is a sink, not a relay.
- **Do NOT touch `CLAUDE.md`, `~/.claude/`, the Rust execution crates, or the research_orchestrator.**
- **Do NOT bake credentials into Dockerfile or code.** All secrets via env (already standard).
- **Do NOT enable order-side flow.** This is read-from-bus, write-to-DB only. No risk-manager interaction.

---

## Verification checklist

- [ ] `uv run pytest services/market_data_archiver/tests -v` green
- [ ] `uv run pytest -m integration services/market_data_archiver/tests` green against a local compose-managed Redis + Postgres
- [ ] `uv run ruff check services/market_data_archiver` clean
- [ ] `uv run mypy services` clean (whole repo, not just the new package — this catches accidental import-cycle issues)
- [ ] `uv run python -m scripts.migrate` applies `0007` cleanly on both fresh and existing DBs
- [ ] `docker compose -f deploy/docker-compose.prod.yml config` validates with the new service entry
- [ ] `docker build` succeeds for `services/market_data_archiver/Dockerfile`
- [ ] On a running stack, `XLEN market.data` minus `XLEN-of-pending-for-archiver-group` should hover near zero — the archiver is keeping up. Document the exact command for measuring lag in the PR description.
- [ ] After 5 minutes of running on a host with live ingestion, `SELECT count(*) FROM market_data_archive WHERE venue='polymarket' AND ingested_at > now() - interval '5 minutes'` returns a number consistent with the publish rate (~500k for 5 min × 1.7k/s, modulo dedupe and chunk batching).
- [ ] Stop the archiver mid-flight (`docker stop`), restart, re-check counts: zero gaps and zero duplicate rows by stream_id.
- [ ] No changes to `CLAUDE.md`, `~/.claude/`, or any service other than the new one and the compose file
- [ ] PR description includes the count-check query result and a 5-minute lag observation

---

## Post-branch — what unblocks once this lands

1. **`backtest_engine.validate` archive mode.** Add `data_source='archive'` that reads `market_data_archive` slices ordered by `observed_at` and feeds the same `mean_reversion.on_tick` (or future strategies) the existing harness uses. Separate plan; small change once the data is there.
2. **Local replay pull.** With durable rows in TimescaleDB, the operator can pull subsets via SSH+pg_dump or CSV `\copy` over Tailscale (commands already documented in the project handover notes — they'll just work once the archive has content).
3. **Hypothesis validation.** The three filed hypotheses ([[../../wiki/30-Strategies/polymarket-book-imbalance]], [[../../wiki/30-Strategies/polymarket-whale-follow]], [[../../wiki/30-Strategies/polymarket-news-lag]]) all want a depth-aware archive. Combined with the still-pending CLOB book-depth ingestion plan (`docs/superpowers/plans/2026-04-24-polymarket-clob-book-depth-ingestion.md`), they become runnable through the gauntlet.

These are follow-ups, not this plan's scope.
