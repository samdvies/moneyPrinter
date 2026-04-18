---
title: Wiki Maintenance Agent
type: agent-spec
tags: [agent, wiki, maintenance, karpathy]
updated: 2026-04-18
status: draft-spec
---

# Wiki Maintenance Agent — Spec

The agent that implements Karpathy's wiki pattern for this project. Runs in three modes.

## Mode 1 — Ingest

**Trigger:** a new source lands in `wiki/80-Sources/` or a research agent emits a finding to the `research.events` stream.

**Behaviour:**
1. Read the source fully.
2. Identify which wiki pages (across all folders) are semantically touched by the source.
3. Update **all** touched pages, not just one. Cross-link aggressively.
4. If no page fits, create a new one under the appropriate prefix.
5. Update the relevant index / map-of-content in `00-Index/`.
6. Append a one-paragraph summary to today's `70-Daily/YYYY-MM-DD.md`.
7. Never edit sources in `80-Sources/`.

## Mode 2 — Query

**Trigger:** another agent (e.g. Research Orchestrator) asks a question.

**Behaviour:**
1. Search the wiki (semantic + keyword) first. Do **not** go to raw sources unless the wiki is silent.
2. If the answer is valuable and doesn't correspond to an existing page, **file the answer as a new page**. The wiki grows in response to the questions asked.
3. Return the answer with citations to the wiki pages used.

## Mode 3 — Lint

**Trigger:** scheduled (nightly).

**Behaviour:**
1. Scan for broken `[[wikilinks]]`.
2. Flag orphaned pages (no backlinks, not in an index).
3. Flag stale pages (`updated` older than N days for `status: living` pages).
4. Detect contradictions between pages via LLM comparison on overlapping tags.
5. Write a report to `70-Daily/YYYY-MM-DD.md` under a "Lint" section.
6. Only fix trivially mechanical issues (broken links, missing frontmatter). Larger edits go to a queue for human review.

## Invariants

- **Sources are immutable.** Never edit `80-Sources/`.
- **Frontmatter is mandatory.** Every page has `title`, `type`, `tags`, `updated`, `status`.
- **No silent rewrites of approved strategies.** Pages under `30-Strategies/` with `status: live` or `status: awaiting-approval` are read-only for this agent; changes require human approval.
- **Dated logs only for today.** Historical daily logs are read-only.
- **Prefer additions over deletions.** When in doubt, write a new page linking to the old one rather than rewriting.

## Implementation

- Host: the Research Orchestrator service (Python).
- Storage I/O: MCP via [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) if Obsidian is open; otherwise direct file I/O.
- Model: Claude for ingestion (quality), Haiku for linting (cost).

## Open Questions

- Do we want a separate "reviewer" agent to validate ingestion edits before they land, or is post-hoc linting enough?
- How do we version-control the wiki? Git commit per ingestion? Daily snapshot?
