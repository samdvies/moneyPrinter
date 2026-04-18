---
title: Kalshi & Prediction Market Research
type: market-research
tags: [kalshi, polymarket, prediction-markets, arbitrage]
updated: 2026-04-18
status: initial-research
---

# Kalshi & Prediction Market Research

Initial research dump from parallel discovery pass. Source: Haiku research agent, 2026-04-18.

## Reusable SDKs & API Clients

| Library | URL | Notes |
|---|---|---|
| Kalshi Python SDK (official) | https://docs.kalshi.com/sdks/python/quickstart | Sync + async flavours (`kalshi_python_sync`, `kalshi_python_async`) |
| Polymarket py-clob-client | https://github.com/Polymarket/py-clob-client | Official CLOB client — keep for later Polymarket phase |
| pykalshi | https://github.com/arshka/pykalshi | Community client, WebSocket streaming, pandas |
| aiokalshi | https://github.com/the-odds-company/aiokalshi | Asyncio-native, typed query params |

## Production Bots to Study

- **[ImMike/polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage)** — cross-platform scanner, 5,000+ markets, text-similarity matching, bundle arbitrage, real+sim modes, fee-aware. **High priority to study.**
- **[OctagonAI/kalshi-deep-trading-bot](https://github.com/OctagonAI/kalshi-trading-bot-cli)** — fundamental research → probability estimation → Kelly sizing + 5-gate risk engine. **Architecture reference for our research loop.**
- **[ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot)** — multi-agent decision making, portfolio optimization, Grok-4 integration. **Closest to our agentic vision.**
- [dev-protocol/polymarket-arbitrage-trade-bot](https://github.com/dev-protocol/polymarket-arbitrage-trade-bot) — dump-hedge strategy, stop-loss hedging
- [Trum3it/polymarket-arbitrage-bot](https://github.com/Trum3it/polymarket-arbitrage-bot) — Rust-based, BTC/ETH 15-min markets

## Must-Read Papers

- **Clinton & Huang — 2024 Election Prediction Markets**: https://ideas.repec.org/p/osf/socarx/d5yx2_v1.html — Kalshi 78% accuracy vs Polymarket 67%; persistent arbitrage windows; daily negative autocorrelation
- **Rasooly & Rozzi — Market Manipulability**: https://arxiv.org/html/2503.03312v1 — do prices reflect fundamentals or persist under noise?

## Practitioner Resources

- Trevor Lasn on cross-market arb: https://www.trevorlasn.com/blog/how-prediction-market-polymarket-kalshi-arbitrage-works
- TokenMetrics 7 strategies: https://tokenmetrics.com/blog/7-prediction-market-strategies/
- Robin Hanson (invented LMSR, foundational market design): https://scholar.google.com/citations?user=PjIP_WcAAAAJ

## Key Insights

1. **Settlement risk is structural** — Clinton & Huang: identical contracts diverge across venues due to different settlement criteria (e.g. Kalshi "24hr shutdown" vs Polymarket "OPM announcement"). Any cross-venue arb must model settlement semantics, not just price.
2. **Combined fee drag** — Kalshi 3% + Polymarket 2% = 5% combined floor. Cross-venue arbs need >5% spreads to clear.
3. **Windows are seconds, not minutes** — manual trading non-viable. ~0.51% of participants are consistently profitable.
4. **Information edges persist** — county-level election data led major networks by 20–45 min in 2024. Fast data ingestion > fast execution for some strategies.
5. **Polymarket CLOB is maturing** — Wintermute and other professional MMs now provide deep liquidity. Taker-maker fee differentiation (Oct 2025). Implication: pure Polymarket arb is harder than it was.

## Building Blocks to Reuse First

1. Kalshi official SDK → base client for our ingestion service
2. OctagonAI's 5-gate risk engine → reference for our risk manager design
3. ImMike's text-similarity market matching → reference for cross-venue pairing logic
4. ryanfrigo's multi-agent structure → reference for our research loop

## Open Questions

- Does Kalshi's API support full order-book depth streaming, or only top-of-book?
- What's the rate limit on the Kalshi API in 2026?
- Does our UK tax position change if we trade Kalshi? (Kalshi is CFTC-regulated, fiat-denominated — likely still gambling-exempt, but needs verification)
