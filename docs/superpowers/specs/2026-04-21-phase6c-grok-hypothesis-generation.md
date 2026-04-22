# Phase 6c — Agentic Hypothesis Generation (xAI Grok)

- **Status:** draft — awaiting user review
- **Date:** 2026-04-21
- **Supersedes stub:** `services/research_orchestrator/src/research_orchestrator/workflow.py` `hypothesize()`
- **Depends on:** Phase 6b (backtest harness, wiki write-back, strategy registry, mean-reversion reference strategy)
- **Unblocks:** agentic research loop; subsequent tuning phases

## 1. Goal

Replace the stub `hypothesize()` with a two-stage LLM pipeline that emits machine-executable, wiki-documented strategy candidates, auto-validates them, auto-backtests them, and lands passing candidates in the registry at `hypothesis` state — all without bypassing the human approval gate that sits between `paper` and `live`.

## 2. Non-goals

- No live-capital path. This phase produces candidates only; promotion to `paper` and `live` remain manually gated.
- No reinforcement learning, no fine-tuning, no multi-agent debate. Single-pass generation with prior-cycle feedback.
- No new venues, markets, or data sources beyond what 6b already ingests.
- No changes to the strategy interface or backtest harness.

## 3. End-to-end flow per cycle

```
[Trigger]
  → (1) assemble context (4 layers)
  → (2) Ideation call (grok-4) → JSON spec of 4 candidate strategies
  → for each of 4 specs:
        (3) Codegen call (grok-4-fast-reasoning) → Python module source
        (4) AST validator (whitelist) — reject on violation
        (5) Sandboxed import + interface check — reject on failure
        (6) Backtest (reuses 6b harness) — reject on zero trades / degenerate P&L
        (7) Registry insert: state=hypothesis, params populated
        (8) Wiki write-back: spec + code + backtest summary under wiki/30-Strategies/proposed/
  → Daily-log entry under wiki/70-Daily/YYYY-MM-DD.md summarising the cycle
```

Every reject step logs the failure reason to the daily log so failed generations feed Layer 3 on the next cycle.

## 4. Components

Lives in `services/research_orchestrator/src/research_orchestrator/`. One new subpackage per concern, each independently testable.

### 4.1 `llm_client`
Thin wrapper over the OpenAI-compatible xAI SDK. Handles: base_url config, API key from env, model selection per call, structured-output enforcement (JSON mode for ideation), retry on transient failures, per-call cost accounting against a daily budget cap.

Public surface:
- `ideate(context: IdeationContext) -> list[StrategySpec]`
- `codegen(spec: StrategySpec, whitelist: ASTWhitelist) -> str`
- `cumulative_spend_today_usd() -> float`

### 4.2 `context_builder`
Assembles the four context layers on demand, with Layer 3 gracefully empty before cycle 5.

- **Layer 1 (static):** project constraints, strategy interface contract, AST whitelist, wiki template. Stored as markdown templates under `research_orchestrator/prompts/`.
- **Layer 2 (features):** derived from a single source-of-truth file `research_orchestrator/features.py` listing snapshot primitives with one-line descriptions. Adding a feature requires a PR to this file (keeps Grok from hallucinating fields).
- **Layer 3 (prior cycles):** queries the strategy registry for top-K and bottom-K by Sharpe over the last N cycles. K=3, N=10 configurable.
- **Layer 4 (regime):** aggregate stats over the last 7 days of `market.data` — median spread, median book depth, sport mix. Implemented as a parameterised SQL query over Timescale; result is small (tens of rows) and infrequent (once per cycle), so no materialised view needed v1.

### 4.3 `ast_validator`
Strict whitelist walker. Single file, standalone, no external dependencies beyond `ast`. Inputs: source string. Outputs: `Ok(module_ast)` or `Err(violation_report)` listing every rejected node with file:line:col.

Whitelist (initial):
- Allowed imports: `math`, `statistics`, `dataclasses`
- Allowed node types: `FunctionDef`, `arguments`, `Return`, `If`, `IfExp`, `BoolOp`, `BinOp`, `UnaryOp`, `Compare`, `Call` (only to whitelisted names), `Name`, `Constant`, `Attribute` (read-only), `Tuple`, `List`, `Dict`, `Subscript`, `Assign` (local only), `AugAssign`
- Allowed callables: arithmetic ops, `math.*`, `statistics.*`, `min`, `max`, `abs`, `sum`, `len`, `round`, `sorted`
- Rejected outright: `Import` (other than whitelisted), `ImportFrom`, `ClassDef`, `AsyncFunctionDef`, `Global`, `Nonlocal`, `Lambda` (YAGNI for v1), `Try`, `With`, `Raise`, `Delete`, `Assert`, `comprehensions` with side-effects, any `Call` to `eval`/`exec`/`__import__`/`open`/`getattr`/`setattr`/`compile`

