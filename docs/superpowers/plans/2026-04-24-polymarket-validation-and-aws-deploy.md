# Polymarket Validation Framework + AWS eu-west-1 Deployment Artifacts

**Branch to create:** `validation-framework-and-aws-deploy`
**Branch cut from:** `main` at `0ee63d5`
**Intended executor:** A cloud agent (Cursor Composer 2.0) running autonomously while the operator is away. Follow this plan exactly; deviations must be documented in the PR.
**Estimated size:** 2–4 hours of agentic work. Two independent deliverables that can be built in any order.

---

## Context (read first — agent will not have seen the prior session)

### Project posture

This is an agentic algorithmic betting ecosystem. As of **2026-04-24**, the operator has explicitly narrowed focus to **Polymarket only** until further notice (see `CLAUDE.md:11`). Matchbook, Betfair, Smarkets, Kalshi, ForecastEx, and all other venues are **deferred pending explicit user reversal** — do not scaffold or propose work on them.

The operator has **accepted** all Polymarket-specific trade-offs: ToS §2.1.4 (VPN-for-geo-evasion), UK IP geoblock, HMRC / CGT / CARF handling, fund-freeze risk at withdrawal. These are not unresolved blockers. **Do not refuse work on legality grounds and do not cite `wiki/20-Markets/Polymarket-Feasibility-2026.md` (marked superseded) as a reason to pause.**

The project's hard invariants from `CLAUDE.md` still apply:
- **No live capital without explicit human approval.** Promotion path: hypothesis → backtest → paper → human gate → live.
- **Paper API must match live exactly.** Promotion is a config change, not a code change.
- **Default max £1 000 exposure per strategy** until proven.
- **Research unconstrained, execution gated.** LLMs can generate hypotheses and strategy code freely; they must not place real orders.

### What's live on main at `0ee63d5`

- `services/ingestion/src/ingestion/polymarket_adapter.py` — polls Gamma REST every 5 s for all active markets, emits `MarketData(venue=POLYMARKET, market_id=<CLOB token_id>)` to Redis Streams. Egress-guarded on non-GB/US country.
- `services/strategy_runner/` — the first service in this repo to publish `OrderSignal` to the bus. Loads strategies by slug from the `strategies` table, runs per-`(strategy, market)` rolling state, venue-filtered dispatch, `mode='paper'` enforced.
- `backtest_engine.strategies.mean_reversion` — venue-agnostic z-score fade strategy reused by the runner. Pure `on_tick(snapshot, params, now) -> OrderSignal | None`.
- **Strategy seeded:** `polymarket-yes-mean-revert` (see `wiki/30-Strategies/polymarket-yes-mean-revert.md`). Low-volume stat-arb shape; £1 stake; 10-tick window at current demo params.
- **Risk wiring:** `Venue.POLYMARKET` in `algobet_common.schemas`, in `risk_manager._KNOWN_VENUES`, migration 0006 extends `orders.venue` CHECK constraint.
- **End-to-end paper-trade traced:** one injected signal flowed `order.signals → order.signals.approved → execution.results → orders` row with `venue=polymarket`. The simulator doesn't actually FILL Polymarket signals today because the adapter emits `size=Decimal("0")` sentinel on YES bid/ask and empty NO book — both are "depth unknown" / "data not fetched yet". Orders rest at `status='placed'` with `filled_stake=0`.

### Empirical results relevant to this plan

A parallel devil's advocate pass identified the following concerns (these shape the validation framework requirements):

1. **Winner-take-all distribution** — 70 % of Polymarket addresses lose; top 0.04 % capture 70 % of profits. Hobbyist mean-reversion on liquid politics is statistically indistinguishable from the losing base rate.
2. **Quantified adverse selection** — $143 M captured by "informed" traders per academic analysis. Sharps + insiders concentrate in politics/geopolitics.
3. **Fee + spread round-trip ~5 %** at £100 notional / 50 ¢ midpoint on politics markets. Current strategy doesn't clear this.
4. **MM reward program (quadratic scoring)** compresses spreads on high-volume markets — hobbyist makers can't compete there.
5. **UMA oracle resolution risk** — Zelenskyy suit market flipped after 9 days; Ukraine mineral deal lost $7 M to a governance whale, Polymarket refused refunds.
6. **5 s polling = structurally taker-only, adversely selected.** Pro MMs observe via WebSocket at 10–50 ms.

