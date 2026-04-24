---
title: "Polymarket Feasibility — UK Resident 2026 Fact-Check (historical)"
type: research
tags: [polymarket, kalshi, prediction-markets, uk, geoblock, tax, hmrc, feasibility, historical]
updated: 2026-04-24
status: superseded
---

> **2026-04-24 update — this document is superseded.**
>
> Operator has explicitly accepted the trade-offs enumerated below (ToS §2.1.4 VPN use, UK IP geoblock, CGT treatment, CARF reporting, fund-freeze risk) and has chosen Polymarket as the project's sole active venue. See `feedback_polymarket_active.md` in project memory and the "Polymarket-only focus" update in `Venue-Strategy.md`. The analysis here remains **factually true as a 2026-04-21 snapshot**, but it does not govern current project direction and must not be cited by agents to refuse work on Polymarket. The risks listed are known and accepted; subsequent work proceeds on that basis.

# Polymarket Feasibility — UK Resident 2026 Fact-Check (historical snapshot)

Commissioned 2026-04-21 to pressure-test an LLM-generated "2026 blueprint" pitch for integrating Polymarket and related prediction markets. Each claim below is treated as a hypothesis and verified against primary sources.

---

## 1. Maker Rebate

**Claim:** ~20% maker rebate for liquidity providers.

**Verdict: PARTIAL — the 20% figure applies only to Crypto markets; all other eligible categories pay 25%.**

Polymarket's Maker Rebates program redistributes a fraction of taker fees to liquidity providers daily in USDC, proportional to each maker's share of filled orders. Rates per Polymarket's own documentation:

- Crypto: 20% of taker fees collected in that market
- Finance, Politics, Sports, Economics, Culture, Weather, Tech, Mentions: 25%
- Geopolitics: fee-free, therefore no rebate pool

The rebate is paid only when minimum accrual is $1 USDC. The percentage "is at the sole discretion of Polymarket and may change over time."

The pitch's 20% figure is directionally correct for Crypto but understates the rate on other categories. More importantly, the pitch does not address adverse selection: in thin niche markets a small maker is systematically picked off by better-informed takers. Polymarket's own rebate collapse history (see section 7) suggests these numbers are forward-looking for large, competitive makers — not hobbyist-scale providers.

