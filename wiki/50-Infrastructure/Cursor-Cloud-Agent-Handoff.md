---
title: Cursor Cloud / Long-Running Agent Handoff
type: infrastructure-research
tags: [cursor, agents, handoff, automation, background-agent, cloud-agent]
updated: 2026-04-19
status: initial-research
---

# Cursor Cloud / Long-Running Agent Handoff

## TL;DR

Cursor now offers autonomous agents that run on cloud VMs for hours without supervision. For this project, the pattern is: commit the current state → push to a feature branch → hand the agent a self-contained brief pointing at `CLAUDE.md` + the relevant Phase 2 plan → it spins up a VM, implements, runs tests, opens a PR → you review the PR and merge. The primary safety gate is **architectural**: the Execution Engine doesn't exist yet, so the agent cannot place live orders even if it tried.

## Three related products

### Background Agents (GA, short asynchronous tasks)

- Trigger: `Ctrl+E` inside Cursor.
- Runs on an isolated Ubuntu VM with internet and package-install rights.
- Works on a separate git branch; pushes back on completion.
- Good for single-PR tasks measured in minutes to a couple of hours.
- Docs: [docs.cursor.com/en/background-agent](https://docs.cursor.com/en/background-agent), [cursor.com/docs/agent/agents-window](https://cursor.com/docs/agent/agents-window)

### Long-Running Agents (Feb 12 2026, Ultra/Teams/Enterprise)

- Designed to run **25–52+ hours** autonomously.
- Planner/Worker pipeline: planners continuously explore the codebase and create tasks; workers grind tasks end-to-end.
- Propose a plan up front and wait for approval before implementing (so you are not surprised 20 hours in).
- Source: [cursor.com/blog/scaling-agents](https://cursor.com/blog/scaling-agents), [cursor.com/blog/long-running-agents](https://cursor.com/blog/long-running-agents)

### Cloud Agents with Computer Use (Feb 24 2026)

- Agents actually **run** the software they build — interact with a web UI, capture video/screenshots/logs, attach to the PR.
- Useful when the feature has an observable UI. Less relevant for our current server-side Phase 2 work.

For a "leave it for a few hours" handoff on Phase 2 ingestion, **Long-Running Agent** is the right pick if you have Ultra/Teams. Otherwise a plain Background Agent scoped to a single sub-task is the fallback.

## Prerequisites

1. **GitHub connection** with read-write on `algo-betting` (and any submodules).
2. **Usage-based billing enabled** — top up with at least $20 before a multi-hour session. Set a spend cap.
3. **Green `main`** — pre-commit hooks + CI passing. The agent follows the same gates.
4. **`.cursor/environment.json`** at repo root so the VM bootstraps correctly.

## `.cursor/environment.json` template

Drop this at the repo root. Key bits: Python 3.12, uv, Docker CLI (to bring up the local stack for tests).

```json
{
  "install": "curl -LsSf https://astral.sh/uv/install.sh | sh && uv sync --all-packages",
  "start": "docker compose up -d && ./scripts/wait-for-health.sh",
  "terminals": [
    { "name": "tests", "command": "uv run pytest -q" }
  ]
}
```

If you need a custom base image (e.g. Python 3.12 pre-installed, Docker-in-Docker), add a `build.dockerfile` field pointing at `.cursor/Dockerfile`. Keep it minimal — Cursor's default Ubuntu image already has Node, Python, and most CLIs.

## Setup steps

1. Install or open Cursor.
2. Open the repo.
3. Settings → enable Background Agents. Approve the GitHub repo access prompt.
4. Commit `.cursor/environment.json` to `main`.
5. Top up credits; set a spend cap (Settings → Usage).
6. `Ctrl+E` → paste the brief in §"Prompt to hand it" below → pick Long-Running mode if available.
7. Walk away. Come back to a PR.

## Prompt to hand it (Phase 2 target)

Copy-paste this into the agent window. It is self-contained — the agent does not have our conversation context.

> Continue implementation of the algo-betting project.
>
> **First, read in order:**
> 1. `CLAUDE.md` — project invariants, especially the promotion gate and capital caps.
> 2. `docs/superpowers/specs/2026-04-18-algo-betting-design.md` — full system design.
> 3. `docs/superpowers/plans/2026-04-18-phase1-scaffolding.md` — completed Phase 1 scaffold.
> 4. Any plan file under `docs/superpowers/plans/` starting with `2026-04-18-phase2-*` (create one yourself if none exists, following the plan-doc conventions in `CLAUDE.md`).
>
> **Tasks, in order:**
> 1. If `.claude/agents/`, `scripts/validate_agents.py`, or the `pyproject.toml` change are uncommitted, commit them with a clear message first.
> 2. Implement Phase 2 real Betfair ingestion using `betfairlightweight`. Replace the dummy publisher in `services/ingestion/src/ingestion/__main__.py` with a real streaming client that publishes `MarketData` messages to the `market.data` Redis stream. Reuse `algobet_common.bus.BusClient` and `algobet_common.schemas.MarketData` exactly; do not redefine either.
> 3. Tests must stay green. Add new tests for the Betfair adapter (mock the SDK, don't hit live).
> 4. Keep the existing CI pipeline working (lint + typecheck + test + smoke).
>
> **Hard constraints:**
> - Do **not** implement Polymarket.
> - Do **not** implement the Execution Engine, Risk Manager, or live order placement.
> - Do **not** bypass the promotion gate defined in `CLAUDE.md`.
> - Paper trading API must match live execution API — but since neither exists yet, just leave a TODO pointing at the spec.
> - If you need live Betfair credentials, stop and open a PR describing what you need. Do not commit secrets.
>
> **When done or blocked:** open a PR from your branch with a clear description of what's implemented, what's tested, and what's outstanding. Then stop.

## Guardrails

- **Execution Engine absence = primary safety gate.** The agent cannot place live orders because the code to do so does not exist. Do not ask the agent to build it autonomously.
- **Promotion-gate-auditor subagent** (`.claude/agents/promotion-gate-auditor.md`) encodes the lifecycle checks. A long-running agent's planner can dispatch it before any strategy-lifecycle edit.
- **PR review is mandatory.** Even a 52-hour agent delivers a *proposal*, not a deployment.
- **Secrets never commit.** If the agent says it needs a live Betfair app-key, that is a human decision — answer via the Betfair developer program offline, then inject the key via env vars on the VPS later. The agent's own VM should see only dummy credentials.
- **Hard spend cap.** Usage-based billing can run away on a bad loop. Cap it.
- **Branch protection on `main`.** Require PR reviews + passing CI. The agent pushes to a feature branch; main stays protected.

## When Cursor long-running is the wrong tool

- **Anything touching live capital or credentials.** Do that by hand.
- **Architectural decisions.** The agent will happily build any of three valid options. You decide which.
- **Wiki curation.** Research agents writing to the wiki should use the Obsidian MCP path in this repo, not a Cursor cloud VM (which has no Obsidian GUI).

## Sources

- [Cursor — Background Agents docs](https://docs.cursor.com/en/background-agent)
- [Cursor — Scaling long-running autonomous coding](https://cursor.com/blog/scaling-agents)
- [Cursor — Expanding our long-running agents research preview](https://cursor.com/blog/long-running-agents)
- [Cursor — Agents Window](https://cursor.com/docs/agent/agents-window)
- [NxCode — Cursor Cloud Agents 2026 guide](https://www.nxcode.io/resources/news/cursor-cloud-agents-virtual-machines-autonomous-coding-guide-2026)
- [ameany — Cursor Background Agents: Complete Guide (2026)](https://ameany.io/cursor-background-agents/)
