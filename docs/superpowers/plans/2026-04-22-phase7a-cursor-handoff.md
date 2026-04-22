# Phase 7a — Cursor Cloud Agent Handoff

**Date:** 2026-04-22
**From:** Claude Code (local, low-context)
**To:** Cursor Cloud Agent
**Branch:** `phase7a-rust-execution` (already checked out, **not yet pushed**)
**Base branch:** `phase6c-grok-hypothesis` (10 commits ahead of `main`; both branches unpushed)

## Your job

Finish Phase 7a (Rust execution scaffold), commit every task, and push both
branches to `origin`. The plan is already written — you execute it.

## Required reading before you start

1. `CLAUDE.md` (repo root) — **read ground rules**. UK venues only. Smarkets T1,
   not Betfair. No live capital without approval. Commit discipline says
   "only commit when asked" — **the user has pre-authorised commits for this
   handoff**, one per task, as described below.
2. `docs/superpowers/specs/2026-04-21-phase7a-rust-execution-scaffold.md` —
   authoritative spec.
3. `docs/superpowers/plans/2026-04-21-phase7a-rust-execution-scaffold.md` —
   the 10-task plan. Every task has explicit file paths, steps, and
   verification commands. **Do not deviate from task ordering.**
4. `docs/superpowers/plans/2026-04-21-handoff-status.md` — prior handoff doc
   (earlier session) for broader context.
5. `wiki/20-Markets/Venue-Strategy.md` — why Smarkets, not Betfair.

## Current state on disk

### Branch graph

```
main
  └── phase6c-grok-hypothesis (10 commits — Phase 6c complete except Task 10)
        └── phase7a-rust-execution (current HEAD — Phase 7a Task 1 partially scaffolded)
```

Neither feature branch has been pushed. You push both at the end.

### Phase 6c state (already complete, do not touch)

All Phase 6c code shipped, tests green. Commits on `phase6c-grok-hypothesis`:

- `ea85e27` AST whitelist validator
- `4697007` AST validator review fixes
- `b573147` sandbox runner
- `94671c3` spend tracker
- `2a2d177` LLM client + mock backend
- `d860c18` context builder
- `02d2e51` hypothesize() end-to-end
- `e41c017` CLI + dry-run
- `9a920b5` wiki + daily-log write-back
- `d5c7b58` cron docs
- `4c82341` markdown-fence strip fix

Phase 6c Task 10 (first live full cycle) is deferred — it needs docker compose
up and real historical tick data. Not your problem.

### Phase 7a state (what you inherit)

`phase7a-rust-execution` was branched off `phase6c-grok-hypothesis`. Rust
toolchain 1.95.0 MSVC is installed (`rustup show` confirms). Cargo is on
`$HOME/.cargo/bin/cargo` — add to PATH if not auto-discovered.

**Uncommitted changes on this branch (Task 1, partially complete):**

- `execution/Cargo.toml` — workspace root (written)
- `execution/rust-toolchain.toml` — toolchain pin 1.95.0 (written)
- `execution/.cargo/config.toml` — build config (written)
- `execution/execution-core/Cargo.toml` — empty core crate (written)
- `execution/execution-core/src/lib.rs` — empty core lib with crate docstring (written)
- `.gitignore` — `execution/target/` appended (staged implicitly via working tree)

**Also present as unstaged from prior sessions** — these are Phase 6c artefacts
that should already be committed on `phase6c-grok-hypothesis` but apparently
aren't. Investigate before your first commit:

```
 M .env.example
 M CLAUDE.md
 M docs/devils-advocate/2026-04-19-phase4-postimpl.md
 M docs/devils-advocate/2026-04-19-phase4-preimpl.md
 M docs/superpowers/specs/2026-04-18-algo-betting-design.md
?? docs/devils-advocate/2026-04-19-phase5a-preimpl.md
?? docs/devils-advocate/2026-04-20-phase5b-preimpl.md
?? docs/superpowers/plans/2026-04-19-phase5a-cumulative-exposure.md
?? docs/superpowers/plans/2026-04-20-phase5b-dashboard-auth.md
?? docs/superpowers/plans/2026-04-20-phase6-7-roadmap.md
?? docs/superpowers/plans/2026-04-21-handoff-status.md
?? docs/superpowers/plans/2026-04-21-phase6c-grok-hypothesis-generation.md
?? docs/superpowers/plans/2026-04-21-phase7a-rust-execution-scaffold.md
?? docs/superpowers/specs/2026-04-21-phase6c-grok-hypothesis-generation.md
?? docs/superpowers/specs/2026-04-21-phase7a-rust-execution-scaffold.md
?? wiki/20-Markets/Polymarket-Feasibility-2026.md
?? wiki/20-Markets/Venue-Strategy.md
?? wiki/70-Daily/2026-04-21.md
?? wiki/70-Daily/2026-04-22.md
?? wiki/Untitled.md
?? .claude/scheduled_tasks.lock
```

