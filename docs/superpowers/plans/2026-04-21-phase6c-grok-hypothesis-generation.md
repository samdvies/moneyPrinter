# Plan: Phase 6c — Agentic Hypothesis Generation (xAI Grok)

> **Spec:** `docs/superpowers/specs/2026-04-21-phase6c-grok-hypothesis-generation.md`
> **Preceded by:** Phase 6b merged on `main` (backtest harness + wiki↔registry loader + mean-reversion reference strategy)
> **Branch:** `phase6c-grok-hypothesis` (new, off `main`)

## Why now

6b shipped the backtest harness, a wiki↔registry loader, and a hand-written reference strategy. The orchestrator's `hypothesize()` is still a stub that returns a hard-coded dict. Everything downstream — research loop, auto-promotion to `hypothesis` state, prior-cycle learning — is gated on replacing that stub with a real generator.

6c closes the gap by landing a two-stage LLM pipeline (`grok-4` ideation → `grok-4-fast-reasoning` codegen), a strict AST-whitelist validator, a sandboxed runner, and the orchestration glue that ties them to the existing 6b harness.

**This phase is the first code in the repo that invokes xAI.** That means the AST validator and sandbox must land and be exhaustively tested *before* any live LLM call ever runs, per the safety sequencing in spec §11.

## Ordering invariant

Tasks MUST land in this order; reordering invalidates the safety story:

1. AST validator (rejects dangerous code)
2. Sandbox runner (kills what somehow slips past)
3. LLM client with mock backend only (no live key in use)
4. Context builder
5. Workflow rewrite wiring everything together — still mock-backed
6. End-to-end integration test, all-mocks green
7. Config + env additions
8. First live `--dry-run` call, manual inspection
9. Daily-log + wiki output wiring
10. Optional cron docs (off by default)

Each task is independently shippable (PR-per-task or commits-per-task depending on review load). Tests for each task must pass before the next starts.

## File structure

New files (all under `services/research_orchestrator/src/research_orchestrator/`):

- `ast_validator.py` — whitelist walker, pure stdlib, no deps
- `sandbox_runner.py` — subprocess orchestration, resource limits, network-block
- `llm_client.py` — xAI SDK wrapper, budget tracker, mock mode
- `context_builder.py` — Layer 1–4 assembly, registry + Timescale queries
- `features.py` — curated feature catalog (Layer 2 source of truth)
- `prompts/ideation_system.md` — Layer 1 static preamble (ideation)
- `prompts/codegen_system.md` — Layer 1 static preamble (codegen)
- `prompts/strategy_template.md` — wiki template referenced by ideation
- `spend_tracker.py` — SQLite-backed daily spend accounting

Modified:

- `workflow.py` — rewrite `hypothesize()` (currently a stub)
- `config.py` — add `XAI_*` and `HYPOTHESIS_*` env fields
- `services/research_orchestrator/pyproject.toml` — add `openai` SDK dep
- `.env.example` — add full `HYPOTHESIS_*` block (already has `XAI_*`)

New tests (under `services/research_orchestrator/tests/`):

- `test_ast_validator.py` — allowed/rejected fixture matrix + adversarial inputs
- `test_sandbox_runner.py` — escape-attempt suite
- `test_llm_client.py` — mock cassette + budget-cap
- `test_context_builder.py` — mocked registry + Timescale
- `test_workflow_hypothesize.py` — end-to-end with all LLMs mocked
- `tests/fixtures/adversarial_modules/*.py` — the 10 malicious modules from spec §9

No schema migrations. No Postgres changes. The `spend.db` SQLite file lives under `var/research_orchestrator/spend.db` and is gitignored.

---

