---
title: Karpathy's LLM Wiki — Pattern & Rationale
type: foundation
tags: [llm, wiki, karpathy, knowledge-base, rag, flywheel]
source: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
updated: 2026-04-18
status: foundational
related: [[00-Index/README]], [[60-Agents/Wiki-Maintenance-Agent]]
---

# Karpathy's LLM Wiki Pattern

> "The wiki is a persistent, compounding artifact."

Andrej Karpathy's gist describes a knowledge management pattern where an LLM *actively maintains* a wiki rather than an application retrieving raw documents at query time. This is the organising pattern for our research flywheel.

## Three-Layer Architecture

```
┌─────────────────┐
│  Raw Sources    │  ← immutable documents, URLs, papers, datasets
│ (papers, blogs, │
│ tickets, PDFs)  │
└────────┬────────┘
         │ ingest
         ▼
┌─────────────────┐
│    The Wiki     │  ← LLM-generated + maintained markdown
│ (this Obsidian  │
│  vault)         │
└────────┬────────┘
         │ queried by
         ▼
┌─────────────────┐
│  Schema /       │  ← CLAUDE.md — instructions and invariants
│  CLAUDE.md      │     for the maintainer-LLM
└─────────────────┘
```

- **Sources are immutable.** We preserve them verbatim (in `wiki/80-Sources/` or linked).
- **The wiki is derived.** Pages are synthesised markdown. Pages can be rewritten, split, merged. Trust only what the schema guarantees.
- **CLAUDE.md is the schema.** It defines the taxonomy, conventions, invariants, and the role of the maintainer-LLM.

## The Three Operations

### Ingestion
An agent reads a new source (paper, GitHub README, blog post, a market event, a strategy backtest result) and updates 10–15 wiki pages simultaneously. Synthesis happens once, not every query.

### Querying
Search the wiki, not raw documents. If a query produces a valuable answer that doesn't fit an existing page, **the answer becomes a new page**. The wiki grows in response to the questions asked.

### Linting
A maintenance agent periodically scans for contradictions, orphaned pages, broken links, stale content. This is background hygiene — the wiki degrades without it.

## Why This Beats Plain RAG

- **Synthesis once, not every query.** Costly inference happens during ingestion. Queries are cheap.
- **Multi-document understanding** is pre-computed. The wiki already contains the reconciled picture across sources.
- **Compound returns.** Each ingestion makes the next one cheaper and every query stronger.
- **Failure mode of plain RAG** — rediscovering the same connections on every question. Plain RAG is stateless; the wiki has memory.

## Why Knowledge Bases Usually Fail

Maintenance burden > value. Humans write a few pages, cross-linking decays, staleness creeps in, the vault gets abandoned. Karpathy's claim: **the maintenance burden is the part LLMs can eliminate.** Humans curate sources and ask questions; the agent does the bookkeeping.

## How We Apply This

| Layer | In this project |
|---|---|
| Sources | `wiki/80-Sources/` — papers, API docs, historic tick data README, raw market event logs |
| Wiki | `wiki/10-` through `wiki/70-` — synthesised pages |
| Schema | `CLAUDE.md` at project root + `wiki/00-Index/README.md` |
| Ingestion agent | See [[60-Agents/Wiki-Maintenance-Agent]] |
| Linting agent | Runs on a schedule — orphan detection, contradiction detection |
| Daily log agent | Writes to `wiki/70-Daily/YYYY-MM-DD.md` summarising research-loop activity |

## Integration with the Research Flywheel

Our **Research Orchestrator** (the Karpathy-style research agent) doesn't just output strategies — it produces findings. Every finding is an ingestion event for the wiki:

1. Orchestrator backtests a hypothesis → writes a `wiki/30-Strategies/<id>.md` page
2. Orchestrator reads a paper → updates `wiki/40-Papers/` and cross-links into `wiki/10-Foundations/`
3. Orchestrator observes a market anomaly → writes `wiki/70-Daily/YYYY-MM-DD.md` and creates a new Foundations page if the anomaly is conceptually novel

The wiki is both the agent's notebook and its memory. A later agent reads the wiki before generating a new hypothesis, so research **compounds** rather than resetting.

## Tooling

- **Obsidian** — our local IDE over the vault. Plugins:
  - Smart Connections (semantic search)
  - Obsidian MCP Server ([cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)) — programmatic note CRUD, critical for agent autonomy
  - Text Generator or LLM Tagger (auto-taxonomy)

## Source

Original gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

Fetched summary (2026-04-18):

> "Unlike traditional RAG systems, this approach avoids rediscovering knowledge from scratch on every question. Instead, synthesis happens once during ingestion, enabling more sophisticated queries requiring multi-document understanding."

> "The pattern addresses why knowledge bases fail: maintenance burden outpaces value. By automating bookkeeping, LLMs remove the tedious part, allowing humans to focus on curation and critical thinking."

## Related

- [[00-Index/README]] — wiki entry point
- [[60-Agents/Wiki-Maintenance-Agent]] — the maintainer
- [[10-Foundations/Karpathy-Software-2]] — related Karpathy foundation (to be written)