**First action: commit all these docs/specs/wiki/daily-log files on the
`phase6c-grok-hypothesis` branch** (not on your current 7a branch — they
belong to 6c). Then rebase or merge 7a on top. Sequence:

```bash
git checkout phase6c-grok-hypothesis
git add docs/superpowers/ docs/devils-advocate/ wiki/ .env.example CLAUDE.md
# SKIP: wiki/Untitled.md (looks like an accidental file — check its content;
#       if empty or junk, `git rm` or just leave untracked)
# SKIP: .claude/scheduled_tasks.lock (local lockfile, should be gitignored — add
#       `.claude/scheduled_tasks.lock` to .gitignore before committing)
git commit -m "docs(phase6c+7a): specs, plans, daily logs, wiki, env template

Co-Authored-By: Cursor Cloud Agent <noreply@cursor.sh>"

git checkout phase7a-rust-execution
git rebase phase6c-grok-hypothesis   # should be a no-op fast-forward if clean
```

Check `CLAUDE.md` diff before staging — the modification might be a rename of
Betfair→Smarkets that's already reflected in `wiki/20-Markets/Venue-Strategy.md`.
If so, include it; otherwise ask.

## Execution plan

**Follow `docs/superpowers/plans/2026-04-21-phase7a-rust-execution-scaffold.md`
verbatim.** Tasks 1 through 10. Current state: Task 1 scaffold files are
written but not committed, and `cargo build` has not been run.

### Task ordering (mandatory, per spec §12)

```
1. Workspace skeleton + CI
2. Core types + Venue trait              (depends on 1)
3. Schema parity script                  (depends on 2)
4. MockVenue                             (depends on 2)
5. Smarkets crate + rate limiter         (depends on 2)
6. Smarkets HTTP client + Venue impl     (depends on 5)
7. execution-bin Redis consumer          (depends on 4, 6)
8. E2E Redis integration test            (depends on 7)
9. Dockerfile rust-build stage           (depends on 7)
10. Env + docs polish                    (depends on everything)
```

### Per-task commit discipline

One commit per task. Commit messages are pre-written in the plan — use them
verbatim. Add trailer `Co-Authored-By: Cursor Cloud Agent <noreply@cursor.sh>`.

Pre-commit hooks (`.pre-commit-config.yaml`) run on every commit and cover
Python files. Rust code is not linted by pre-commit — `cargo fmt --check`,
`cargo clippy -- -D warnings`, and `cargo test --workspace` must pass before
every commit (do these manually, no hook).

Do **not** use `--no-verify`. If a hook fails, fix the root cause.

### Finishing Task 1 (your first real work)

Files are already written. You need to:

1. Run `cd execution && cargo build` — confirm empty workspace compiles.
2. Run `cd execution && cargo fmt --check` — should pass (nothing to format).
3. Run `cd execution && cargo clippy --workspace --all-targets -- -D warnings`.
4. Edit `.github/workflows/ci.yml` — add a `rust` job per the plan (step list
   in Task 1). Use `Swatinem/rust-cache@v2` keyed on
   `execution/Cargo.lock` + `execution/rust-toolchain.toml`. `working-directory:
   execution`. Jobs: fmt-check, clippy, test.
5. Commit: `feat(execution): rust workspace scaffold + ci integration`.

Then proceed to Task 2.

### Tasks 2–10

Follow the plan. Each task lists exact files, dependencies, tests, and a
commit message. Verification commands are included inline.

Key points the plan **does not** spell out but matter:

- **`chrono` with `serde` feature** is required by core types (`DateTime<Utc>`).
  Pin: `chrono = { version = "0.4", features = ["serde"] }`.
- **`rust_decimal` serde feature**: `rust_decimal = { version = "1.36",
  features = ["serde-with-str"] }` — use string serialization so Python's
  `Decimal` round-trips without float precision loss.
- **`reqwest`**: `{ version = "0.12", default-features = false,
  features = ["json", "rustls-tls"] }` — no openssl dep, cleaner cross-compile
  for the Docker stage (Task 9).
