# Obsidian MCP + Research Continuation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up an Obsidian MCP server against the project's `wiki/` vault so agents can read/write notes programmatically, then execute a second wave of deep research that closes the open questions from Phase 0.

**Architecture:** Local Obsidian app runs the Local REST API plugin against `C:\Users\davie\algo-betting\wiki`. A stdio MCP server (`cyanheads/obsidian-mcp-server`) bridges Claude Code → Obsidian. Research tasks run as parallel Haiku subagents that write findings directly into the vault via the MCP server.

**Tech Stack:** Obsidian (desktop), Obsidian Local REST API community plugin, Node.js 20+ (for the MCP server), `cyanheads/obsidian-mcp-server`, Claude Code MCP configuration.

---

## Fresh-session bootstrap (read these first)

Any Claude that picks up this plan in a new session MUST read, in order:

1. `C:\Users\davie\algo-betting\CLAUDE.md` — project invariants
2. `C:\Users\davie\algo-betting\docs\superpowers\specs\2026-04-18-algo-betting-design.md` — full system design
3. `C:\Users\davie\algo-betting\wiki\00-Index\README.md` — wiki map
4. `C:\Users\davie\algo-betting\wiki\10-Foundations\Karpathy-LLM-Wiki.md` — knowledge-management pattern
5. `C:\Users\davie\.claude\projects\C--Users-davie-algo-betting\memory\MEMORY.md` — persisted user/project memory

## Current state (as of 2026-04-18)

- Project tree scaffolded at `C:\Users\davie\algo-betting\`
- Obsidian vault seeded with 11 notes + 3 templates + `.obsidian/` config
- No services implemented yet. No live credentials. No Obsidian app installed or MCP wired.
- Phase 0 design is locked. Next step is this plan.

---

## Part A — Obsidian MCP Wiring

### Task A1: Install Obsidian desktop

**Files:**
- None (installs the Obsidian app; binary lands under `%LocalAppData%\Programs\Obsidian`)

- [ ] **Step 1: Check if Obsidian is already installed**

Run: `Get-ChildItem "$env:LocalAppData\Programs\Obsidian\Obsidian.exe" -ErrorAction SilentlyContinue`
Expected: path printed if present, nothing if not.

- [ ] **Step 2: If not installed, download and install**

Download https://obsidian.md/download → run the installer (user interaction required, ask the user to confirm before triggering).

- [ ] **Step 3: Open the vault**

In Obsidian: **Open folder as vault** → select `C:\Users\davie\algo-betting\wiki`.
Confirm the left sidebar shows folders `00-Index`, `10-Foundations`, `20-Markets`, `30-Strategies`, `40-Papers`, `50-Infrastructure`, `60-Agents`, `70-Daily`, `80-Sources` (may be absent — fine), `90-Templates`.

### Task A2: Install Obsidian Local REST API plugin

**Files:**
- Modify: `C:\Users\davie\algo-betting\wiki\.obsidian\community-plugins.json` (Obsidian writes this on enable)
- Create: `C:\Users\davie\algo-betting\wiki\.obsidian\plugins\obsidian-local-rest-api\data.json` (Obsidian writes on config)

- [ ] **Step 1: Enable community plugins**

Obsidian → Settings → Community plugins → **Turn on community plugins** (first-run consent).

- [ ] **Step 2: Install the plugin**

Community plugins → Browse → search "Local REST API" by Adam Coddington → Install → Enable.

- [ ] **Step 3: Configure the plugin**

Settings → Local REST API → note the **API key** (copy it — we'll need it for Task A4). Enable **HTTPS** (default). Note the port (27124 for HTTPS by default).

- [ ] **Step 4: Verify the API responds**

Run: `curl -k -H "Authorization: Bearer <API_KEY>" https://127.0.0.1:27124/vault/`
Expected: JSON listing of vault files (or the vault root directory).

### Task A3: Install the Obsidian MCP server