**Do not rebuild these critiques — they're findings, not requirements.** The validation framework below is what lets us measure whether a given candidate strategy survives these filters.

An AWS test from eu-west-1 (Dublin) confirmed:
- `/api/geoblock` returns `blocked:false` from Irish AWS IP
- Gamma `/markets` and CLOB `/price` respond in ~36 ms
- No Cloudflare datacenter blocking
- **Meaning: we can deploy everything to eu-west-1 with no VPN**

---

## Deliverable 1 — Validation framework (pure scripts; no LLMs)

**Location:** `services/backtest_engine/src/backtest_engine/`

The operator explicitly requires: validation must be deterministic scripts, not LLM judgment. LLMs can generate hypotheses + code; LLMs must not compute metrics or decide promotion.

### Build order (one commit per module, each green before moving on)

#### 1. `metrics.py`

Pure functions operating on numpy arrays / `pd.Series` / lists of dicts. No logging, no side effects.

Required public API:

```python
def compute_sharpe(returns: np.ndarray, ann_factor: float = 252) -> float: ...
def compute_sortino(returns: np.ndarray, ann_factor: float = 252, mar: float = 0.0) -> float: ...
def compute_max_drawdown(equity_curve: np.ndarray) -> dict:
    """Returns {'peak': float, 'trough': float, 'depth_pct': float, 'duration_bars': int}"""
def compute_calmar(returns: np.ndarray, equity_curve: np.ndarray, ann_factor: float = 252) -> float: ...
def compute_hit_rate(trades: list[dict]) -> float: ...  # fraction of trades with pnl > 0
def compute_win_rate(trades: list[dict]) -> float: ...  # alias of hit_rate for clarity
def compute_profit_factor(trades: list[dict]) -> float: ...  # sum(wins) / abs(sum(losses))
def compute_expectancy(trades: list[dict]) -> float: ...  # avg pnl per trade
def compute_avg_trade(trades: list[dict]) -> float: ...
def compute_all_metrics(trades: list[dict], equity_curve: np.ndarray, ann_factor: float = 252) -> dict:
    """Aggregates everything into one dict; keys are snake_case."""
```

A `trade` is `{'entry_ts': datetime, 'exit_ts': datetime, 'pnl': Decimal | float, 'stake': ..., 'venue': str, 'market_id': str}`.

Fully typed, `from __future__ import annotations`, full docstrings explaining conventions (e.g. "returns are assumed to be arithmetic, not log"). Use `scipy.stats` only where unavoidable.

**Tests** (`services/backtest_engine/tests/test_metrics.py`):
- Hand-computed Sharpe on a known 10-value return series — assert matches to 6 decimal places.
- Max drawdown on a monotonically-decreasing series (100%), monotonically-increasing (0%), V-shape (known depth).
- Win rate / hit rate / profit factor / expectancy on small fixtures with manual-verify answers.
- `compute_all_metrics` returns every documented key.
- Edge cases: empty inputs raise `ValueError`; all-zero returns produce Sharpe=0 or NaN, documented behaviour either way.

#### 2. `significance.py`

Deterministic with explicit seed input (`rng: np.random.Generator | None = None`).

Required public API:

```python
def bootstrap_sharpe_ci(returns: np.ndarray, n_bootstrap: int = 10_000, alpha: float = 0.05,
                        rng: np.random.Generator | None = None) -> tuple[float, float]: ...
def block_bootstrap_ci(returns: np.ndarray, metric_fn: Callable, block_size: int = 20,
                        n_bootstrap: int = 10_000, alpha: float = 0.05,
                        rng: np.random.Generator | None = None) -> tuple[float, float]: ...
def t_test_vs_zero(returns: np.ndarray) -> dict:
    """Returns {'t_stat', 'p_value', 'df', 'mean', 'std_err'}"""
def compare_to_random_baseline(strategy_trades: list[dict], n_simulations: int = 1_000,
                                reference_returns: np.ndarray | None = None,
                                rng: np.random.Generator | None = None) -> dict:
    """
    Null: trades are random entries on the same underlying.
    Returns {'p_value_sharpe', 'p_value_mean_pnl', 'sharpe_percentile', 'mean_pnl_percentile'}.
    """
```

