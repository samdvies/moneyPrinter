# algo-betting

Agentic low-latency statistical arbitrage ecosystem for Betfair Exchange and Kalshi.

Hobbyist-tier (£500–£1k stakes initially), UK-based, risk-averse with real capital, aggressive in simulation. Self-improving research flywheel with human approval gate before any live deployment.

## Local development

Requirements: Docker, uv (>=0.5), Python 3.12.

    uv sync                                  # install all workspace deps
    cp .env.example .env                     # adjust if ports collide
    docker compose up -d                     # postgres + redis
    uv run python -m scripts.migrate         # apply SQL migrations
    uv run python -m scripts.smoke           # end-to-end sanity
    uv run pytest -v                         # run the test suite

CI runs the same `smoke.py` in `.github/workflows/ci.yml` against service containers.

## Status

**Phase 1 — Scaffolding complete.** Infra, common library, migrations, CI in place. No live services. No live capital.

## Layout

```
algo-betting/
├── docs/superpowers/specs/   # Design specs (see latest for architecture)
├── wiki/                      # Obsidian vault — research notes, Karpathy foundations, papers
├── services/                  # Microservices (Python + Rust)
├── scripts/                   # Utility scripts
└── README.md
```

## Core Venues

- **Betfair Exchange** — primary liquidity source, UK-legal, 0% tax on winnings for individuals
- **Kalshi** — secondary venue, CFTC-regulated US event contracts
- **Polymarket** — deferred (UK geoblock + crypto CGT overhead)

## Principles

- Strategies are pure functions — identical API in sim and live.
- Promotion path: hypothesis → backtest → paper → **human review** → live.
- Risk limits enforced at two layers (Python risk manager + Rust execution engine).
- Agents do research; humans approve capital.

## See Also

- `docs/superpowers/specs/` — design docs
- `wiki/00-Index/` — start here for the research knowledge base