**Files:**
- Create: `C:\Users\davie\algo-betting\scripts\mcp\obsidian-mcp\` (clone target)

- [ ] **Step 1: Clone the MCP server**

Run:
```powershell
mkdir C:\Users\davie\algo-betting\scripts\mcp -Force
git clone https://github.com/cyanheads/obsidian-mcp-server.git C:\Users\davie\algo-betting\scripts\mcp\obsidian-mcp
```

Expected: fresh clone, no errors.

- [ ] **Step 2: Install dependencies & build**

Run:
```powershell
cd C:\Users\davie\algo-betting\scripts\mcp\obsidian-mcp
npm install
npm run build
```

Expected: build output in `dist/` (or whatever the repo README specifies — read its README first).

- [ ] **Step 3: Smoke test the server standalone**

Run (from the cloned dir):
```powershell
$env:OBSIDIAN_API_KEY="<API_KEY>"
$env:OBSIDIAN_BASE_URL="https://127.0.0.1:27124"
$env:OBSIDIAN_VERIFY_SSL="false"
node dist/index.js
```

Expected: server starts on stdio, logs readiness, does not crash. Ctrl+C to stop.

### Task A4: Register the MCP server with Claude Code

**Files:**
- Modify: `C:\Users\davie\.claude\settings.json` OR `C:\Users\davie\.claude\settings.local.json` (preferred for secrets)

- [ ] **Step 1: Read the current settings file**

Run: `cat C:\Users\davie\.claude\settings.json` (and `.local.json` if present) to see existing `mcpServers` entries.

- [ ] **Step 2: Add the obsidian entry**

Add (or merge) into the `mcpServers` object:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "node",
      "args": ["C:\\Users\\davie\\algo-betting\\scripts\\mcp\\obsidian-mcp\\dist\\index.js"],
      "env": {
        "OBSIDIAN_API_KEY": "<API_KEY>",
        "OBSIDIAN_BASE_URL": "https://127.0.0.1:27124",
        "OBSIDIAN_VERIFY_SSL": "false"
      }
    }
  }
}
```

Put the API key in `settings.local.json` (git-ignored), not `settings.json`.

- [ ] **Step 3: Restart Claude Code**

Exit and relaunch so it picks up the new MCP server.

- [ ] **Step 4: Verify Claude can see the MCP tools**

In the new session, confirm tools prefixed `mcp__obsidian__*` appear in ToolSearch. Specifically look for tools like `mcp__obsidian__list_files`, `mcp__obsidian__read_note`, `mcp__obsidian__create_note`, `mcp__obsidian__search`.

### Task A5: MCP smoke test against the live vault

**Files:**
- Create: `C:\Users\davie\algo-betting\wiki\70-Daily\2026-04-19.md` (smoke test artefact; safe to delete after)

- [ ] **Step 1: List vault files via MCP**