**Tests** (`test_significance.py`):
- Seed a generator, call `bootstrap_sharpe_ci` on a known series, assert CI contains the analytical Sharpe.
- `t_test_vs_zero` on normal(0, 1) sample of size 1000 — p-value not significant at α=0.05. On normal(0.3, 1) — significant.
- Block bootstrap on AR(1)-generated returns — CI should be WIDER than iid bootstrap on the same series. Assert this inequality.
- `compare_to_random_baseline` on trades generated by a deterministic no-edge strategy — p-value should be non-significant in expectation (check over 20 seeded runs, at least 85% non-significant at α=0.05).

#### 3. `walkforward.py`

```python
@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: int  # bar index inclusive
    train_end: int
    test_start: int
    test_end: int

def generate_splits(n_bars: int, train_bars: int, test_bars: int, step: int | None = None) -> list[WalkForwardSplit]:
    """Rolling walk-forward. step defaults to test_bars (no overlap in test windows)."""

def walkforward_run(
    strategy_on_tick: Callable[[MarketData, dict, datetime], OrderSignal | None],
    ticks: list[MarketData],
    split_cfg: WalkForwardSplit,
    params: dict,
    fit_fn: Callable[[list[MarketData], dict], dict] | None = None,
) -> dict:
    """Runs strategy on IS split, optionally refits params, then runs on OOS split.
    Returns {'in_sample': metrics_dict, 'out_of_sample': metrics_dict, 'split': split_cfg}."""

def summarise_walkforward(results: list[dict]) -> dict:
    """IS vs OOS aggregate + degradation ratios.
    Returns {'mean_is_sharpe', 'mean_oos_sharpe', 'degradation_ratio', 'oos_win_consistency', ...}."""
```

For this initial delivery, a strategy is *parameterless refit* by default — `fit_fn=None` means params are constant across splits. Leave the `fit_fn` hook for future strategies that tune.

**Tests** (`test_walkforward.py`):
- `generate_splits` math: assert number of splits = `(n_bars - train_bars) // step` and first/last split indices.
- `walkforward_run` with a toy strategy on synthetic data — returns both IS and OOS dicts with expected keys.
- `summarise_walkforward` on synthetic results showing degradation — degradation ratio matches manually-computed value.

#### 4. `param_sweep.py`

```python
def param_grid(param_ranges: dict[str, list]) -> Iterator[dict]: ...
def run_sweep(
    strategy_on_tick: Callable,
    ticks: list[MarketData],
    grid: Iterator[dict],
    metric: str = 'sharpe',
) -> pd.DataFrame:
    """Returns DataFrame with one row per grid point, columns = params + all metrics."""

def stability_score(df: pd.DataFrame, metric: str = 'sharpe', top_k: int = 5) -> float:
    """Of the top_k parameter points by `metric`, return the std/mean ratio of `metric` values.
    Lower = more stable; >0.3 typically indicates overfitting."""
```

**Tests** (`test_param_sweep.py`):
- `param_grid` on `{'a': [1,2], 'b': [3,4]}` produces 4 combinations.
- `run_sweep` on a toy strategy with 2 params × 3 values = 9 rows, Sharpe column populated.
- `stability_score` on a df with very spiky metric distribution — score should be > 0.5.
- `stability_score` on a flat-ish distribution — score < 0.2.

#### 5. `regimes.py`

Simple starter labelling. No need for sophisticated HMM; the goal is to answer "does this strategy's edge concentrate in one regime?"

```python
def label_vol_regime(prices: pd.Series, window: int = 30, quantile_high: float = 0.75) -> pd.Series:
    """Rolling std percentile. Returns 'high' / 'low' Series aligned to prices."""
def label_trend_regime(prices: pd.Series, window: int = 30, slope_threshold: float = 0.001) -> pd.Series:
    """Rolling regression slope. Returns 'up' / 'down' / 'flat'."""
def regime_conditional_metrics(trades: list[dict], regimes: pd.Series, metric_fn: Callable) -> dict[str, float]:
    """Per-regime metric values. Requires trade entry_ts to align to regime series timestamps."""
```