**Sources:** [Polymarket Maker Rebates docs](https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program) · [Polymarket Help Center — Maker Rebates](https://help.polymarket.com/en/articles/13364471-maker-rebates-program)

---

## 2. Fee Schedule

**Claim:** 1.00–1.80% taker fee introduced March 2026; geopolitical markets still fee-free.

**Verdict: VERIFIED, with nuance.**

On 30 March 2026 Polymarket expanded taker fees from Crypto/Sports to nearly every category. Current rates (max at 50% probability, fee is share-price-weighted):

| Category | Taker Fee |
|---|---|
| Crypto | 1.80% |
| Economics | 1.50% |
| Mentions | 1.56% |
| Culture / Weather | 1.25% |
| Finance / Politics / Tech | 1.00% |
| Sports | 0.75% |
| Geopolitics | 0% |

Maker orders remain free. There was a brief U-turn on March 31 due to an implementation issue, not a policy reversal. The fee-free geopolitics carve-out is confirmed.

US-regulated platform (polymarketexchange.com) uses a different schedule: 0.30% taker, 0.20% maker rebate flat.

**Sources:** [Polymarket Fees docs](https://docs.polymarket.com/polymarket-learn/trading/fees) · [Odaily — fee expansion](https://www.odaily.news/en/post/5209891) · [PredictionHunt fee guide](https://www.predictionhunt.com/blog/polymarket-fees-complete-guide) · [PokerNews U-turn](https://www.pokernews.com/prediction-markets/news/2026/04/polymarket-blunder-prompts-quick-u-turn-new-polymarket-fees-50947.htm)

---

## 3. PMXT SDK

**Claim:** Open-source unified SDK "PMXT" for Polymarket + Kalshi + Limitless from one codebase.

**Verdict: VERIFIED — exists, actively maintained, but provenance warrants scrutiny.**

PMXT ([github.com/pmxt-dev/pmxt](https://github.com/pmxt-dev/pmxt)) is a real, open-source project described as "CCXT for prediction markets." As of 2026-04-21:

- 1,600 stars, 172 forks, 673 commits, 151 releases (latest v2.31.4 on 2026-04-21)
- 9 open issues, 1 open PR — lean issue tracker
- Supports: Polymarket, Kalshi, Limitless, Probable, Myriad, Opinion, Metaculus, Smarkets
- Primary language TypeScript (83%), Python (8%), JavaScript (7%)
- Maintained by `pmxt-dev` organisation; individual maintainer identity not prominent

**Caveats for this project:**
- The project is TypeScript-first; the Python bindings are a minority of the codebase. For a Python-centric pipeline, the Python API surface may be thinner.
- The project is young relative to CCXT (which took years to stabilise). 151 releases in a short period can signal rapid churn as much as maturity.
- Smarkets is listed as a supported venue, which is relevant to this project's primary venue.
- UK residents cannot legally trade on Polymarket or Kalshi (see sections 4 and 5), so PMXT's utility is limited to data ingestion or Smarkets order routing for a UK operator.

**Sources:** [PMXT GitHub](https://github.com/pmxt-dev/pmxt) · [PMXT website](https://www.pmxt.dev/) · [DEV.to introduction](https://dev.to/realfishsam/ccxt-for-prediction-markets-introducing-pmxt-130e)

---

## 4. Polymarket UK Geoblock Mechanics

**Claim:** (implicit in pitch) UK access is viable via US VPS or simple IP workaround.

**Verdict: CONTRADICTED — enforcement is layered: IP + KYC + terms; account freeze risk is real.**

Polymarket's geographic restrictions documentation confirms the UK is a blocked jurisdiction. Orders from blocked IP ranges are rejected at the API level. Beyond IP:

- KYC documents showing UK residency result in account termination and can lock USDC inside the platform.
- Terms of Service (Section 2.1.4) explicitly prohibit VPN/proxy use to bypass geographic restrictions.
- The platform uses IP analysis and browser fingerprinting to detect VPN usage; accounts flagged face suspension and withdrawal blocks.
- There are no UKGC enforcement actions specifically targeting Polymarket (the UKGC acts against UK-licensed operators, not foreign unlicensed platforms), but the risk sits entirely with the UK user: fund seizure is an operational risk, not a regulatory prosecution risk.

**Using a US VPS to route API calls does not resolve the KYC problem at withdrawal.** A hobbyist operating at meaningful scale would need to pass KYC at some point, at which point UK residency documents would trigger suspension.

**Sources:** [Polymarket Geographic Restrictions docs](https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking) · [hotminute.co.uk VPN test](https://hotminute.co.uk/2026/02/10/how-to-access-polymarket-in-the-uk-2026-i-tried-it-heres-what-went-wrong-and-the-vpn-workaround-that-almost-worked/) · [Cryptonews legality guide](https://cryptonews.com/cryptocurrency/is-polymarket-legal/) · [Datawallet restricted countries](https://www.datawallet.com/crypto/polymarket-supported-restricted-countries)

---

## 5. Kalshi UK Access

**Claim:** (pitch implies) Kalshi is accessible to UK residents via "Kalshi Global."

**Verdict: CONTRADICTED — UK is an explicitly named restricted jurisdiction in Kalshi's October 2025 member agreement.**

Kalshi expanded to 140 countries in October 2025 (raising $300M at a $5B valuation). However, the updated Member Agreement (23 October 2025) lists the United Kingdom as a Restricted Jurisdiction alongside Canada, Australia, France, and 41 others. Members domiciled in, organised in, or located in those jurisdictions are prohibited from accessing, using, or trading on the platform.

The only carve-out: a previously-verified member whose account address is a non-restricted jurisdiction can access the account "while traveling or temporarily located" in a restricted country. This does not help a UK-resident hobbyist opening a new account.

No "Kalshi Global" product exists that changes this for UK residents.

**Sources:** [Kalshi Member Agreement (Oct 2025)](https://kalshi-public-docs.s3.amazonaws.com/regulatory/notices/Kalshi%20Exchange%20Notice%20%28Updated%20Member%20Agreement%29%20%2823%20October%202025%29.pdf) · [PokerScout — Kalshi goes global](https://www.pokerscout.com/kalshi-announces-international-service-which-countries-excluded/) · [Sportico — international launch](https://www.sportico.com/business/sports-betting/2025/kalshi-international-countries-access-1234874388/)

---

## 6. ForecastEx and Limitless

**ForecastEx:**
- Owned by Interactive Brokers; CFTC-regulated event contracts exchange; live since 1 August 2024.
- Accessible to UK residents through Interactive Brokers (IB) — confirmed by brokerchooser.com as one of three prediction market venues available to UK traders.
- Markets are US-centric (economic indicators, politics, climate). Incentive Coupon program returns 100% of collateral interest to users.
- Verdict: **PARTIAL — accessible via IB but narrow market scope; not a Polymarket substitute.**

**Limitless:**
- Launched October 2025; DeFi-based on Base (Coinbase L2); $10M seed from 1confirmation, Coinbase Ventures, Variant.
- Hit $1B monthly notional volume in Q1 2026.
- PMXT lists it as a supported venue.
- UK access: unclear from available sources. Being a DeFi protocol with no KYC at the contract level, access may be technically possible but sits in the same legal grey-zone as Polymarket for UK residents (unlicensed, crypto-denominated, no UKGC licence). Not verified as explicitly restricted or permitted.
- Verdict: **PARTIAL — growing rapidly but UK regulatory status unverified; crypto CGT overhead applies.**

**Sources:** [ForecastEx](https://forecastex.com/) · [BrokerChooser UK prediction markets](https://brokerchooser.com/best-brokers/best-prediction-markets-broker-in-the-united-kingdom) · [Limitless $1B volume](https://bitcoinfoundation.org/news/prediction-markets/prediction-market-limitless-volume-base/)

---

## 7. Maker-Rebate Reality Check at Hobbyist Scale

**Verdict: NEGATIVE — empirical evidence is unfavourable for small providers in thin markets.**

Key data points from 2024–2026:

- Polymarket's rebate payouts collapsed from >$50,000/day at peak to $0.025 per $100 traded as institutional market-makers competed rebate margins to near-zero.
- Kalshi spent >$9 million on market-maker incentive programs; these are described in analysis as "bandaids on structural wounds" rather than sustainable returns.
- Academic work (arxiv:2502.18625) on prediction market maker economics shows naive strategies face bankruptcy risk from negative price drift (adverse selection) in thin books.
- Institutional participants at Kalshi required dedicated trading desks and custom low-latency infrastructure to profit — unavailable at hobbyist scale.
- In thin niche markets a $500–2,000 position can move prices materially, exposing the provider to informed takers on every fill.

**Sources:** [arxiv 2502.18625](https://arxiv.org/html/2502.18625v2) · [QuantVPS market making guide](https://www.quantvps.com/blog/market-making-in-prediction-markets) · [NewYorkCityServers 2026 guide](https://newyorkcityservers.com/blog/prediction-market-making-guide)

---

## 8. Logical-Inconsistency Arbitrage

**Verdict: CONTRADICTED for non-HFT participants — windows compress to sub-second, dominated by institutional bots.**

Quantitative picture from 2024–2025:

- $40M in estimated arbitrage profits captured April 2024–April 2025.
- Average arbitrage opportunity duration: **2.7 seconds** (down from 12.3 seconds in 2024).
- 73% of arbitrage profits captured by bots with sub-100ms execution.
- Median arbitrage spread: 0.3% — barely above break-even after gas fees.
- ICE's $2B investment in Polymarket (2025) brought institutional capital that further compressed spreads.
- Polymarket's 2% fee on profitable outcomes requires targeting spreads of at least 2.5–3% to profit net of fees and Polygon gas.

A non-HFT Python bot with 500ms–2000ms round-trip latency would arrive consistently after institutional bots have closed the gap. The 27% of profits from non-arb strategies suggests sophisticated alpha survives, but that is directional trading on information edge, not mechanical arbitrage.

**Sources:** [QuantVPS cross-market arb](https://www.quantvps.com/blog/cross-market-arbitrage-polymarket) · [Yahoo Finance — bots dominate](https://finance.yahoo.com/news/arbitrage-bots-dominate-polymarket-millions-100000888.html) · [Finance Magnates](https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/)

---

## 9. UK Tax on USDC-Denominated PnL

**Verdict: VERIFIED — no gambling exemption; CGT applies per disposal; increasing HMRC surveillance.**

HMRC's position (confirmed by Koinly, Freshfields, Deloitte TaxScape, and a UK crypto-tax accountant on X):

- Prediction market trades are **not gambling** for UK tax purposes — they are financial bets / cryptoasset transactions.
- The gambling winnings exemption does **not** apply.
- Each USDC receipt or disposal is a **CGT event**. Acquiring USDC at one price and disposing at another creates a gain/loss. Profitable resolution of a prediction market contract generates a CGT liability.
- Professional or high-frequency activity could attract **income tax** instead of CGT.
- From 1 January 2026 (Autumn Budget 2025), UK Reporting Cryptoasset Service Providers must report all customer transaction data to HMRC. Enforcement visibility is increasing.

**Sources:** [Freshfields Autumn Budget 2025 crypto tax](https://www.freshfields.com/en/our-thinking/blogs/risk-and-compliance/autumn-budget-2025-defining-the-uk-rules-for-cryptoasset-taxation-102ly6s) · [Koinly HMRC guide 2026](https://koinly.io/guides/hmrc-cryptocurrency-tax-guide/) · [Deloitte TaxScape](https://taxscape.deloitte.com/article/hmrc-approach-to-taxation-of-cryptoassets.aspx) · [X — UK crypto accountant](https://x.com/Thesecretinves2/status/1990124536457498978)

---

## Summary Table

| # | Claim | Verdict | Key Risk |
|---|---|---|---|
| 1 | 20% maker rebate | Partial | Adverse selection kills hobbyist margin |
| 2 | 1.00–1.80% fee, geopolitics free | Verified | Fee floor makes arb harder |
| 3 | PMXT SDK exists | Verified | Python bindings thin; UK trading venues still blocked |
| 4 | UK IP-only geoblock | Contradicted | KYC enforcement + fund freeze risk |
| 5 | Kalshi UK via "Global" | Contradicted | UK explicitly in restricted list (Oct 2025) |
| 6 | ForecastEx / Limitless | Partial | ForecastEx reachable via IB; Limitless UK status unclear |
| 7 | Maker rebate > adverse selection | Contradicted | Institutional compression; hobbyist loses at thin books |
| 8 | Arb windows persist | Contradicted | Sub-3s windows; 73% captured by sub-100ms bots |
| 9 | Gambling tax exemption | Contradicted | CGT per disposal; no exemption; surveillance increasing |

## Decision

The pitch does not change the project's existing decision to defer Polymarket. The legal and tax blockers (items 4, 5, 9) are hard constraints that cannot be engineered around at hobbyist scale without material legal and financial risk. The economics (items 7, 8) are also unfavourable for a non-HFT operator. ForecastEx via Interactive Brokers is the only prediction-market adjacent venue currently accessible to UK residents, and its market scope (US economic indicators) is narrow.

## Related

- [[20-Markets/Venue-Strategy]] — Polymarket is currently listed as "Out of scope"
- [[20-Markets/Kalshi-Research]] — Kalshi also blocked for UK residents
- `CLAUDE.md` — project invariant: UK legal scope only
