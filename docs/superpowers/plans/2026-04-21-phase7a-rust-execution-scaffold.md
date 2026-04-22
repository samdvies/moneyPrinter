# Plan: Phase 7a — Rust Execution Scaffold (Smarkets-first)

> **Spec:** `docs/superpowers/specs/2026-04-21-phase7a-rust-execution-scaffold.md`
> **Venue pivot:** `wiki/20-Markets/Venue-Strategy.md` (Smarkets Tier 1, not Betfair)
> **Branch:** `phase7a-rust-execution` (new, off `main`)
> **Non-blocking:** 7a ships the scaffold; 7b fills Smarkets endpoint bodies when API creds arrive

## Why now

The project is Python-heavy and currently has no execution layer — all order placement flows through the simulator. CLAUDE.md mandates Rust for the execution hot path and a sim↔live-identical API. 7a lands the first Rust code, the workspace skeleton, the `Venue` trait, a fully-working `MockVenue`, and a Smarkets HTTP client with every endpoint stubbed behind the trait. When Smarkets API approval arrives, 7b is a narrow PR filling in endpoint bodies — no trait changes, no consumer changes.

The scaffold also unblocks the ordering dependency for every future venue (Betfair Delayed, ForecastEx) without paying the cost of a Rust rewrite later.

## Ordering invariant

Tasks land bottom-up: core types first, no venue; mock venue second (exercises the trait); Smarkets client third (stubbed, unit-tested); binary + Redis wiring last (integration test green); Docker + CI final. Each task produces a shippable PR with green CI.

## File structure

All new files under a new top-level directory `execution/` (peer of `services/`).

```
execution/
  Cargo.toml                         # workspace root
  rust-toolchain.toml
  .cargo/config.toml                 # workspace build flags
  execution-core/
    Cargo.toml
    src/
      lib.rs
      venue.rs                       # Venue trait
      types.rs                       # OrderRequest, OrderState, ExecutionResult, Side, Price, Stake
      error.rs                       # VenueError (thiserror)
      mock.rs                        # MockVenue, behind `mock` feature (default-on)
    tests/
      mock_behaviour.rs
  execution-smarkets/
    Cargo.toml
    src/
      lib.rs
      client.rs                      # SmarketsClient, session lifecycle
      endpoints.rs                   # one fn per endpoint, bodies todo!() except fetch_markets
      rate_limit.rs                  # governor wrapper
      error.rs                       # SmarketsError (thiserror)
      venue_impl.rs                  # impl Venue for SmarketsVenue
    tests/
      client_auth.rs                 # wiremock-backed
      rate_limit.rs
  execution-bin/
    Cargo.toml
    src/
      main.rs                        # tokio runtime entry
      config.rs                      # env parsing
      bus.rs                         # fred Redis consumer/producer
      lifecycle.rs                   # DashMap + transition publisher
      reconcile.rs                   # startup open-orders fetch
    tests/
      integration_redis.rs           # docker-compose-backed
```

Also new/modified outside `execution/`:

- Modify: `docker-compose.yml` — add `execution` service (default `VENUE=mock`)
- Modify: `Dockerfile` — new `rust-build` stage producing the binary
- Modify: `.github/workflows/ci.yml` — new `rust` job parallel to existing Python jobs
- Create: `scripts/check_schema_parity.py` — guards Python↔Rust serde shape drift
- Modify: `.env.example` — add `SMARKETS_*` + `VENUE` + `EXECUTION_*` block
- Modify: `.gitignore` — add `execution/target/`

No Python code is modified. Python schemas (`algobet_common.schemas`) are the source of truth; Rust mirrors them.

---

## Task 1: Workspace skeleton + CI wiring

**Files:**
- Create: `execution/Cargo.toml`
- Create: `execution/rust-toolchain.toml`
- Create: `execution/.cargo/config.toml`
- Create: `execution/execution-core/Cargo.toml` (empty lib)
- Create: `execution/execution-core/src/lib.rs` (empty)
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore`

### Responsibilities

Land the minimal Cargo workspace that builds clean and has CI running `fmt`, `clippy`, `test` on every PR. No domain code yet.

### Steps

- [ ] Create the Cargo workspace `execution/Cargo.toml` with members `["execution-core"]` (additional members added in later tasks)
- [ ] Pin toolchain in `rust-toolchain.toml` — use latest stable at impl time (record version here when written)
- [ ] Add `execution/target/` to `.gitignore`
- [ ] Add a `rust` job to `.github/workflows/ci.yml` running: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace`. Use `Swatinem/rust-cache` for cache keyed on `execution/Cargo.lock` + `execution/rust-toolchain.toml`. Set `working-directory: execution`.
- [ ] Verify locally: `cd execution && cargo build` succeeds (empty crate compiles)
- [ ] Verify CI: push to a throwaway branch, confirm `rust` job green alongside `python` jobs
- [ ] Commit: `feat(execution): rust workspace scaffold + ci integration`