**Tests** (`test_regimes.py`):
- Synthetic high-vol slice — labels 'high' in that slice.
- Rising trend — `label_trend_regime` returns 'up'.
- `regime_conditional_metrics` on fixture returns per-regime values summing consistently.

#### 6. `validate.py` (CLI + orchestration)

```python
@dataclass(frozen=True)
class BacktestReport:
    strategy_slug: str
    run_id: str  # uuid
    run_ts: datetime
    data_source: str  # 'synthetic' | 'archive'
    n_trades: int
    metrics: dict
    significance: dict
    walkforward: dict
    param_sweep_path: str | None  # relative to artifacts/
    regime_metrics: dict
    promotion_pass: bool
    failure_reasons: list[str]

def validate_strategy(strategy_slug: str, data_source: str = 'synthetic',
                       n_synthetic_ticks: int = 5_000,
                       param_sweep: bool = True,
                       walkforward_splits: int = 5,
                       **config) -> BacktestReport: ...

# CLI: `uv run python -m backtest_engine.validate --strategy polymarket-yes-mean-revert --synthetic`
#   writes artifacts/backtests/<slug>/<YYYY-MM-DD-HHMMSS>/metrics.json,
#          walkforward.csv, param_sweep.csv, regimes.json, report.md
```

The markdown `report.md` is generated by a plain Jinja2 template (deterministic). It is **not** LLM-written. The first line of the report says `Generated by backtest_engine.validate at <ts>. Numbers in this report are produced by deterministic scripts.`

**Synthetic data generator** for initial validation (archive is empty):
- Generate a random walk at 1 s cadence for N hours
- Shape it into `MarketData` objects matching the `POLYMARKET` schema
- Reproducible with seed
- Sufficient to drive the whole pipeline end-to-end

**Tests** (`test_validate.py`):
- End-to-end run on synthetic data produces a complete `BacktestReport`.
- Report artifacts exist on disk at the expected paths.
- `run_id` is a valid UUID.
- Running twice with the same seed produces byte-identical numerical outputs.

#### 7. `promotion_gate.py`

```python
def load_thresholds(strategy_slug: str, wiki_root: Path = Path('wiki/30-Strategies')) -> dict:
    """Reads the strategy's wiki frontmatter, expects a `promotion_thresholds:` block.
    Missing/empty → return project defaults."""

def check_promotion_criteria(report: BacktestReport, thresholds: dict) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_failure_reasons).
    Default thresholds: sharpe >= 0.5, max_dd_pct >= -20, hit_rate >= 0.45, p_value_sharpe <= 0.05,
    walkforward_degradation <= 0.5 (OOS Sharpe at least half of IS Sharpe)."""

# CLI: `uv run python -m backtest_engine.promotion_gate --report artifacts/backtests/<slug>/<ts>/report.json`
#   prints PASS / FAIL with reasons. Exit code 0 on pass, 1 on fail.
```

Add a `promotion_thresholds:` block to `wiki/30-Strategies/polymarket-yes-mean-revert.md` frontmatter with the defaults above, so the framework has something concrete to check against.

**Tests** (`test_promotion_gate.py`):
- Passing report → returns `(True, [])`.
- Failing Sharpe → returns `(False, [reason_mentioning_sharpe])`.
- Failing multiple criteria → multiple reasons.
- Loads thresholds from a fixture wiki file.

### Dependencies to add to `services/backtest_engine/pyproject.toml`

```
dependencies = [
    "algobet-common",
    "simulator",
    "strategy-registry",
    "numpy>=1.26",
    "pandas>=2.1",
    "scipy>=1.11",
    "jinja2>=3.1",
]
```

(numpy / pandas / scipy likely already present transitively; pin explicitly.)

### End-to-end sanity on current Polymarket strategy

