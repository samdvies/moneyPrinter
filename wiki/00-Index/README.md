---
title: Wiki Index — algo-betting
type: index
tags: [index, home]
updated: 2026-04-18
status: living
---

# algo-betting — Research Wiki

Persistent knowledge base for our agentic betting ecosystem. Organised per Karpathy's [[10-Foundations/Karpathy-LLM-Wiki|LLM wiki pattern]]. Agents ingest sources here, agents query here, humans curate here.

## Map of Content

### 10 — Foundations
Conceptual bedrock. LLM basics, market microstructure, statistical primitives.
- [[10-Foundations/Karpathy-LLM-Wiki]] — the wiki pattern we follow
- *(to be written: Software-2, Micrograd-intuitions, nanoGPT-notes, CLV, Kelly, market-microstructure)*

### 20 — Markets
Venue-specific research: APIs, microstructure, quirks, costs.
- [[20-Markets/Betfair-Research]] — OSS survey, reuse plan
- [[20-Markets/Kalshi-Research]] — OSS survey, cross-venue insights

### 30 — Strategies
Hypotheses, backtest results, paper-trading performance, approval status. One page per strategy. Written by the Research Orchestrator.

### 40 — Papers
Academic literature, reading list, paper summaries.
- [[40-Papers/Reading-List]] — curated canon

### 50 — Infrastructure
Hosting, latency, deployment, costs.
- [[50-Infrastructure/Hosting-Strategy]] — recommended stack & scale path

### 60 — Agents
Prompts, specs, and behaviour definitions for the agents in our research loop.
- *(to be written: Research-Orchestrator, Wiki-Maintenance-Agent, Linting-Agent)*

### 70 — Daily
Daily log entries written by the research loop. `YYYY-MM-DD.md` per day.

### 80 — Sources
Immutable raw documents (PDFs, URL captures). Referenced by synthesised pages above.

### 90 — Templates
Note templates for agent-written pages.
- *(to be written: strategy-template, daily-log-template, paper-summary-template)*

## Core Conventions

- **Frontmatter is mandatory** on every note: `title`, `type`, `tags`, `updated`, `status`.
- **Backlinks over folders.** Use `[[wikilinks]]` liberally. Folders provide coarse structure; the graph is where meaning lives.
- **Numeric prefixes** order folders. Pages within a folder have no prefix.
- **Agents write dated logs** in `70-Daily/`. They do not edit arbitrary historical pages without explicit tasks.
- **Sources are never edited.** Only derived pages evolve.

## Current Status

Phase 0 — research & scaffolding. No live services, no live capital. The wiki is being seeded from the initial discovery pass.

## For Agents

If you are a research agent arriving fresh:
1. Read `CLAUDE.md` at project root for invariants.
2. Read this index.
3. Read [[10-Foundations/Karpathy-LLM-Wiki]] for the maintenance pattern.
4. When you ingest a new source, update **all** semantically-related pages, not just one. Cross-link aggressively.
5. When you propose a new strategy, write a new page under `30-Strategies/` using the template.
6. Append one paragraph to today's `70-Daily/YYYY-MM-DD.md` summarising what you did.
