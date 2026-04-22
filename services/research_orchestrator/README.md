# research_orchestrator

Agentic hypothesis generation + promotion loop. Phase 6c wires xAI Grok
into `hypothesize()`; Phase 6b wires the backtest harness + wiki round-trip.

## CLI

```
uv run orchestrator hypothesize            # full cycle (ideate → codegen → validate → sandbox → backtest → persist → wiki)
uv run orchestrator hypothesize --dry-run  # stages 1–5 only, prints specs + code, no writes
uv run orchestrator hypothesize --no-backtest
uv run orchestrator spend-today            # prints cumulative xAI spend vs daily cap
uv run python -m research_orchestrator run # legacy single-iteration loop (Phase 6b)
```

## Opt-in cron

See [CRON.md](CRON.md) for the scheduled-cycle opt-in. **Default: off.**
Only enable after ≥5 clean manual cycles.

## Safety sequencing

Per spec §11: AST validator + sandbox runner landed before any live xAI
call. Tests run in mock mode via the `XAI_API_KEY=mock` cassette-replay
path; no network access in CI.
