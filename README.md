# algo-betting

Agentic low-latency statistical arbitrage ecosystem for Betfair Exchange and Kalshi.

Hobbyist-tier (£500–£1k stakes initially), UK-based, risk-averse with real capital, aggressive in simulation. Self-improving research flywheel with human approval gate before any live deployment.

## Status

**Phase 0 — Research & scaffolding.** No live services. No live capital.

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
