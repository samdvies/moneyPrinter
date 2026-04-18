---
title: Canonical Reading List — Quant Sports Betting
type: reading-list
tags: [papers, books, practitioners, kelly, clv]
updated: 2026-04-18
status: initial-research
---

# Canonical Reading List

Curated by research agent. Prioritised for Betfair + Kalshi focus.

## Top 5 Papers

1. **Modified Kelly Criteria** (Chu, Wu, Swartz, Simon Fraser) — Kelly when win probability is unknown; foundational for our bankroll module. [PDF](https://www.sfu.ca/~tswartz/papers/kelly.pdf)
2. **Information, Prices and Efficiency in an Online Betting Market** (University of Reading) — empirical market efficiency on betting exchanges, directly applicable to Betfair. [PDF](https://www.reading.ac.uk/web/files/economics/emdp201910.pdf)
3. **Predicting Goal Probabilities with Improved xG Models Using Event Sequences** (PMC/NIH) — state-of-the-art xG, random forests, essential for football. [Link](https://pmc.ncbi.nlm.nih.gov/articles/PMC11524524/)
4. **Assessing the Predictability of Racing Performance of Thoroughbreds** (Oda et al., 2024) — mixed-effects models + pedigree data for horse racing. [Link](https://onlinelibrary.wiley.com/doi/10.1111/jbg.12822)
5. **Informational Efficiency and Behaviour Within In-Play Prediction Markets** (University of Reading) — in-play market dynamics, in-play arbitrage. [PDF](https://www.reading.ac.uk/web/files/economics/emdp201920.pdf)

## Top Books & Longform

- **Calculated Bets** — Steven Skiena. Practical quant betting reference text.
- **Squares & Sharps, Suckers & Sharks** — Joseph Buchdahl. CLV, edge measurement, psychology.
- **The Kelly Criterion** — Ed Thorp. Seminal. [Williams PDF](https://web.williams.edu/Mathematics/sjmiller/public_html/341/handouts/Thorpe_KellyCriterion2007.pdf)
- **[Pinnacle Betting Resources](https://www.pinnacle.com/betting-resources/)** — free academic-grade articles on CLV and sharp bookmaker operations.
- **[Peter Webb / Bet Angel Academy](https://www.peterwebb.com/)** — free resources on Betfair exchange trading, in-play, latency.

## Practitioners to Follow

- **Tony Bloom** — Starlizard, one of the UK's most successful private syndicates. Mostly private; rare profile pieces.
- **Matthew Benham** — Smartodds / Brentford FC owner. Bayesian methods, data-driven.
- **Joseph Buchdahl** — [Football-Data.co.uk](https://www.football-data.co.uk/). Writes extensively on CLV, bankroll, model validation.
- **Peter Webb** — Bet Angel, Betfair exchange pioneer.
- **Pinnacle** — industry benchmark for sharp pricing.

## Core Concepts

1. **Closing Line Value (CLV)** — primary performance metric. Beat closing line by 2%+ over 100+ bets ⇒ long-term profit. **Track this from day one.**
2. **Kelly Criterion / Fractional Kelly** — half-Kelly is industry standard. Full Kelly has unacceptable drawdown variance.
3. **Sharp vs Soft Books** — Pinnacle is the sharp benchmark. Betfair Exchange is sharper than soft books. Exploit soft-book lag.
4. **Line Shopping** — use Betfair + Pinnacle as the floor; hunt positive CLV at slower soft books.
5. **In-Play Latency Advantage** — 8–10ms latency gaps in live markets. Courtsiding / real-time video-vs-feed exploits exist and are well documented.
6. **Asian Handicaps** — eliminate draw outcomes; quarter-goal splits.
7. **Market Microstructure** — Betfair's P2P model exposes true probability faster than traditional books; bid-ask spread is edge signal.

## Betfair-Specific Advantage

As a UK hobbyist, Betfair lets us **lay bets** to exploit overpriced soft-book markets — a structural option not available when trading Kalshi (quote-driven, lower volume, no lay/back duality).

## Recommended Reading Order

1. Skiena — Calculated Bets (warm-up, mindset)
2. Buchdahl — Squares & Sharps (CLV, edge measurement)
3. Thorp — Kelly paper (bankroll math)
4. Reading in-play paper (live market dynamics)
5. xG paper (if football) / Oda paper (if horse racing)