## Task 1: AST whitelist validator (standalone, no external deps)

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/ast_validator.py`
- Create: `services/research_orchestrator/tests/test_ast_validator.py`
- Create: `services/research_orchestrator/tests/fixtures/validator_allowed/*.py` (10+ files, hand-written)
- Create: `services/research_orchestrator/tests/fixtures/validator_rejected/*.py` (20+ files covering every rejection reason in spec §4.3)

### Responsibilities

Single entry point:

```
validate(source: str) -> Result[ast.Module, list[Violation]]
```

Where `Violation` carries `node_type`, `line`, `col`, `reason`. Walker does a single-pass `ast.walk` + parent-child traversal to detect disallowed nodes, disallowed import targets, disallowed call targets, and local-only assign enforcement.

### Steps

- [ ] Enumerate the allowed/rejected node lists exactly from spec §4.3. Codify as module-level constants (`ALLOWED_NODES`, `ALLOWED_IMPORTS`, `ALLOWED_CALLABLES`, `REJECTED_CALLABLES`).
- [ ] Write test fixtures first — one file per allowed case (the 6b reference strategy source is a required allowed fixture) and one file per rejection reason (import `os`, `eval(...)`, `ClassDef`, `AsyncFunctionDef`, `Lambda`, decorator, `Try`/`Except`, `With`, `Raise`, `Delete`, `Assert`, global mutation, `__import__` attr access, `getattr`/`setattr`/`compile` call, deep attribute chain `obj.x.y.z.w` with a banned leaf, comprehension with side-effect call).
- [ ] Implement the validator to satisfy the fixture matrix. TDD: allowed fixtures parse to `Ok`; rejected fixtures produce `Err` with a violation at the right line.
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_ast_validator.py -v` — all fixtures pass/reject correctly.
- [ ] Commit: `feat(orchestrator): strict AST whitelist validator for generated strategies`

### Verification

- All 30+ fixtures green
- The 6b reference strategy `backtest_engine.strategies.mean_reversion` source file parses as allowed — tests assert this explicitly, because if the reference passes that's our floor for "can generate real strategies"
- Coverage report shows every `ALLOWED_NODES` entry is exercised

---

## Task 2: Sandbox runner (subprocess isolation)

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/sandbox_runner.py`
- Create: `services/research_orchestrator/tests/test_sandbox_runner.py`
- Create: `services/research_orchestrator/tests/fixtures/adversarial_modules/*.py` (10 files per spec §9 adversarial list)

### Responsibilities

Single entry point:

```
run_in_sandbox(
    module_source: str,
    entry_callable: str,
    args: tuple,
    cpu_seconds: int,
    mem_mb: int,
    wall_timeout_s: float,
) -> SandboxResult
```

Uses `multiprocessing.get_context("spawn").Process` — never `fork`. Before importing the user module, the child process:
1. Applies `resource.setrlimit(RLIMIT_CPU, ...)` and `RLIMIT_AS`
2. Monkey-patches `socket.socket`, `socket.create_connection`, `urllib.request.urlopen` to raise
3. Rebinds `__builtins__` to strip `__import__`, `open`, `eval`, `exec`, `compile` (belt-and-braces; AST validator is the primary defence)

IPC: parent sends `(source, entry, args)` pickled via stdin; child returns pickled `(Ok, result) | (Err, exception_repr)` via stdout.

### Steps

- [ ] Write each of the 10 adversarial module fixtures (subprocess fork-bomb, CPU spin, memory balloon, `socket.create_connection` call, `open('/etc/passwd')`, `__import__('os')`, deeply nested class with side-effects on import, infinite generator, pickle-RCE attempt, ctypes attempt). These modules MUST be rejected upstream by the AST validator — but the sandbox is belt-and-braces and must also contain them if invoked directly without validation.
- [ ] Write test cases: each adversarial module is passed directly to `run_in_sandbox` (bypassing validator) and asserted to return `SandboxResult.Killed(reason=...)` with the right reason within the timeout.
- [ ] Write a happy-path test: a trivial pure module that returns `42` passes through cleanly with correct result.
- [ ] Write a timeout test: an infinite loop hits wall-clock timeout and is killed.
- [ ] Implement `sandbox_runner.py` to make all of the above green.
- [ ] Document the Windows-dev-box limitation per spec §4.4 in the module docstring.
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_sandbox_runner.py -v`
- [ ] Commit: `feat(orchestrator): subprocess sandbox with cpu/mem/network caps`

### Verification

- All 10 adversarial tests kill-within-timeout
- Happy-path + timeout + OOM cases all green
- No test leaks a child process (pytest fixture cleanup asserts no child processes at teardown)

---

## Task 3: Spend tracker (SQLite daily budget)

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/spend_tracker.py`
- Create: `services/research_orchestrator/tests/test_spend_tracker.py`
- Modify: `.gitignore` (add `var/research_orchestrator/`)

### Responsibilities

```
class SpendTracker:
    def record(self, model: str, input_tokens: int, output_tokens: int) -> float: ...
    def cumulative_today_usd(self) -> float: ...
    def would_exceed(self, estimated_usd: float, cap_usd: float) -> bool: ...
```

Pricing table module-level constant keyed on model id, editable via config. UTC day boundary. Schema: single table `spend_events(ts_utc, model, input_tokens, output_tokens, usd)`.

### Steps

- [ ] TDD: test fresh DB → `cumulative_today_usd() == 0.0`
- [ ] TDD: record 3 events same day → cumulative equals sum of individual costs
- [ ] TDD: record events across UTC midnight boundary → today's cumulative excludes yesterday's events
- [ ] TDD: `would_exceed` returns true when current + estimate > cap, false otherwise
- [ ] Implement `spend_tracker.py`
- [ ] Add pricing constants keyed on `grok-4`, `grok-4-fast-reasoning`, `grok-4-fast-non-reasoning` from xAI pricing page (capture exact values as of impl date; mark with a `# verified YYYY-MM-DD` comment)
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_spend_tracker.py -v`
- [ ] Commit: `feat(orchestrator): sqlite-backed daily xai spend tracker`

### Verification

- All unit tests green
- DB file created at expected path on first use
- Boundary test (clock mocked) passes without flakes

---

## Task 4: LLM client with mock backend (no live xAI call yet)

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/llm_client.py`
- Create: `services/research_orchestrator/tests/test_llm_client.py`
- Create: `services/research_orchestrator/tests/fixtures/llm_cassettes/*.json` (recorded response fixtures)
- Modify: `services/research_orchestrator/pyproject.toml` — add `openai` dep
- Modify: `services/research_orchestrator/src/research_orchestrator/config.py` — add `XAI_*` fields

### Responsibilities

Contract (names final, other tasks depend on these):

```
class LLMClient:
    def ideate(self, context: IdeationContext) -> list[StrategySpec]: ...
    def codegen(self, spec: StrategySpec) -> str: ...
```

Mock mode: if `XAI_API_KEY == "mock"`, reads pre-recorded JSON from a configurable fixture dir. Every test in later tasks uses mock mode; the single live integration test gates on a real key.

Budget guard: every call first consults `SpendTracker.would_exceed` with the estimated cost (computed from prompt length × model price); raises `BudgetExceeded` before any HTTP round-trip.

### Steps

- [ ] Add `openai` to `pyproject.toml` and run `uv sync`
- [ ] Add `XAI_API_KEY`, `XAI_BASE_URL`, `XAI_MODEL_IDEATION`, `XAI_MODEL_CODEGEN`, `HYPOTHESIS_DAILY_USD_CAP` to `config.py` Settings
- [ ] Define `IdeationContext`, `StrategySpec`, `ParamRange` dataclasses in a new `types.py` (shared across modules)
- [ ] TDD: mock-mode `ideate` returns exactly 4 valid `StrategySpec` from a cassette fixture
- [ ] TDD: mock-mode `codegen` returns the cassette-recorded source string for a given spec
- [ ] TDD: malformed cassette JSON → raises; triggers one retry then abort (configurable retry count, default 1)
- [ ] TDD: budget-cap exceeded → raises `BudgetExceeded`, no HTTP call attempted (patch the openai client to a sentinel that would throw if called)
- [ ] Implement using the OpenAI SDK pointed at `XAI_BASE_URL`, JSON-mode enforced for ideation via `response_format={"type": "json_object"}`
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_llm_client.py -v`
- [ ] Commit: `feat(orchestrator): xai llm client with mock backend + budget guard`

### Verification

- All tests green in mock mode only (no network access required)
- `openai` package pinned to a known-good version
- Config loads `XAI_API_KEY` from env; absent key is explicitly allowed only when all tests run in mock mode

---

## Task 5: Context builder (Layers 1–4)

**Files:**
- Create: `services/research_orchestrator/src/research_orchestrator/features.py`
- Create: `services/research_orchestrator/src/research_orchestrator/context_builder.py`
- Create: `services/research_orchestrator/src/research_orchestrator/prompts/ideation_system.md`
- Create: `services/research_orchestrator/src/research_orchestrator/prompts/codegen_system.md`
- Create: `services/research_orchestrator/src/research_orchestrator/prompts/strategy_template.md`
- Create: `services/research_orchestrator/tests/test_context_builder.py`

### Responsibilities

```
class ContextBuilder:
    def build(self, cycle_id: str) -> IdeationContext: ...
```

Returned `IdeationContext` contains 4 fields mapping to Layers 1–4:

- `static`: str — loaded from `prompts/ideation_system.md`
- `features`: list[FeatureSpec] — loaded from `features.py` (1-liner each)
- `prior_cycles`: PriorCycleSummary — empty if <5 prior cycles, else top-K + bottom-K by Sharpe over last N cycles from strategy registry
- `regime`: RegimeStats — result of a parameterised SQL query over Timescale (last 7 days)

`features.py` is curated, not auto-generated. Initial seed lists: `best_bid`, `best_ask`, `mid`, `spread`, `book_imbalance`, `microprice`, `recent_mid_velocity`, `best_bid_depth`, `best_ask_depth`. Each entry has `name`, `expression_hint` (how to derive from `snapshot`), and `one_line_doc`.

### Steps

- [ ] Seed `features.py` with the 9 feature entries above (as a list of dataclass instances)
- [ ] Write `prompts/ideation_system.md` — project constraints from CLAUDE.md (UK venues, £1k cap, taker-focus, Smarkets book structure), the strategy interface contract, the AST whitelist summary, a pointer to the wiki template. Keep under 2k tokens.
- [ ] Write `prompts/codegen_system.md` — the strategy interface (`(snapshot, params) → signal | None`), the AST whitelist summary, the 6b mean-reversion source as worked example. Keep under 3k tokens.
- [ ] Write `prompts/strategy_template.md` — the wiki frontmatter + body template (matching the 6b loader contract in `docs/superpowers/plans/2026-04-20-phase6b-reference-strategy.md`).
- [ ] TDD: `build()` with empty registry → `prior_cycles` is empty, other layers populated
- [ ] TDD: `build()` with ≥5 prior cycles → `prior_cycles` contains top-K and bottom-K, ordered by Sharpe
- [ ] TDD: `build()` regime query result matches expected shape for a fixture time-series
- [ ] Implement `context_builder.py` — static + features load from disk; prior_cycles and regime query the registry and Timescale respectively via the existing `algobet_common.Database`
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_context_builder.py -v`
- [ ] Commit: `feat(orchestrator): 4-layer context builder for hypothesis generation`

### Verification

- All layers populated correctly from mocked DB fixtures
- The static prompt loads from disk and fits a token-count budget (assert `len(static) < 8000` chars as a rough gate)
- No network or LLM calls in this task

---

## Task 6: Workflow rewrite — `hypothesize()` orchestration

**Files:**
- Modify: `services/research_orchestrator/src/research_orchestrator/workflow.py` — replace `hypothesize()` body
- Modify: `services/research_orchestrator/src/research_orchestrator/config.py` — add remaining `HYPOTHESIS_*` fields
- Create: `services/research_orchestrator/tests/test_workflow_hypothesize.py`

### Responsibilities

`hypothesize()` orchestrates the full cycle per spec §3:

1. `context = ContextBuilder().build(cycle_id)`
2. `specs = llm.ideate(context)` → 4 `StrategySpec`
3. for each spec: `source = llm.codegen(spec); validate(source); sandbox_runner.run(backtest)`
4. persist passing strategies to registry (`state=hypothesis`) + write wiki
5. return `CycleReport`

On any stage failure per spec, the failure is recorded but the cycle continues with remaining specs.

### Steps

- [ ] Add `HYPOTHESIS_BATCH_SIZE`, `HYPOTHESIS_PRIOR_CYCLE_K`, `HYPOTHESIS_PRIOR_CYCLE_N`, `HYPOTHESIS_SANDBOX_CPU_SECONDS`, `HYPOTHESIS_SANDBOX_MEM_MB` to `config.py` Settings
- [ ] TDD: happy path — all 4 specs pass validation + sandbox → 4 registry rows written, 4 wiki files written, `CycleReport` shape matches spec §5
- [ ] TDD: 2 specs fail AST validation → 2 registry rows written, failures logged to `CycleReport.failures` with reason
- [ ] TDD: 1 spec sandbox-timeouts → recorded in `CycleReport` as sandbox-kill, registry unaffected for that spec
- [ ] TDD: `BudgetExceeded` raised during ideation → cycle aborts cleanly, no partial writes
- [ ] TDD: backtest returns zero trades → strategy not persisted; failure logged
- [ ] Implement the rewrite. Use the existing 6b `backtest_harness` and wiki writer unchanged.
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_workflow_hypothesize.py -v`
- [ ] Verify all previous orchestrator tests still green: `uv run pytest services/research_orchestrator/ -v`
- [ ] Commit: `feat(orchestrator): agentic hypothesize() wired end-to-end (mock-backed)`

### Verification

- End-to-end mock cycle green
- Existing 12 orchestrator tests still pass
- No live LLM call made during test run (assert via a sentinel patched into `openai`)

---

## Task 7: CLI + dry-run mode

**Files:**
- Modify: `services/research_orchestrator/src/research_orchestrator/__main__.py` (or create if absent — check first)
- Create: `services/research_orchestrator/tests/test_cli.py`

### Responsibilities

```
uv run orchestrator hypothesize [--dry-run] [--no-backtest]
uv run orchestrator spend-today
```

`--dry-run`: executes stages 1–5 of the cycle (context, ideate, codegen, validate, sandbox-import-only); skips backtest, registry, wiki. Prints generated specs and code to stdout.

`--no-backtest`: same as full cycle but skips backtest. Useful for debugging.

`spend-today`: prints current daily spend and remaining budget.

### Steps

- [ ] Check current `__main__.py` layout; either extend it or create using `argparse` (follow project convention — don't introduce `click`/`typer` if not already used)
- [ ] TDD: `--dry-run` invocation produces stdout containing 4 spec names and 4 code blocks; no DB writes (assert via mock Database)
- [ ] TDD: `spend-today` prints parseable line `Spend today: $X.XX / $Y.YY cap`
- [ ] Implement.
- [ ] Verify: `uv run pytest services/research_orchestrator/tests/test_cli.py -v`
- [ ] Manual smoke: `XAI_API_KEY=mock uv run orchestrator hypothesize --dry-run` — eyeball the output.
- [ ] Commit: `feat(orchestrator): hypothesize + spend-today CLI commands`

### Verification

- CLI commands run with mock backend
- `--dry-run` produces no side-effects beyond stdout

---

## Task 8: Wiki + daily-log output wiring

**Files:**
- Modify: `services/research_orchestrator/src/research_orchestrator/workflow.py` — add daily-log append step
- Modify: `services/research_orchestrator/src/research_orchestrator/wiki_writer.py` — add `write_hypothesis(spec, source, backtest_result) -> Path` if not already present; cross-check 6b's writer interface
- Add tests in `test_workflow_hypothesize.py`

### Responsibilities

On cycle completion, append a section to `wiki/70-Daily/YYYY-MM-DD.md` listing:
- Cycle id
- Per-spec outcome (passed / rejected + reason)
- Links to each generated `wiki/30-Strategies/proposed/<name>.md` file
- Cumulative spend delta

Proposed-strategy wiki files get YAML frontmatter matching the 6b loader contract plus 6c-specific fields: `generated_by`, `cycle_id`, `spec_sha256`, `code_sha256`.

### Steps

- [ ] Read the 6b `wiki_writer.py` to confirm the existing interface; extend or add new function per what's already there
- [ ] TDD: cycle completion writes exactly 1 daily-log section and N proposed-strategy files (N = number of passing specs)
- [ ] TDD: frontmatter contains all required 6b fields + new 6c fields; filename matches `strategy-id`
- [ ] TDD: CRLF preservation on Windows — must match 6b's existing CRLF handling (see recent commit `ef011f5`)
- [ ] Implement.
- [ ] Verify: all workflow tests green; wiki file shape inspected manually on one test run
- [ ] Commit: `feat(orchestrator): wiki + daily-log write-back for generated hypotheses`

### Verification

- Wiki files load cleanly via 6b loader (round-trip test)
- Daily log entry is appended, not overwritten, when a second cycle runs on the same date

---

## Task 9: First live Grok call — manual `--dry-run`

**Not a code task — a human-in-the-loop verification gate.** No commits in this task; purely operational.

**Prerequisites:**
- User has provisioned `XAI_API_KEY` in `.env`
- All tasks 1–8 are merged and tests green on `main`
- Optional: review Layer 1 prompt content one more time for tone + constraints

### Steps

- [ ] Set `XAI_API_KEY` to real key; `HYPOTHESIS_DAILY_USD_CAP=1.0` (conservative for first run)
- [ ] Run: `uv run orchestrator hypothesize --dry-run`
- [ ] Inspect stdout — does Grok produce 4 plausible specs? Does the code conform to the AST whitelist?
- [ ] Run: `uv run orchestrator spend-today` — confirm spend is under $0.10
- [ ] If specs look reasonable, proceed; if Grok produces nonsense, iterate on Layer 1 prompt before enabling full cycle
- [ ] Document findings + any prompt tweaks in `wiki/70-Daily/YYYY-MM-DD.md` as a `6c-shakedown` entry

### Verification

- 4 specs land in stdout
- No sandbox or validator rejections (if any rejected, iterate prompts until clean)
- Spend within budget

---

## Task 10: First live full cycle (no `--dry-run`)

- [ ] Run: `uv run orchestrator hypothesize` (full cycle)
- [ ] Check wiki for 4 new files under `wiki/30-Strategies/proposed/`
- [ ] Check strategy registry for 4 new rows at `state=hypothesis`
- [ ] Check daily log for the cycle summary section
- [ ] Review each generated strategy by hand; if any look suspect, manually set their registry state to `rejected` with a reason
- [ ] Commit the generated wiki files: `docs(wiki): first 6c-generated hypothesis cohort`

### Verification

- All four artefacts present
- No human-read flags anything dangerous
- Cumulative spend still under cap

---

## Task 11: Optional cron documentation

**Files:**
- Create: `services/research_orchestrator/CRON.md`

Not a wired-up cron — just documentation for the user to opt in once ≥5 manual cycles have produced no surprises.

### Steps

- [ ] Write `CRON.md` — single-page explaining: the commented cron line, the prerequisite of 5 clean manual cycles, how to disable, where logs go, how to check spend
- [ ] Link from `services/research_orchestrator/README.md` if present (or create a 1-section README pointing at it)
- [ ] Commit: `docs(orchestrator): document opt-in cron for hypothesize loop`

### Verification

- Doc renders correctly
- User can follow the instructions without asking questions

---

## Branch + PR strategy

- Branch `phase6c-grok-hypothesis` off `main`
- One PR per task, OR batch 1–2, 3, 4, 5, 6, 7–8, 11 into 6 PRs (task 9/10 aren't code)
- Each PR gates on: `ruff`, `mypy`, `pytest services/research_orchestrator/`, `pytest` at repo level to catch any accidental cross-service breakage
- Merge to `main` after task 10 complete + user manual review

## Out of scope (explicit — do not scope-creep)

- Semantic spec↔code equivalence checker (spec §13)
- Reinforcement learning / multi-agent debate
- Parameter-space search inside a hypothesis
- numpy/pandas expansion of AST whitelist
- New venues, new data sources, new strategy types

## Self-review note

Every spec section maps to at least one task:
- §3 flow → Task 6
- §4.1 llm_client → Task 4
- §4.2 context_builder → Task 5
- §4.3 ast_validator → Task 1
- §4.4 sandbox_runner → Task 2
- §4.5 workflow → Task 6
- §4.6 CLI + cron → Task 7 + Task 11
- §5 data contracts → Task 4 (types.py)
- §6 config → Tasks 4 + 6
- §7 budget guard → Tasks 3 + 4
- §8 wiki layout → Task 8
- §9 testing → every task has explicit test steps
- §10 observability → Task 4 (llm_client) + Task 6 (workflow logs)
- §11 rollout → Tasks 9 + 10 + 11
- §12 failure modes → Task 6 test matrix

No placeholders remain.