Rationale: everything the 6b reference strategy needed, nothing else.

### 4.4 `sandbox_runner`
Executes a validated module's backtest in an isolated subprocess. Responsibilities:
- Fresh subprocess per run (`multiprocessing.Process` with `spawn` start method, not `fork`)
- CPU limit (`resource.setrlimit(RLIMIT_CPU, ...)`) — default 60s
- Memory limit (`RLIMIT_AS`) — default 1 GB
- No network: on Linux production hosts, run inside a network namespace with no outbound access. On the Windows dev box (primary dev environment per `CLAUDE.md`) namespace isolation isn't available, so the sandbox additionally monkey-patches `socket.socket`, `socket.create_connection`, and `urllib.request.urlopen` to raise in the child process before the user's module is imported. Documented limitation: a determined adversary with ctypes access could bypass the monkey-patch, but ctypes is blocked upstream by the AST whitelist (`__import__` rejected, bare `import ctypes` rejected).
- Wall-clock timeout (orchestrator-side `join(timeout=...)`)
- stdin/stdout is the IPC channel; pickled input in, pickled `BacktestResult | ErrorReport` out

### 4.5 `workflow.hypothesize()` (rewrite)
Orchestrates the flow in §3. Replaces the existing stub. Reuses 6b's backtest harness and wiki writer unchanged.

### 4.6 CLI + optional cron
- New CLI: `uv run orchestrator hypothesize [--dry-run] [--no-backtest]`
- `--dry-run`: runs stages 1–5 but skips backtest + registry insert + wiki write; prints the generated specs and code
- Cron: off by default. A commented `schedule: 0 3 * * *` entry in `services/research_orchestrator/CRON.md` (docs only). The user enables it by copying into their system cron of choice.

## 5. Data contracts

### StrategySpec (ideation output)
```python
@dataclass(frozen=True)
class StrategySpec:
    name: str                    # snake_case, unique per cycle
    rationale: str               # 1–3 sentences, grounded in market microstructure
    signal_formula: str          # pseudocode, human-readable
    params: dict[str, ParamRange]  # name → {type, min, max, default}
    entry_rules: str
    exit_rules: str
    expected_edge: str           # argument for why this has edge given Layer 4 regime
```

Ideation call uses xAI JSON-mode to emit a `{"hypotheses": [StrategySpec, ...]}` envelope with exactly 4 items. Strict schema validation on return; a malformed response triggers one retry then abort.

### GeneratedStrategy (codegen output)
```python
@dataclass(frozen=True)
class GeneratedStrategy:
    spec: StrategySpec
    source: str                  # the Python module
    sha256: str                  # of source
    module_path: Path            # where it was written
```

### CycleReport
Per-cycle summary written to the daily log and returned from `hypothesize()`. Includes: 4 specs, validation pass/fail per spec, backtest result per passing spec, cumulative spend delta.

## 6. Configuration

Extends `services/research_orchestrator/src/research_orchestrator/config.py`. New fields:

- `XAI_API_KEY: str` (required)
- `XAI_BASE_URL: str` (default `https://api.x.ai/v1`)
- `XAI_MODEL_IDEATION: str` (default `grok-4`)
- `XAI_MODEL_CODEGEN: str` (default `grok-4-fast-reasoning`)
- `HYPOTHESIS_BATCH_SIZE: int` (default 4)
- `HYPOTHESIS_DAILY_USD_CAP: float` (default 5.0)
- `HYPOTHESIS_PRIOR_CYCLE_K: int` (default 3)
- `HYPOTHESIS_PRIOR_CYCLE_N: int` (default 10)
- `HYPOTHESIS_SANDBOX_CPU_SECONDS: int` (default 60)
- `HYPOTHESIS_SANDBOX_MEM_MB: int` (default 1024)

Daily spend is tracked in a small SQLite file under `var/research_orchestrator/spend.db` (not Postgres — this is service-local accounting, not shared state). Reset on UTC midnight boundary.

## 7. Budget guard

