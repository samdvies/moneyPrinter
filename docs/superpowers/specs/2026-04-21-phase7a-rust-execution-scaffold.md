# Phase 7a — Rust Execution Scaffold (Smarkets-first)

- **Status:** draft — awaiting user review
- **Date:** 2026-04-21
- **Depends on:** Phase 1 scaffolding (Redis + Postgres + `algobet_common` schemas), venue pivot decision (`wiki/20-Markets/Venue-Strategy.md`)
- **Unblocks:** 7b (real Smarkets endpoint bodies once API access approved), 7c (ForecastEx venue), 7d (Betfair Delayed Tier-2)
- **Does NOT unblock live trading** — the human approval gate and paper-trading validation per CLAUDE.md remain ahead

## 1. Goal

Land the first Rust code in the project: a Cargo workspace that defines venue-agnostic execution primitives, a fully-working in-memory mock venue, and a Smarkets HTTP client skeleton with auth + rate-limiting + endpoint stubs. When Smarkets API approval arrives, completing the integration is a narrow, bounded PR that fills in endpoint bodies behind the already-defined trait.

## 2. Non-goals

- No live order placement to Smarkets. Stubs return `NotImplemented` for all trading endpoints until creds + approval land.
- No Betfair, ForecastEx, or any second venue in 7a. Trait is designed to accept them; implementation comes in later phases.
- No live positions reconciliation against Smarkets (deferred; requires endpoints 7b fills in).
- No changes to the Python services' public contracts. Rust joins the existing Redis Streams bus as another consumer/producer.

## 3. Workspace layout

Lives at the repo root under `execution/` (new top-level directory, peer of `services/`).

```
execution/
  Cargo.toml              # workspace root
  rust-toolchain.toml     # pinned stable toolchain
  .cargo/config.toml      # workspace-wide build settings
  execution-core/
    Cargo.toml
    src/
      lib.rs              # re-exports
      venue.rs            # Venue trait + order/execution types
      mock.rs             # MockVenue impl, behind `mock` feature (default-on for tests)
      error.rs            # thiserror types for library surface
      types.rs            # OrderRequest, OrderState, ExecutionResult, Side, Price, Stake
  execution-smarkets/
    Cargo.toml
    src/
      lib.rs
      client.rs           # HTTP client, auth, session-token lifecycle
      endpoints.rs        # one fn per Smarkets endpoint — all NotImplemented v1
      rate_limit.rs       # governor-backed token bucket
      error.rs            # thiserror types specific to Smarkets responses
      venue_impl.rs       # impl Venue for SmarketsVenue
  execution-bin/
    Cargo.toml
    src/
      main.rs             # tokio runtime, config load, Redis consumer loop
      bus.rs              # fred-based Redis Streams consumer group + producer
      lifecycle.rs        # in-memory order state tracking (HashMap)
      config.rs           # env-driven config: venue selection, creds, limits
      reconcile.rs        # on-startup fetch open orders, rebuild map (stub v1)
```

## 4. Component responsibilities

### 4.1 `execution-core`

Pure, no I/O, no async except trait method signatures. The `Venue` trait:

```rust
#[async_trait::async_trait]
pub trait Venue: Send + Sync {
    async fn place_order(&self, req: OrderRequest) -> Result<ExecutionResult, VenueError>;
    async fn cancel_order(&self, id: OrderId) -> Result<ExecutionResult, VenueError>;
    async fn fetch_open_orders(&self) -> Result<Vec<OrderState>, VenueError>;
    fn venue_name(&self) -> &'static str;
}
```

Types use `rust_decimal::Decimal` for prices/stakes (never `f64`; avoids floating-point P&L drift). `OrderId` is a newtype wrapper over `String` so venue IDs and internal IDs don't get confused.

`MockVenue` is scriptable: construct with a `Vec<MockBehavior>` where each behaviour is `{matches: predicate, responds: response}`. Default behaviour: fill at requested price. Alternate behaviours: partial fill, reject, error, delay — used in tests.

### 4.2 `execution-smarkets`

Structure mirrors the Smarkets HTTP API:
- `SmarketsClient::login(username, password) -> Session` — returns session token + expiry
- `Session` holds the token; auto-refreshes on 401 before retry (once)
- One method per endpoint in `endpoints.rs`, every body is `todo!("7b: implement against live API")` for trading endpoints
- **Exception:** `fetch_markets` (read-only, documented as pre-auth accessible) gets a real implementation in 7a if it works without login; otherwise it joins the stubs. We'll discover this during implementation and decide.

Rate limiter wraps every outbound HTTP call via a `governor::RateLimiter` in the client struct. Config: 5 req/s steady, burst 10. Configurable via env.

`impl Venue for SmarketsVenue` lives in `venue_impl.rs`, delegates to the client methods, translates `SmarketsError` → `VenueError`.

### 4.3 `execution-bin`