Once the above is built, run `uv run python -m backtest_engine.validate --strategy polymarket-yes-mean-revert --synthetic` as part of the CI for the branch. **Expect it to FAIL the promotion gate** — the DA agent already predicted this. Producing a report that says "FAIL: Sharpe 0.2 with 95 % CI [-0.4, 0.8] not significantly > 0; OOS Sharpe is 40 % of IS Sharpe, suggesting overfitting" is a **successful** outcome of this deliverable, because it means the framework is doing its job.

Add the generated `report.md` to `wiki/30-Strategies/polymarket-yes-mean-revert-backtest-2026-04-24.md` (replace date token with actual run date) as a durable record.

---

## Deliverable 2 — AWS eu-west-1 deployment artifacts (producer-only; agent does NOT deploy)

**Location:** `deploy/` at repo root + a Dockerfile per Python service.

### 1. Dockerfiles per service

Create:

- `services/ingestion/Dockerfile`
- `services/simulator/Dockerfile`
- `services/risk_manager/Dockerfile`
- `services/strategy_runner/Dockerfile`

All identical structure:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY services/ services/
RUN uv sync --frozen --no-dev --package <service-name>

FROM python:3.12-slim
COPY --from=builder /app /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
CMD ["python", "-m", "<service-module>"]
```

Substitute `<service-name>` (hyphenated, e.g. `ingestion`, `strategy-runner`) and `<service-module>` (underscored, e.g. `ingestion`, `strategy_runner`).

### 2. `deploy/docker-compose.prod.yml`

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

  postgres:
    image: timescale/timescaledb:latest-pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-algobet}
      POSTGRES_USER: ${POSTGRES_USER:-algobet}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set in .env}
    volumes:
      - postgres-data:/var/lib/postgresql/data

  ingestion:
    build: { context: .., dockerfile: services/ingestion/Dockerfile }
    restart: unless-stopped
    environment:
      SERVICE_NAME: ingestion-polymarket
      INGESTION_MODE: polymarket
      POLYMARKET_POLL_INTERVAL_SECONDS: "1.0"
      POLYMARKET_PAGE_SIZE: "500"
      REDIS_HOST: redis
      POSTGRES_HOST: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    depends_on: [redis, postgres]

  simulator:
    build: { context: .., dockerfile: services/simulator/Dockerfile }
    restart: unless-stopped
    environment:
      SERVICE_NAME: simulator
      REDIS_HOST: redis
      POSTGRES_HOST: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    depends_on: [redis, postgres]

  risk_manager:
    build: { context: .., dockerfile: services/risk_manager/Dockerfile }
    restart: unless-stopped
    environment:
      SERVICE_NAME: risk-manager
      REDIS_HOST: redis
      POSTGRES_HOST: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    depends_on: [redis, postgres]

  strategy_runner:
    build: { context: .., dockerfile: services/strategy_runner/Dockerfile }
    restart: unless-stopped
    environment:
      SERVICE_NAME: strategy-runner
      REDIS_HOST: redis
      POSTGRES_HOST: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    depends_on: [redis, postgres]

volumes:
  redis-data:
  postgres-data:
```

No ports published externally — everything internal except SSH to the host.

### 3. `deploy/.env.prod.template`

```
# Copy to .env.prod and fill in values. DO NOT COMMIT .env.prod.
POSTGRES_DB=algobet
POSTGRES_USER=algobet
POSTGRES_PASSWORD=<set-a-strong-random-value>
POLYMARKET_POLL_INTERVAL_SECONDS=1.0
POLYMARKET_PAGE_SIZE=500
# XAI_API_KEY=<set-from-parameter-store-later>
```

### 4. `deploy/bootstrap.sh` (EC2 user-data)

```bash
#!/bin/bash
set -euo pipefail
# Runs as EC2 user-data on first boot, Amazon Linux 2023 arm64.

dnf update -y
dnf install -y git docker
systemctl enable --now docker
usermod -aG docker ec2-user

mkdir -p /opt
cd /opt
git clone https://github.com/samdvies/moneyPrinter.git algo-betting
cd algo-betting

# apply migrations once postgres is up
cat > /etc/systemd/system/algo-betting.service <<'EOF'
[Unit]
Description=algo-betting docker compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/algo-betting
EnvironmentFile=/opt/algo-betting/deploy/.env.prod
ExecStart=/usr/bin/docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
ExecStop=/usr/bin/docker compose -f deploy/docker-compose.prod.yml down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable algo-betting.service
# Don't start yet — operator must provision .env.prod first.
```