Before every xAI call, `llm_client` checks `cumulative_spend_today_usd() + estimated_call_cost < HYPOTHESIS_DAILY_USD_CAP`. If not, raises `BudgetExceeded` and the workflow aborts the cycle with a loud log line. Estimated cost is model's input+output price × observed-token-per-call running average.

## 8. Wiki layout

Generated candidates land under:
```
wiki/30-Strategies/
  proposed/
    2026-04-21-<strategy-name>.md   # spec + code + backtest summary
  ...
```

YAML frontmatter: `status: hypothesis`, `type: strategy`, `generated_by: grok-4+grok-4-fast-reasoning`, `cycle_id`, `spec_sha256`, `code_sha256`.

Daily log (`wiki/70-Daily/YYYY-MM-DD.md`) appends a section per cycle linking to each proposed note.

## 9. Testing strategy

- **Unit:** `ast_validator` — exhaustive allowed/rejected fixtures; `context_builder` with mocked registry; `llm_client` with a recorded-cassette xAI mock; `sandbox_runner` escaping attempts (import forbidden lib, infinite loop, memory balloon, network call).
- **Integration:** end-to-end cycle with a mocked Grok that returns a known-good spec + known-good code → assert registry row + wiki file + daily log.
- **Adversarial:** 10 hand-crafted malicious "generated" modules (shell-out, file read, network exfil, fork bomb, CPU spin, memory balloon, `__import__` tricks, decorator abuse, pickle RCE, long-running infinite comprehension) — each must be rejected before execution or killed by sandbox.
- **Cost test:** budget cap is respected; synthetic spend accumulation hits the cap and aborts correctly.

## 10. Observability

- Every LLM call logs: model, input tokens, output tokens, $ cost, duration, cycle_id.
- Every validator rejection logs the full violation report.
- Every sandbox kill logs the reason (cpu, mem, timeout, network).
- Cumulative daily spend exposed via a CLI: `uv run orchestrator spend-today`.

## 11. Rollout

1. Land `ast_validator` + `sandbox_runner` first (they're the safety floor; useful even without Grok).
2. Land `llm_client` with a mock backend; full test suite passes without touching xAI.
3. Land `context_builder`; integration test uses a seeded registry + fixture market data.
4. Wire `workflow.hypothesize()`; integration test with all-mocks green.
5. First live Grok call: manual CLI, `--dry-run`, 1 cycle, review the 4 generated specs by hand before removing `--dry-run`.
6. Promote to optional cron only after ≥5 manual cycles have produced no AST-validator or sandbox surprises.

## 12. Failure modes and mitigations

| Failure | Detection | Mitigation |
|---|---|---|
| Ideation returns malformed JSON | schema validation | 1 retry, then abort cycle; log raw response |
| Codegen produces non-whitelisted AST | `ast_validator` | reject + log; cycle continues with remaining specs |
| Generated module fails to import | `sandbox_runner` | reject + log |
| Backtest degenerate (zero trades, NaN Sharpe) | harness checks | reject + mark as low-signal in Layer 3 |
| Spec↔code drift (passes AST, doesn't implement spec) | no automatic detection v1 | wiki artefact is human-auditable; monitor during first 20 cycles; add semantic-check stage only if empirically warranted |
| Budget cap hit mid-cycle | `llm_client` | abort cleanly; partial cycles don't write to registry or wiki |
| xAI API outage | exception | retry 3× with exponential backoff then abort cycle |

## 13. Out of scope (deferred)

- Multi-candidate ranking (just emit all 4 as equals for now)
- Parameter-space search within a hypothesis (hand off to a future 6d)
- Semantic spec↔code equivalence checker (wait for evidence it's needed)
- numpy/pandas in whitelist (expand deliberately later if a real strategy needs them)
- Running the sandbox on strict-seccomp Linux (defer platform-specific hardening until we have a production host picked)

## 14. Open decisions resolved by this spec

- **D2 (model choice):** split — `grok-4` for ideation, `grok-4-fast-reasoning` for codegen.
- **D3 (no-cache strategy):** batch-of-4 for ideation (amortises preamble); per-spec codegen calls (smaller preamble, still cheap).

## 15. Open decisions still outstanding after 6c lands

- When to expand the AST whitelist (and the governance for doing so).
- Whether to add a Stage-3 self-critique call — defer until we have spec↔code drift evidence.
- Whether prior-cycle Layer 3 should include the *full* losing strategy source, or just a summary. Start with summary + top-line metrics; revisit.
