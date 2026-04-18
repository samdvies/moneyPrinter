---
title: Hosting & Infrastructure Strategy
type: infrastructure-research
tags: [hosting, aws, hetzner, quantvps, latency, betfair, kalshi]
updated: 2026-04-18
status: initial-research
---

# Hosting & Infrastructure Strategy

## TL;DR

**AWS is fine for research, wrong for execution.** Start with Hetzner + Oracle free tier for ~£30–50/mo. Move Betfair execution to a London/Frankfurt VPS, Kalshi execution to a Chicago VPS. Add AWS later for GPU/backtest bursts using startup credits.

## The Recommended Stack — Month 0–2 (~£30/mo)

| Role | Provider | Box | Cost |
|---|---|---|---|
| Research / backtesting / ML | Oracle Cloud Always Free | 4 ARM vCPU, 24GB RAM | £0 |
| Betfair execution | Hetzner Cloud (Frankfurt or Falkenstein) | cx22, 2 vCPU / 4 GB | €4.90/mo |
| Kalshi execution | QuantVPS (Chicago) | Entry tier | ~$20/mo |
| Data store | Hetzner Postgres + Redis on same box or Supabase free | — | £0–10 |
| **Total** | | | **~£35–50/mo** |

## Exchange Reality

### Betfair

- Infra: Dublin + Equinix **LD5** / LD4 (Slough)
- Practical stream API latency: **40–100ms** from typical cloud locations. Sub-ms is a red herring for retail — stop chasing it
- Priority: consistent 50–100ms with low jitter, not raw minimums
- Sweet spot: London or Frankfurt VPS. Hetzner Frankfurt gets ~30–50ms
- **Never use residential IP** — Betfair throttles and flags bot-like patterns

### Kalshi

- Infra: Chicago, CME-adjacent
- Target: **<5ms critical for queue position**
- QuantVPS Chicago measures 1.14ms. Industry standard for algo traders
- **US geofencing risk** — UK trader routing through US VPS is a compliance grey zone. Check ToS before live trading; VPN obfuscation is not recommended

## Why Not AWS First

AWS Activate gives $1,000 credits, but:
- EC2 c7i.large in eu-west-2: ~£110/mo always-on → credits evaporate in 5.5 months
- Hidden costs: NAT egress (£0.043/GB), RDS, CloudWatch, Lambda when bot runs 300×/day
- Hetzner is 4–5× cheaper for equivalent CPU, predictable
- **AWS shines for**: one-off backtest bursts (spot instances), SageMaker for model training, S3 for 1.5TB Betfair historical data archive
- **AWS loses at**: always-on execution + small-margin trading

## Scale Path

- **Month 0–2 (£30)**: Oracle free + Hetzner cx22 + QuantVPS entry. Dev locally.
- **Month 2–6 (£80–120)**: upgrade Hetzner to CPX21 if trading. Add managed Postgres (£10–15). Apply for AWS Activate now — 2–4 week lag.
- **Month 6+ (£200–350)**: dedicated Hetzner for Betfair (€80–120, eliminates noisy neighbour). Premium QuantVPS or BeeksFX if latency matters. AWS c8g spot instances for parallel backtest runs — kill after run.

## What to Avoid

1. **Home internet** — jitter >> raw latency. ISP contention during evening peaks kills tick-to-trade.
2. **Shared residential VPS** (bargain-bin UK hosting, DO shared) — noisy neighbour effect.
3. **Wrong region** — putting Betfair bot in us-east-1 (150ms+) to save £10/mo. Bad fills cost more.
4. **AWS cost complacency** — t3.medium eu-west-2 + data transfer = £120–150/mo before you're profitable.
5. **LD4 colocation romance** — £200–400/mo. Not worth it at £5k bankroll.

## Gotchas

- **Betfair rate limits** aggressively if your connection looks bot-like → Stream API conflation (batch delays). A proper VPS avoids this; residential IP does not.
- **Kalshi ToS** may treat VPN/foreign routing as account risk. We should verify with Kalshi support before going live.
- **AWS free tier is 1-year**. Plan replacement ahead of expiry.

## Open Questions

- Exact Betfair LD5 ping from London AWS eu-west-2 `t4g.small` — worth measuring in month 2
- Kalshi compliance position on non-US residents trading via Chicago VPS — support ticket needed
- Does Oracle Cloud Always Free in London region give stable Betfair connectivity, or is latency erratic? (can test free)

## Sources

- [Betfair Stream API Latency forum thread](https://forum.developer.betfair.com/forum/sports-exchange-api/exchange-api/27059-stream-api-latency)
- [QuantVPS — Kalshi servers & latency](https://www.quantvps.com/blog/kalshi-servers-location)
- [QuantVPS — Best VPS for algo trading](https://www.quantvps.com/blog/best-vps-algorithmic-trading)
- [AWS Activate credits](https://aws.amazon.com/startups/credits)
- [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/)