Pre-pass with shellcheck; all code under `set -euo pipefail`.

### 5. `deploy/provision.sh`

Operator-run wrapper (agent should NOT execute). Uses AWS CLI to create the infra:

```bash
#!/bin/bash
set -euo pipefail
# Run from your laptop after configuring AWS CLI with credentials.
# Creates a t4g.small EC2 instance in eu-west-1 with Elastic IP and Security Group.

REGION=eu-west-1
KEY_NAME=${KEY_NAME:-algo-betting}
SG_NAME=algo-betting-sg
HOME_CIDR=${HOME_CIDR:?set to your home IP in CIDR form, e.g. 1.2.3.4/32}
AMI_ID=$(aws ec2 describe-images --region "$REGION" --owners amazon \
  --filters 'Name=name,Values=al2023-ami-2023.*-arm64' 'Name=state,Values=available' \
  --query 'sort_by(Images, &CreationDate) | [-1].ImageId' --output text)

# ... (security group creation, key pair import, run-instances, allocate-address, associate)
```

Full implementation: ~80 lines of bash. Idempotent: if the SG exists, reuse; if the key exists, skip import; if the instance tag already has one, print its IP instead of launching a duplicate.

### 6. `deploy/README.md`

One-page operator guide. Includes:
- Prerequisites (AWS CLI configured, home IP, SSH key generated locally)
- One-line `provision.sh` invocation
- How to SSH in (`ssh -i <key> ec2-user@<eip>`)
- How to set `.env.prod` (copy template, edit, `sudo systemctl start algo-betting`)
- How to tail logs (`docker compose logs -f <service>`)
- How to apply DB migrations after first start (`docker compose exec ingestion uv run python -m scripts.migrate`)
- How to seed the Polymarket strategy (`docker compose exec strategy_runner uv run python -m scripts.seed_polymarket_strategy`)
- How to tear down (`sudo systemctl stop algo-betting; aws ec2 terminate-instances ...`)
- Cost estimate: t4g.small £12/mo + 30 GB gp3 £2/mo + CloudWatch Logs <£1/mo = **~£15/mo total**
- Architecture ASCII diagram:

```
┌─────────────────────────────────────┐
│ EC2 t4g.small eu-west-1 (Dublin)    │
│                                     │
│  ┌─────────┐  ┌──────────┐          │
│  │ redis   │  │ postgres │          │
│  └────┬────┘  └─────┬────┘          │
│       │             │               │
│  ┌────▼─────────────▼──┐            │
│  │ ingestion           │──── Gamma REST (public)
│  │ strategy_runner     │
│  │ simulator           │
│  │ risk_manager        │
│  └─────────────────────┘            │
└──────────────┬──────────────────────┘
               │
          Elastic IP (stable)
```

### 7. Validation of deployment artifacts (agent-side, before committing)

- `docker build -t test-ingestion -f services/ingestion/Dockerfile .` (and equivalents for other services) succeed.
- `docker compose -f deploy/docker-compose.prod.yml config` validates against a synthetic `.env.prod`.
- `shellcheck deploy/bootstrap.sh deploy/provision.sh` clean.
- `hadolint` on each Dockerfile (best-effort; fix obvious issues).

---

## Hard constraints — the agent must not do these

- **Do NOT push to `main`.** Work on branch `validation-framework-and-aws-deploy`. Open a PR; let the operator merge.
- **Do NOT merge any PR.** Human review gate.
- **Do NOT delete any existing branch** (local or remote).
- **Do NOT call AWS APIs**, attempt to provision infrastructure, or run `deploy/provision.sh`. Only produce the artifacts.
- **Do NOT commit secrets.** Templates with placeholders only. `.env.prod` must be `.gitignore`'d; only `.env.prod.template` is tracked.
- **Do NOT modify `CLAUDE.md` or any file under** `~/.claude/` (memory is outside the repo anyway).
- **Do NOT add venue adapters** for Matchbook, Betfair, Smarkets, Kalshi, ForecastEx, or any venue other than Polymarket.
- **Do NOT re-open the "Polymarket is risky" debate.** It's been decided and documented; the operator accepts the trade-offs.
- **Do NOT use an LLM to compute any metric.** `metrics.py` / `significance.py` / `walkforward.py` / `param_sweep.py` / `regimes.py` / `promotion_gate.py` must be deterministic scripts.
- **Do NOT modify the existing live services** (ingestion, simulator, risk_manager, strategy_runner) beyond adding Dockerfiles. Their Python behaviour must not change as a side effect.

