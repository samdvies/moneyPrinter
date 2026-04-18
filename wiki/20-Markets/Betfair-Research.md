---
title: Betfair Exchange Research
type: market-research
tags: [betfair, horse-racing, football, oss-survey]
updated: 2026-04-18
status: initial-research
---

# Betfair Exchange Research

Initial research dump from parallel discovery pass. Source: Haiku research agent, 2026-04-18.

## Core Libraries — Foundation Layer

### Tier 1 — must use

- **[betfairlightweight](https://github.com/betcode-org/betfair)** — 480★, actively maintained (last update Oct 2025), 30+ contributors. De facto Python API wrapper: streaming, market data, order execution, account. Python 3.9–3.14. **This is our ingestion + execution base.**
- **[flumine](https://github.com/betcode-org/flumine)** — 229★, event-driven framework from the same author. Multi-venue (Betfair, Betdaq, Betconnect), simulation, paper trading, risk controls, modular strategy design. **This is our reference architecture for the strategy-execution layer.** May not be a direct dependency since we're building microservices, but its patterns are worth adopting.

## Active Bots to Study

- **[BetfairAiTrading](https://github.com/StefanBelo/BetfairAiTrading)** — 24★, last update Feb 2026. 120+ AI prompts, horse racing + football + tennis, R1–R6 strategy evolution, multi-language. Integrates OpenAI, DeepSeek, Claude, Gemini, Grok. **Closest analogue to our agentic vision — study the prompt taxonomy.**
- **[betfair-horse-racing](https://github.com/dickreuter/betfair-horse-racing)** — pre-race scalping + neural network value betting, Flask P&L dashboard. Dated (2018 training data) — study architecture, don't run it.
- **[betfair-python-trading-bot-automation](https://github.com/michaelvrxoj/betfair-python-trading-bot-automation)** — Green Book scalping strategy, Stream API integration, pre-race horse racing.

## Data & Modelling Resources

- **[Betfair Data Scientists Hub](https://betfair-datascientists.github.io/)** — Official Betfair resource. 1.5TB raw market data, tutorials (AFL, EPL, Greyhounds, NRL, Super Rugby), backtesting guides.
- **[predictive-models](https://github.com/betfair-datascientists/predictive-models)** — deployed Greyhound + EPL models, Brownlow Medal, World Cup tutorials. **First place to look for sport-specific modelling templates.**

## Reference-Only

- [mcobzarenco/betfair-trading](https://github.com/mcobzarenco/betfair-trading) — 15★, dormant. Stat arb templates, backtest.py, paper-trade.py. Read the files, don't depend on it.
- [BowTiedBettor/BetfairBot](https://github.com/BowTiedBettor/BetfairBot) — flumine-based Beacons pricing strategy. 5★, proof-of-concept.

## Reuse Plan

1. **Mandatory dep** — `betfairlightweight` as the Betfair API client in the Ingestion and Execution services
2. **Pattern reference** — `flumine`'s event-driven architecture, simulation harness, and risk controls
3. **Prompt design reference** — `BetfairAiTrading`'s R1–R6 taxonomy when we write strategy-generating prompts
4. **Data source** — Betfair Data Scientists' 1.5TB historical archive for backtests
5. **Modelling templates** — Betfair Data Scientists' predictive-models repo for sport-specific feature engineering

## Open Questions

- Does `betfairlightweight` still support the 2026 stream API protocol, or are there breaking changes?
- `flumine` is single-author. If we depend on it heavily, do we fork/vendor?
- What's the current Betfair app-key application process and live-environment approval turnaround?