Single binary. Startup sequence:
1. Load config from env (`SMARKETS_USERNAME`, `SMARKETS_PASSWORD`, `REDIS_URL`, `VENUE=mock|smarkets`, rate-limit overrides)
2. Construct the selected `Venue` impl (behind `Arc<dyn Venue>`)
3. Connect to Redis; create consumer group `execution` on `order.signals` if absent
4. Run startup reconciliation (`venue.fetch_open_orders()`, populate in-memory lifecycle map). For `MockVenue` this is a no-op; for `SmarketsVenue` pre-7b this returns `NotImplemented` and startup logs a warning — non-fatal.
5. Enter consume loop: pull batch, dispatch each signal to a tokio task, task calls `venue.place_order()`, publishes `execution.results`, ACKs the Redis message. Task failures are logged but don't crash the binary.
6. Shutdown on SIGTERM: stop consume loop, drain in-flight tasks with a 30s deadline, then exit.

Lifecycle map: `Arc<DashMap<OrderId, OrderState>>`. Every transition publishes to `execution.results` as a separate event (the event log is canonical; the map is a cache). Memory is bounded by `MAX_TRACKED_ORDERS` (default 10k); when exceeded, oldest-terminal entries are evicted first.

## 5. Redis Streams contract

**Consumes:** `order.signals` — messages matching `algobet_common.schemas.OrderSignal` serialised as JSON. Consumer group `execution`, consumer name from env `EXECUTION_CONSUMER_NAME` (default `execution-${VENUE}-1`).

**Produces:** `execution.results` — messages matching `algobet_common.schemas.ExecutionResult`. Published via `XADD` with auto-generated IDs.

Message ACK policy: a signal is ACKed only after the corresponding execution result is successfully `XADD`-ed. Guarantees at-least-once delivery with a crash-recovery window; the risk manager already treats duplicate results as idempotent (keyed on `order_id`).

Serialisation: `serde_json` both directions. Schema drift protection — Rust parses loosely (ignore unknown fields) but serialises strictly per the common schema. A `schema_version` field in every message; Rust rejects messages with an unknown major version and logs loudly.

## 6. Config (env-driven)

- `RUST_LOG` — standard env logger spec (default `execution=info,warn`)
- `REDIS_URL` — shared with Python services
- `VENUE` — `mock` | `smarkets` (default `mock`)
- `SMARKETS_USERNAME`, `SMARKETS_PASSWORD` — required when `VENUE=smarkets`
- `SMARKETS_BASE_URL` — default `https://api.smarkets.com/v3`
- `SMARKETS_RATE_LIMIT_RPS` — default 5
- `SMARKETS_RATE_LIMIT_BURST` — default 10
- `EXECUTION_CONSUMER_NAME` — default `execution-${VENUE}-1`
- `MAX_TRACKED_ORDERS` — default 10000
- `SHUTDOWN_DRAIN_SECONDS` — default 30

Loaded via `envconfig` or hand-rolled (prefer hand-rolled — small surface, no dep needed).

## 7. Error model

- `execution-core::VenueError` — thiserror enum with variants: `Auth`, `RateLimited`, `NetworkTimeout`, `MalformedResponse`, `Rejected(reason)`, `NotImplemented`, `Other(String)`. Exhaustive; downstream code pattern-matches.
- `execution-smarkets::SmarketsError` — thiserror with Smarkets-specific variants, maps to `VenueError` via `From` impl at the venue-impl boundary.
- `execution-bin::main` uses `anyhow::Result` for convenient `?`-bubbling. Bin-level errors are fatal; library errors are recoverable.

Retry policy (at venue-impl layer, not bin):
- `RateLimited` → sleep for the `Retry-After` header value or 1s, retry once
- `NetworkTimeout` → exponential backoff, up to 3 attempts
- `Auth` → one re-login attempt, then bubble
- `Rejected`/`NotImplemented`/`MalformedResponse` → no retry, immediate fail

## 8. Testing strategy

### Unit (fast, run in CI on every PR)
- `execution-core`: `MockVenue` behaviour matrix — fill, partial fill, reject, error, delay
- `execution-smarkets`: HTTP client tested against `wiremock` fixtures — login happy path, 401 retry, rate-limit 429 handling, malformed JSON handling, session expiry + refresh
- `execution-bin`: lifecycle map state transitions; config parsing

### Integration (run in CI, requires Docker)
- Spin up the existing test Redis via docker-compose
- `execution-bin` built with `VENUE=mock` runs against it
- Python-side test publishes `OrderSignal` messages, reads `execution.results`, asserts payloads match
- Reuses the existing end-to-end smoke-test harness; Rust binary is invoked as a subprocess

### Live-smarkets (gated, NOT in CI)
- `#[cfg(feature = "live-smarkets")]` tests that hit real Smarkets endpoints
- Require `SMARKETS_USERNAME`/`SMARKETS_PASSWORD` in env
- Run manually during 7b implementation to verify each endpoint as it's filled in