### Verification

- `cargo build --workspace` green
- `cargo fmt --check` green (nothing to format yet)
- `cargo clippy -- -D warnings` green
- CI shows the new `rust` job passing

---

## Task 2: Core types + `Venue` trait

**Files:**
- Create: `execution/execution-core/src/types.rs`
- Create: `execution/execution-core/src/error.rs`
- Create: `execution/execution-core/src/venue.rs`
- Modify: `execution/execution-core/src/lib.rs` (re-exports)
- Modify: `execution/execution-core/Cargo.toml` (deps: `serde`, `serde_json`, `rust_decimal`, `thiserror`, `async-trait`)

### Responsibilities

Define the types every venue must produce/consume and the trait every venue must implement. No venue impls in this task.

Contract signatures (full bodies not embedded per CLAUDE.md convention):

```rust
pub enum Side { Back, Lay }

pub struct OrderRequest {
    pub client_order_id: OrderId,
    pub market_id: String,
    pub selection_id: String,
    pub side: Side,
    pub price: Decimal,
    pub stake: Decimal,
    pub schema_version: u32,
}

pub enum OrderState { Submitted, Accepted, PartiallyFilled, Filled, Cancelled, Rejected }

pub struct ExecutionResult {
    pub client_order_id: OrderId,
    pub venue_order_id: Option<String>,
    pub state: OrderState,
    pub filled_stake: Decimal,
    pub avg_fill_price: Option<Decimal>,
    pub ts_utc: DateTime<Utc>,
    pub schema_version: u32,
}

#[async_trait]
pub trait Venue: Send + Sync {
    async fn place_order(&self, req: OrderRequest) -> Result<ExecutionResult, VenueError>;
    async fn cancel_order(&self, id: OrderId) -> Result<ExecutionResult, VenueError>;
    async fn fetch_open_orders(&self) -> Result<Vec<OrderState>, VenueError>;
    fn venue_name(&self) -> &'static str;
}
```

`VenueError` is the `thiserror` enum from spec §7.

### Steps

- [ ] Add required deps to `execution-core/Cargo.toml` at pinned versions (record exact versions at impl time)
- [ ] Define `types.rs` — the structs and enums above, all deriving `Debug, Clone, Serialize, Deserialize, PartialEq`
- [ ] Define `error.rs` — `VenueError` thiserror enum with variants from spec §7
- [ ] Define `venue.rs` — the `Venue` trait signature
- [ ] Re-export from `lib.rs` so consumers only need `execution_core::*`
- [ ] Write a serde round-trip test: `OrderRequest` → JSON → `OrderRequest` preserves all fields; `ExecutionResult` same
- [ ] Write a schema-version test: a JSON blob with `schema_version: 999` fails to deserialize (strict major-version gating)
- [ ] Verify: `cargo test -p execution-core`
- [ ] Commit: `feat(execution-core): venue trait + order/execution types`

### Verification