---

## Verification checklist (agent must tick all before opening PR)

- [ ] `uv run pytest services/backtest_engine/tests -v` — all green
- [ ] `uv run ruff check services/backtest_engine deploy/*.sh` — clean (shellcheck for bash)
- [ ] `uv run mypy services/backtest_engine` — clean
- [ ] `docker compose -f deploy/docker-compose.prod.yml config` — valid
- [ ] `docker build` succeeds for each of the 4 service Dockerfiles
- [ ] `uv run python -m backtest_engine.validate --strategy polymarket-yes-mean-revert --synthetic` produces a report file
- [ ] `uv run python -m backtest_engine.promotion_gate --report <path>` runs and prints PASS or FAIL with reasons (FAIL expected for this strategy)
- [ ] The generated `report.md` has a first line that says `Generated by backtest_engine.validate at <ts>. Numbers in this report are produced by deterministic scripts.`
- [ ] `.env.prod` is in `.gitignore`; `.env.prod.template` is tracked
- [ ] `deploy/README.md` has cost estimate and tear-down instructions
- [ ] No files under `~/.claude/` modified
- [ ] No changes to `CLAUDE.md`
- [ ] PR opened against `main`, not merged; description includes the verification output above and any assumptions

---

## Commit cadence (recommended, not mandatory)

Split the work into ~10 commits so the PR is reviewable:

1. `feat(validation): metrics module + tests`
2. `feat(validation): significance module + tests`
3. `feat(validation): walkforward module + tests`
4. `feat(validation): param_sweep module + tests`
5. `feat(validation): regimes module + tests`
6. `feat(validation): validate orchestrator + CLI + synthetic data generator`
7. `feat(validation): promotion_gate + strategy frontmatter thresholds`
8. `feat(validation): run the gauntlet on polymarket-yes-mean-revert + archive report`
9. `feat(deploy): Dockerfiles for all 4 Python services`
10. `feat(deploy): prod docker-compose + bootstrap + provision + README`

Each commit message body: one-line summary, bullets of what's covered, and the verification output for that module. Pre-commit hooks (ruff, mypy) must pass for each commit.

---

## If blocked

If the agent is stuck for more than 3 iterations on any single problem, it must:

1. Write a note to `docs/superpowers/plans/2026-04-24-BLOCKERS.md` describing (a) what was attempted, (b) the exact error output, (c) what the agent suspects is missing or unclear.
2. Commit whatever is complete to the branch with a WIP marker in the commit message.
3. Open the PR with `[WIP]` in the title and a link to the blockers file.
4. Exit cleanly. The operator will review and either unblock or finish manually.

Blockers acceptable for this pattern:
- Missing system dependency the agent can't install
- Ambiguity in the spec that requires operator intent
- Test failures that suggest a real bug in existing code (flag, don't patch)

Blockers NOT acceptable:
- "The strategy doesn't beat the promotion gate" — that's a SUCCESSFUL outcome of Deliverable 1.
- "Polymarket has legal issues" — irrelevant per the Context section above.
- "I'd prefer a different architecture" — follow the plan.

---

## Post-branch: what the operator does next

The operator will, on returning:
1. Review the PR diff.
2. Run `deploy/provision.sh` from their laptop with AWS CLI credentials configured.
3. SSH into the instance, populate `.env.prod`, start the stack.
4. Watch `market.data` stream length grow over 24 h.
5. Decide which strategy candidate to implement next based on (a) this validation gauntlet's verdict on the existing strategy, (b) the research agent's shortlist (separate workstream), (c) whatever else emerges.
