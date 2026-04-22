# Rust execution scaffold (Phase 7a)

This directory contains the Rust execution scaffolding for Phase 7a.

## Crates

- `execution-core`: shared execution types, `Venue` trait, and `MockVenue`.
- `execution-smarkets`: Smarkets client/auth/rate-limit scaffold and endpoint stubs.
- `execution-bin`: Redis Streams consumer/producer binary that dispatches orders through a selected venue.

## Run in mock mode

From the repository root:

```bash
cargo run --manifest-path execution/Cargo.toml -p execution-bin
```

Or from `execution/`:

```bash
VENUE=mock cargo run -p execution-bin
```

Required for local runtime smoke:

- a Redis instance on `redis://127.0.0.1:6379` (or set `REDIS_URL`)

## Switch to Smarkets mode

Once Phase 7b lands endpoint implementations, run with:

```bash
VENUE=smarkets \
SMARKETS_USERNAME=... \
SMARKETS_PASSWORD=... \
SMARKETS_BASE_URL=https://api.smarkets.com/v3 \
cargo run --manifest-path execution/Cargo.toml -p execution-bin
```

## Logs

Set `RUST_LOG` for verbosity, for example:

```bash
RUST_LOG=execution_bin=info cargo run --manifest-path execution/Cargo.toml -p execution-bin
```

## References

- Spec: `docs/superpowers/specs/2026-04-21-phase7a-rust-execution-scaffold.md`
- Plan: `docs/superpowers/plans/2026-04-21-phase7a-rust-execution-scaffold.md`