- **`fred` (Redis)**: `fred = { version = "9", features = ["enable-rustls"] }`.
- **`governor`**: `0.7`. Rate limiter tests should use `tokio::time::pause()`
  for determinism.
- **`wiremock`**: dev-dep only in `execution-smarkets`.
- **`tokio` runtime**: Task 7 binary needs full features:
  `tokio = { version = "1", features = ["full"] }`.

If you hit a version conflict, resolve with latest-compatible; record the
exact pinned version in the task's commit message.

### Schema parity (Task 3) — detail

The plan suggests "constructed-instance method to avoid a new dep". Do it
this way:

1. `execution-core/src/bin/emit_schema.rs` builds sample instances of
   `OrderRequest`, `OrderState`, `ExecutionResult`, serialises each to JSON,
   and prints as one JSON Lines record per type: `{"type": "OrderRequest",
   "fields": [...]}` where `fields` is the list of keys from the serialized JSON.
2. `scripts/check_schema_parity.py` shells out to
   `cargo run --bin emit_schema --manifest-path execution/Cargo.toml`,
   parses the output, loads the Python pydantic models, diffs field names
   and exits non-zero on mismatch.
3. CI runs the script in the `rust` job after `cargo build`.

### Integration test (Task 8) — detail

Existing docker-compose already has Redis at `redis:6379` (used by Python
tests). The new `execution` service should share this network. In CI, the
integration test uses `docker compose up -d redis`, runs the Rust binary with
`VENUE=mock`, publishes 3 `order.signals`, polls `execution.results`, asserts.
Mark `#[ignore]` so `cargo test` without `--ignored` skips it.

## End-to-end verification (your pre-merge checklist)

After Task 10:

1. `cd execution && cargo fmt --check && cargo clippy --workspace
   --all-targets -- -D warnings && cargo test --workspace` — all green.
2. `uv run pytest` from repo root — all Python tests still green (6c must not
   regress).
3. `python scripts/check_schema_parity.py` — exits 0.
4. `docker compose up -d` and `docker compose logs execution` — service
   starts in mock mode, no Smarkets creds required.
5. `cargo test -p execution-bin --test integration_redis -- --ignored` — E2E
   integration test passes against the running Redis.

## Push sequence

Once Phase 7a is green end-to-end and all 10 tasks are committed:

```bash
git checkout phase6c-grok-hypothesis && git push -u origin phase6c-grok-hypothesis
git checkout phase7a-rust-execution && git push -u origin phase7a-rust-execution
```

**Do not push `main`.** Do not force-push anything. Do not open PRs
automatically — stop after push and leave PR creation to the user.

## Things NOT to do

- Do **not** modify any Phase 6c code (`services/research_orchestrator/`).
  If a test there breaks, it's a real regression — investigate before
  touching.
- Do **not** start writing Betfair or Kalshi venue impls. Spec is Smarkets-first;
  Betfair is Tier 2, post-7a.
- Do **not** add Polymarket integration (see `wiki/20-Markets/Polymarket-
  Feasibility-2026.md` — explicitly deferred).
- Do **not** use `unsafe` in Rust. Workspace-level `unsafe_code = "forbid"`
  is set in `execution/Cargo.toml`.
- Do **not** edit `.claude/settings.local.json` or `.claude/` contents other
  than adding `.claude/scheduled_tasks.lock` to `.gitignore`.
- Do **not** push `main`. Do **not** open PRs.
- Do **not** `git rebase -i` or `git push --force`. History-rewriting is
  off-limits.
- Do **not** commit secrets. `.env` is gitignored; only `.env.example` should
  carry placeholders.

## If you get stuck

- Blocked by missing info → stop and report; do not invent.
- Test flaky on Windows (multiprocessing, subprocess, etc.) → add `#[cfg(unix)]`
  skip marker if Unix-only (pattern established in `sandbox_runner.py`). If
  Rust-only, gate with `cfg(target_os = ...)`.
- `cargo clippy -D warnings` fails on a legitimate pedantic warning → add
  `#[allow(clippy::foo)]` with an inline comment explaining why. Don't
  disable at workspace level unless the warning is noisy across many files.
- Schema parity fails because of intentional field rename → update
  `algobet_common.schemas` and the Rust types together in the same commit;
  document the rename.

Good luck. The plan is solid — trust it, execute it, commit each task,
push at the end.