## 9. CI additions

New `rust` job in `.github/workflows/ci.yml` parallel to existing `python` job:
- `cargo fmt --all -- --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`
- Cargo cache keyed on `execution/Cargo.lock` + `execution/rust-toolchain.toml`

Toolchain: `rust-toolchain.toml` pins stable (exact version set at implementation time to whatever is current; renovate-style bumps later).

## 10. Build & deploy

- Dockerfile: new stage `execution-build` using `rust:1-bookworm`, produces `/out/execution-bin` static-linked via `--target x86_64-unknown-linux-musl`. Copy into the runtime image.
- docker-compose: new service `execution` depending on `redis`. Default env sets `VENUE=mock` so it works without any creds.
- Binary is small (<20MB) and starts in <500ms — fine for dev iteration.

## 11. Dependencies (target Cargo.toml shape)

Kept conservative; every dep justified:

- `tokio` (runtime) — async
- `async-trait` — trait async methods
- `serde`, `serde_json` — bus serialisation
- `rust_decimal` — price/stake math
- `thiserror` — library errors
- `anyhow` — binary errors
- `fred` — tokio-native Redis with Stream consumer-group support
- `reqwest` with `rustls-tls` — HTTP client (no OpenSSL pain)
- `governor` — rate limiter
- `dashmap` — concurrent lifecycle map
- `tracing`, `tracing-subscriber` — structured logs
- **dev-deps:** `wiremock`, `tokio-test`

No `diesel`/`sqlx`: Rust doesn't touch Postgres in 7a (Python writes the audit trail).

## 12. Rollout

1. Land `execution-core` alone — trait, types, `MockVenue`, unit tests. Ships in its own PR. **Nothing breaks** because nothing depends on it yet.
2. Land `execution-smarkets` with all stubs — unit-tested against wiremock fixtures. Still unused by anything.
3. Land `execution-bin` + Docker integration — mock-venue integration test green. This is the first PR that adds a service to docker-compose.
4. **Stop here for 7a.** 7b picks up when Smarkets API credentials arrive.

Every PR ends with a green CI — Python jobs continue to pass untouched; new Rust job is green. No flag-day.

## 13. Interaction with existing code

- **No Python code changes required** in 7a. The existing `OrderSignal` / `ExecutionResult` Pydantic schemas are the source of truth; Rust mirrors them.
- Schema sync: a `scripts/check_schema_parity.py` test compares the Rust `serde` structs (via a small `cargo run --bin emit-schema` helper) with Python schemas, asserts shape equivalence. Keeps them from silently drifting.
- Simulator: unchanged. Paper trading still runs Python-side against `MockVenue` or a pure-Python sim; Rust is only in the loop when `VENUE=smarkets` (or a future real venue) is selected.

## 14. Failure modes and mitigations

| Failure | Detection | Mitigation |
|---|---|---|
| Redis unavailable at startup | connection error | exponential backoff retry, log loudly, don't crash |
| Schema mismatch on consumed signal | `serde_json` parse fail | dead-letter to `order.signals.deadletter` stream, don't block the consumer |
| Venue returns unexpected JSON | `MalformedResponse` | log full response body, emit `ExecutionResult` with `errored` status, don't retry |
| Smarkets rate-limit hit | 429 or internal limiter | internal limiter prevents most; 429 triggers backoff-and-retry-once |
| Session token expires mid-call | 401 | re-login, retry once, then fail |
| Binary crashes mid-order | process exit | Redis message remains un-ACKed; on restart, consumer group re-delivers; lifecycle map rebuilt from reconciliation call |
| Lifecycle map unbounded growth | memory pressure | `MAX_TRACKED_ORDERS` eviction policy; metric published for monitoring |

## 15. Open decisions (for 7b, not blocking 7a)

- Which Smarkets endpoints are free to hit without auth? Discover during 7a implementation (read-only `fetch_markets` is the candidate); record findings in the 7b plan.
- Does Smarkets impose a stricter real rate limit than our 5 rps guess? Measure during first live calls in 7b, tighten the default.
- Reconciliation granularity — full `fetch_open_orders` on every restart, or incremental via a persisted cursor? Defer to 7b; v1 is full-sweep.
- Metrics emission — Prometheus, OpenTelemetry, or just structured logs? Currently structured logs via `tracing`. Revisit when dashboards come online.

## 16. Out of scope (explicitly not in 7a)

- Real Smarkets order placement (7b)
- Betfair Delayed venue (7d)
- ForecastEx venue (7c)
- Streaming market-data ingestion via Rust (stays Python; execution crate only handles order flow)
- Co-location, kernel-bypass networking, or anything resembling HFT hardening
- On-disk order store (Postgres audit trail is Python's job)