Use `mcp__obsidian__list_files` (or the server's equivalent) to list the root.
Expected: the numeric-prefixed folders plus README.

- [ ] **Step 2: Read a known note via MCP**

Read `00-Index/README.md` via MCP.
Expected: content matches what's on disk.

- [ ] **Step 3: Create a new note via MCP**

Use `mcp__obsidian__create_note` with path `70-Daily/2026-04-19.md` and minimal frontmatter + a one-line "MCP smoke test" body.
Expected: note created, appears in Obsidian sidebar without restart.

- [ ] **Step 4: Search via MCP**

Search the vault for "Karpathy".
Expected: at least `10-Foundations/Karpathy-LLM-Wiki.md` returned.

- [ ] **Step 5: Cleanup smoke-test note**

Delete the `70-Daily/2026-04-19.md` note (or merge it into a legitimate daily log if research has been done today).

---

## Part B — Deep Research Wave 2

Goal: answer the open questions parked at the end of Phase 0's design + deepen the OSS code review. All research runs as background Haiku subagents writing directly into the vault via MCP (once Part A is done) or via Write (if done before A is complete).

### Task B1: Deep read `flumine` internals

**Files:**
- Create: `wiki/20-Markets/Flumine-Internals.md`

- [ ] **Step 1: Dispatch research agent**

Dispatch a Haiku agent with prompt:
> Read the source of `betcode-org/flumine` on GitHub. Produce a page covering: (1) the event-loop / streaming architecture, (2) how strategies register with the framework, (3) the simulation harness and how it approximates fills and slippage, (4) risk controls built in, (5) multi-venue abstraction, (6) any opinions / design choices we should import for our own Simulator and Strategy contract. Report as a single markdown doc ready to drop into `wiki/20-Markets/Flumine-Internals.md`, including YAML frontmatter per the project conventions in `wiki/00-Index/README.md`.

- [ ] **Step 2: Write output to vault**

Save result to `C:\Users\davie\algo-betting\wiki\20-Markets\Flumine-Internals.md`.

- [ ] **Step 3: Update the index**

Add `[[20-Markets/Flumine-Internals]]` under the `20 — Markets` section of `wiki/00-Index/README.md`.

### Task B2: Deep read `betfairlightweight` API surface

**Files:**
- Create: `wiki/20-Markets/betfairlightweight-API.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> Read the README, docs, and key modules of `betcode-org/betfair` (the `betfairlightweight` library). Produce an API-surface overview page covering: (1) auth + session lifecycle, (2) REST vs Streaming, (3) placing orders (market on close, limit, BSP), (4) listener / handler pattern for stream events, (5) known pitfalls & rate-limit behaviour, (6) 2026 protocol changes if any. Output frontmatter + markdown suitable for `wiki/20-Markets/betfairlightweight-API.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index under `20 — Markets`.

### Task B3: Kalshi API limits & WebSocket specifics

**Files:**
- Create: `wiki/20-Markets/Kalshi-API-Limits.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> Look up the current Kalshi API (docs.kalshi.com) specifics for a trading bot in 2026: (1) REST rate limits, (2) WebSocket streaming endpoints, (3) top-of-book vs depth availability, (4) order types supported, (5) settlement mechanics, (6) sandbox environment and how to use it without real capital. Cite the docs URLs. Output frontmatter + markdown for `wiki/20-Markets/Kalshi-API-Limits.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index.

### Task B4: Betfair app-key application process

**Files:**
- Create: `wiki/20-Markets/Betfair-App-Key-Process.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> Research the Betfair Developer Program app-key application flow in 2026: (1) delayed app-key vs live app-key, (2) £299 (or current) fee for live, (3) certification / review steps, (4) expected turnaround, (5) what the developer portal requires from the applicant, (6) any useful walkthroughs from 2024–2026 forum posts. Output as a practical checklist the project operator can follow. Save as markdown for `wiki/20-Markets/Betfair-App-Key-Process.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index.

### Task B5: Kalshi ToS for UK residents via Chicago VPS

**Files:**
- Create: `wiki/20-Markets/Kalshi-UK-Residency-Legal.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> Research whether Kalshi permits UK-resident users to trade, especially when connecting via a US (Chicago) VPS. Check: (1) current ToS language around residency and eligibility, (2) known forum reports of UK residents using Kalshi, (3) KYC requirements (SSN, US tax ID), (4) any 2024–2026 regulatory updates. Output a risk summary ending in a clear "go/no-go" recommendation for a UK hobbyist. Save as `wiki/20-Markets/Kalshi-UK-Residency-Legal.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index. **This may block live Kalshi trading — flag clearly in the page.**

### Task B6: Concrete strategy-promotion thresholds

**Files:**
- Create: `wiki/30-Strategies/Promotion-Thresholds.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> For a hobbyist algo-betting operation with £1,000 per-strategy live cap, synthesise best-practice numeric thresholds that a strategy must clear before being promoted from (a) backtest → paper, and (b) paper → awaiting-human-approval. Cover: minimum sample size (N trades), minimum Closing Line Value margin, minimum Sharpe-equivalent, maximum drawdown tolerance, minimum live-out-of-sample paper period, any statistical-significance test recommendation. Reference sources (Buchdahl, Pinnacle, Ed Thorp). Output as `wiki/30-Strategies/Promotion-Thresholds.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index under `30 — Strategies`.

- [ ] **Step 3: Reference in CLAUDE.md**

Add a short bullet to `C:\Users\davie\algo-betting\CLAUDE.md` pointing at the thresholds file. Future orchestrator code will read these values.

### Task B7: Wiki git-versioning strategy

**Files:**
- Create: `wiki/60-Agents/Wiki-Versioning.md`

- [ ] **Step 1: Dispatch research agent**

Haiku agent prompt:
> Research approaches to version-controlling an LLM-maintained Obsidian wiki. Evaluate: (1) commit-per-ingestion (high resolution, noisy history), (2) daily rollup commit (low noise, coarse rollback), (3) a branch-per-agent workflow, (4) any existing Obsidian-git plugins or workflows used by public LLM-wiki projects. Recommend a default for this project given: solo operator, agent writes ~10-50 pages/day, wants to be able to revert a bad ingestion cleanly. Save as `wiki/60-Agents/Wiki-Versioning.md`.

- [ ] **Step 2: Save + index**

Save to path; add to index.

### Task B8: Parallelise B1–B7

**Files:**
- None (dispatches agents; they write their own files)

- [ ] **Step 1: Launch B1–B7 as parallel background agents**

Use the `Agent` tool with `subagent_type: general-purpose`, `model: haiku`, `run_in_background: true`. Dispatch all 7 in a single message with multiple Agent tool calls.

- [ ] **Step 2: Wait for completion notifications**

Do not poll; the runtime notifies when each completes.

- [ ] **Step 3: For each completed agent, write the output file**

After a completion, immediately write the page to its target path. Don't let outputs stack up — write as they arrive.

- [ ] **Step 4: Update the index once after all 7 land**

Single edit to `wiki/00-Index/README.md` adding all new page links at once.

- [ ] **Step 5: Append a section to today's daily log**

Append a "Research wave 2" section to `wiki/70-Daily/YYYY-MM-DD.md` summarising what each page answered and any follow-up questions.

---

## Part C — Memory & Handoff Hygiene

### Task C1: Update MEMORY.md with Part A/B outcomes

**Files:**
- Modify: `C:\Users\davie\.claude\projects\C--Users-davie-algo-betting\memory\MEMORY.md`
- Possibly create: memory entries for newly settled facts (e.g. Betfair app-key lead time, Kalshi UK eligibility)

- [ ] **Step 1: Add reference memory for Obsidian MCP**

Create `C:\Users\davie\.claude\projects\C--Users-davie-algo-betting\memory\reference_obsidian_mcp.md` documenting: server location, how to restart, how to rotate the API key. Add an index line to MEMORY.md.

- [ ] **Step 2: If research wave 2 answered an open question, update project memory**

Only for items that will remain true across sessions (e.g. "Kalshi blocks UK residents — do not attempt live"). Ephemeral findings belong in the wiki, not memory.

### Task C2: Close out Phase 0

**Files:**
- Modify: `C:\Users\davie\algo-betting\README.md`
- Modify: `C:\Users\davie\.claude\plans\i-want-to-look-streamed-seahorse.md`

- [ ] **Step 1: Flip status in README**

Change `Phase 0 — Research & scaffolding` → `Phase 0 complete — Phase 1 scaffolding next`.

- [ ] **Step 2: Append a "Phase 0 results" section to the seahorse plan file**

One paragraph summarising: MCP wired, research wave 2 outcomes, any blockers (esp. Kalshi UK eligibility).

---

## Verification

End-to-end check when the plan is complete:

- [ ] Obsidian app shows all existing + new research pages in the sidebar
- [ ] Claude Code (fresh session) can list, read, create, and search the vault via `mcp__obsidian__*` tools
- [ ] `wiki/00-Index/README.md` links to every new page from Part B
- [ ] `wiki/70-Daily/YYYY-MM-DD.md` for the day this is executed has a "Research wave 2" section
- [ ] `MEMORY.md` has one new reference entry (Obsidian MCP)
- [ ] `C:\Users\davie\algo-betting\scripts\mcp\obsidian-mcp\` exists with a built `dist/`

## Non-Goals

- Installing Smart Connections or Text Generator plugins (keep Obsidian lean until MCP proves sufficient)
- Setting up any service (Ingestion, Simulator, Execution) — that's Phase 1, separate plan
- Applying for the Betfair live app-key (Task B4 only researches the *process*; application itself is a later user decision)
- Any live credential wiring

## Open questions that will remain after this plan

- Exact Phase-1 service build order (will come from a Phase-1 plan, informed by B1–B3 outputs)
- Orchestrator cost budget (Claude tokens/day)
- Whether to vendor `flumine` or depend on it directly (informed by B1 output)