- All types compile with no warnings
- Serde round-trip tests green
- Types match the Python `algobet_common.schemas` field names exactly (verified by next task's parity script)

---

## Task 3: Python↔Rust schema parity script

**Files:**
- Create: `scripts/check_schema_parity.py`
- Create: `execution/execution-core/src/bin/emit_schema.rs` (tiny helper binary)
- Modify: `.github/workflows/ci.yml` — run parity check in the `rust` job after `cargo build`

### Responsibilities

Prevent silent Python↔Rust schema drift. The Rust binary dumps its serde schemas as JSON; the Python script loads both sides and asserts field-name + type equivalence for `OrderRequest`, `OrderState`, `ExecutionResult`.

### Steps

- [ ] Add `schemars` dep to `execution-core` (or use `serde_json::to_value` on a constructed instance — pick the lighter-weight approach; prefer constructed-instance method to avoid a new dep if possible)
- [ ] Implement the `emit_schema` binary that prints one line of JSON per exported type
- [ ] Write `check_schema_parity.py` using the existing `algobet_common.schemas` module; diff field names + optionality
- [ ] TDD: a deliberately-broken change (rename one Rust field) makes the script exit non-zero
- [ ] Wire into CI — run after `cargo build` in the `rust` job
- [ ] Commit: `feat(ci): enforce python<->rust schema parity on every build`

### Verification

- Script exits 0 on matching schemas, non-zero with a clear diff on mismatch
- CI runs the parity check and fails on introduced drift

---

## Task 4: `MockVenue` implementation

**Files:**
- Create: `execution/execution-core/src/mock.rs`
- Create: `execution/execution-core/tests/mock_behaviour.rs`
- Modify: `execution/execution-core/Cargo.toml` — add `mock` feature, default-on

### Responsibilities

Scriptable mock venue for testing. Construct with `Vec<MockBehavior>`; each behaviour is `{predicate: Fn(&OrderRequest) -> bool, response: MockResponse}`. Default (no behaviours) fills every order at requested price immediately.

### Steps

- [ ] Define `MockBehavior` and `MockResponse` in `mock.rs` (response variants: `Fill`, `PartialFill`, `Reject(reason)`, `Error(VenueError)`, `Delay(Duration).then(Response)`)
- [ ] Implement `impl Venue for MockVenue`
- [ ] TDD: default MockVenue fills any order at requested price → `ExecutionResult{ state: Filled, avg_fill_price: req.price }`
- [ ] TDD: scripted reject behaviour → `ExecutionResult{ state: Rejected }` with carried reason
- [ ] TDD: partial fill → `filled_stake < req.stake`, state `PartiallyFilled`
- [ ] TDD: error behaviour → `Err(VenueError::...)` bubbles correctly
- [ ] TDD: delay behaviour respects the configured duration (use `tokio::time::pause`)
- [ ] TDD: `cancel_order` on a filled order returns `VenueError::Other("already terminal")`; on a pending order returns `Cancelled` state
- [ ] TDD: `fetch_open_orders` returns whatever the mock currently tracks
- [ ] Verify: `cargo test -p execution-core --features mock`
- [ ] Commit: `feat(execution-core): scriptable MockVenue with behaviour matrix`

### Verification

- All behaviour tests green
- `MockVenue` remains usable as a standalone testing tool for other crates (integration tests in later tasks consume it directly)

---

## Task 5: Smarkets crate skeleton + rate limiter

**Files:**
- Create: `execution/execution-smarkets/Cargo.toml`
- Create: `execution/execution-smarkets/src/lib.rs`
- Create: `execution/execution-smarkets/src/rate_limit.rs`
- Create: `execution/execution-smarkets/src/error.rs`
- Create: `execution/execution-smarkets/tests/rate_limit.rs`
- Modify: `execution/Cargo.toml` — add `execution-smarkets` to workspace members

### Responsibilities

Land the crate and the rate limiter, which is the only piece we can fully implement without hitting Smarkets. Everything else is scaffolded in Task 6.

### Steps

- [ ] Create `execution-smarkets/Cargo.toml` with deps: `execution-core`, `tokio`, `reqwest` (with `rustls-tls`), `governor`, `thiserror`, `serde`, `serde_json`, `async-trait`
- [ ] Implement `rate_limit.rs` — thin wrapper over `governor::RateLimiter` with `new(rps: u32, burst: u32)` and `async fn acquire(&self)`
- [ ] Define `SmarketsError` in `error.rs` with Smarkets-specific variants (`LoginFailed`, `SessionExpired`, `RateLimited`, `HttpStatus(u16)`, `Deserialization`, `EndpointNotImplemented`); `From<SmarketsError> for VenueError` impl
- [ ] TDD: rate limiter allows `burst` immediate acquires, then rate-limits subsequent calls per `rps`
- [ ] TDD: `SmarketsError → VenueError` mapping is exhaustive
- [ ] Verify: `cargo test -p execution-smarkets`
- [ ] Commit: `feat(execution-smarkets): crate skeleton + rate limiter`

### Verification

- Rate limiter tests green (use `tokio::time::pause` for determinism)
- Error mapping covered

---

## Task 6: Smarkets HTTP client (auth + endpoint stubs + `impl Venue`)

**Files:**
- Create: `execution/execution-smarkets/src/client.rs`
- Create: `execution/execution-smarkets/src/endpoints.rs`
- Create: `execution/execution-smarkets/src/venue_impl.rs`
- Create: `execution/execution-smarkets/tests/client_auth.rs`
- Modify: `execution/execution-smarkets/Cargo.toml` — add `wiremock` to dev-deps

### Responsibilities

`SmarketsClient::login(user, pass)` returns a `Session` struct with token + expiry. Subsequent calls include `session-token` header. On 401 during a call, re-login once and retry.

`endpoints.rs` has one function per Smarkets endpoint we intend to use. All trading endpoints (`place_order`, `cancel_order`, `fetch_open_orders`) have bodies `Err(SmarketsError::EndpointNotImplemented)`. `fetch_markets` — attempt real implementation only if discovered to be auth-free during impl; otherwise also stub.

`venue_impl.rs` — `impl Venue for SmarketsVenue` delegates to the endpoint functions, translates errors at the boundary.

### Steps

- [ ] Implement `Session` + `SmarketsClient` in `client.rs`: login flow, stored token, expiry tracking, auto-refresh on 401
- [ ] Implement `endpoints.rs` with function signatures matching each planned endpoint. All trading endpoints return `Err(EndpointNotImplemented)`. `fetch_markets` is an attempted implementation.
- [ ] Implement `impl Venue for SmarketsVenue` — every method calls through to the endpoint and maps errors
- [ ] TDD (wiremock): login happy path → returns `Session` with token
- [ ] TDD (wiremock): login failure (401) → `SmarketsError::LoginFailed`
- [ ] TDD (wiremock): session-token header sent on subsequent call
- [ ] TDD (wiremock): 401 mid-call → triggers re-login + retry, second call succeeds
- [ ] TDD (wiremock): 429 response → `SmarketsError::RateLimited` (internal limiter is advisory; real 429s still handled)
- [ ] TDD: malformed JSON response → `SmarketsError::Deserialization`
- [ ] TDD: `place_order` called → `VenueError::NotImplemented` (translated from `EndpointNotImplemented`)
- [ ] TDD: `fetch_markets` — if implemented against real or recorded fixture, assert expected shape; otherwise same `NotImplemented` path
- [ ] Verify: `cargo test -p execution-smarkets`
- [ ] Commit: `feat(execution-smarkets): http client + auth + endpoint stubs`

### Verification

- All wiremock tests green
- `SmarketsVenue` satisfies the `Venue` trait (confirmed by compile-time check — `static_assertions::assert_impl_all!`)
- Trading endpoints cleanly return `NotImplemented` ready for 7b to replace

---

## Task 7: `execution-bin` — Redis consumer + lifecycle tracking

**Files:**
- Create: `execution/execution-bin/Cargo.toml`
- Create: `execution/execution-bin/src/main.rs`
- Create: `execution/execution-bin/src/config.rs`
- Create: `execution/execution-bin/src/bus.rs`
- Create: `execution/execution-bin/src/lifecycle.rs`
- Create: `execution/execution-bin/src/reconcile.rs`
- Modify: `execution/Cargo.toml` — add `execution-bin` to workspace members

### Responsibilities

Binary wires everything together: consume `order.signals` from Redis, dispatch to the configured venue, track lifecycle, publish `execution.results`.

### Steps

- [ ] Create `execution-bin/Cargo.toml` with deps: both `execution-core` + `execution-smarkets`, `tokio` (`rt-multi-thread`, `macros`), `fred`, `anyhow`, `serde_json`, `tracing`, `tracing-subscriber`, `dashmap`
- [ ] Implement `config.rs` — parse env vars from spec §6 (venue selection, Redis URL, Smarkets creds, rate limits, consumer name, limits). Hand-rolled parsing, no extra dep.
- [ ] Implement `bus.rs` — `fred` client, consumer group creation, batched `XREADGROUP` loop, `XADD` for results, `XACK` only after successful publish
- [ ] Implement `lifecycle.rs` — `Arc<DashMap<OrderId, OrderState>>` + `fn transition(id, new_state)` that both updates the map and publishes to the bus
- [ ] Implement `reconcile.rs` — on startup, call `venue.fetch_open_orders()`; if `NotImplemented`, log warning and continue (pre-7b Smarkets does this)
- [ ] Implement `main.rs` — startup sequence per spec §4.3; graceful shutdown on SIGTERM with 30s drain
- [ ] TDD: config parsing — happy path + missing-required-field (returns error with clear message)
- [ ] TDD: lifecycle transition map updates + publishes event
- [ ] TDD: schema-version drift — consumed signal with unknown major version is dead-lettered, not crashed-on
- [ ] Verify: `cargo test -p execution-bin`
- [ ] Verify: `VENUE=mock cargo run -p execution-bin` — starts, connects to local Redis (from docker-compose), waits for messages, exits cleanly on SIGTERM
- [ ] Commit: `feat(execution-bin): redis consumer + lifecycle tracking + reconciliation`

### Verification

- Unit tests green
- Manual smoke: binary starts, consumes a test message published via `redis-cli`, publishes a result, ACKs cleanly

---

## Task 8: End-to-end integration test

**Files:**
- Create: `execution/execution-bin/tests/integration_redis.rs`
- Modify: existing `docker-compose.yml` — add `execution` service (default `VENUE=mock`)

### Responsibilities

Spin up real Redis (shared with Python test infrastructure), publish scripted `OrderSignal` messages, start the binary, assert `ExecutionResult` messages match expected shape and timing.

### Steps

- [ ] Add the `execution` service to `docker-compose.yml` with `depends_on: [redis]` and default env `VENUE=mock`
- [ ] Write `integration_redis.rs` — connects to the same Redis as docker-compose dev env, publishes 3 scripted orders, starts the binary in a tokio task, polls for 3 execution results, asserts
- [ ] TDD: happy path — 3 published → 3 results with `state: Filled`
- [ ] TDD: schema-mismatch message → dead-lettered, not consumed
- [ ] TDD: crash recovery — simulate binary kill mid-processing, restart, verify un-ACKed message re-delivered
- [ ] Mark the integration test `#[ignore]`-by-default; run in CI under a `docker-compose` service step
- [ ] Verify: `cargo test -p execution-bin --test integration_redis -- --ignored` local run green
- [ ] Verify: CI integration-test job green
- [ ] Commit: `test(execution): end-to-end redis integration test`

### Verification

- All three scenarios green locally and in CI
- Docker-compose `execution` service starts without Smarkets creds (mock mode default)

---

## Task 9: Dockerfile + final CI wiring

**Files:**
- Modify: `Dockerfile` — new `rust-build` stage
- Modify: `.github/workflows/ci.yml` — ensure integration test runs with docker-compose

### Responsibilities

Ship a container image that includes the Rust binary. Keep image size tight via musl static-linking.

### Steps

- [ ] Add a `rust-build` stage to `Dockerfile` using `rust:1-bookworm` (pin exact minor at impl); target `x86_64-unknown-linux-musl` for static output
- [ ] Copy the built binary into the runtime stage
- [ ] Verify: `docker build .` succeeds and produces an image with `/usr/local/bin/execution-bin` present
- [ ] Verify: `docker compose up execution` starts the service in mock mode without Smarkets creds
- [ ] Verify: binary size under 30MB (stripped)
- [ ] Commit: `feat(docker): ship execution-bin rust binary`

### Verification

- Docker build green locally
- Docker-compose stack comes up clean
- Binary cold-starts in <1 second

---

## Task 10: Env + docs polish

**Files:**
- Modify: `.env.example`
- Create: `execution/README.md`

### Steps

- [ ] Add `SMARKETS_USERNAME`, `SMARKETS_PASSWORD`, `SMARKETS_BASE_URL`, `SMARKETS_RATE_LIMIT_RPS`, `SMARKETS_RATE_LIMIT_BURST`, `VENUE`, `EXECUTION_CONSUMER_NAME`, `MAX_TRACKED_ORDERS`, `SHUTDOWN_DRAIN_SECONDS` to `.env.example` with comments
- [ ] Write `execution/README.md` — one page: what the crate does, how to run in mock mode, how to switch to Smarkets mode once 7b lands, where to find logs, link to spec + plan
- [ ] Commit: `docs(execution): env template + readme`

### Verification

- `.env.example` diff readable; no secrets leaked
- README is accurate and scannable

---

## Branch + PR strategy

- Branch `phase7a-rust-execution` off `main`
- One PR per task works, or bundle: 1+2 (skeleton + core), 3 (parity), 4 (mock), 5+6 (Smarkets crate), 7+8 (bin + integration), 9+10 (docker + docs) → 6 PRs
- Each PR: green `cargo test --workspace`, green existing Python tests, green parity check
- Merge to `main` after task 10

## Explicit out-of-scope (7b territory)

- Real Smarkets order placement
- Live-session integration tests
- Position reconciliation against Smarkets
- Metrics/Prometheus emission
- On-disk order store in Rust (Python owns the Postgres audit trail)

## Spec coverage self-review

| Spec section | Task(s) |
|---|---|
| §3 workspace layout | 1, 2, 5, 7 |
| §4.1 execution-core | 2, 4 |
| §4.2 execution-smarkets | 5, 6 |
| §4.3 execution-bin | 7, 8 |
| §5 Redis contract | 7, 8 |
| §6 config | 7, 10 |
| §7 error model | 2, 5, 6 |
| §8 testing strategy | 2, 4, 6, 7, 8 |
| §9 CI | 1, 3, 8 |
| §10 build & deploy | 9 |
| §11 dependencies | 2, 5, 7 |
| §12 rollout | task ordering |
| §13 Python interaction | 3 (parity script), 7 (bus) |
| §14 failure modes | 6, 7, 8 test matrices |

No placeholders. No unresolved TBDs. Task ordering maintains the "always-shippable" invariant.
