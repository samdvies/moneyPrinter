# Claude Code Agent Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-level Claude Code subagent team (6 agents) under `.claude/agents/` so the primary Claude Code session can dispatch scoped workflow roles (planner, researcher, implementer, reviewer, tester, promotion-gate-auditor).

**Architecture:** Each agent is a single Markdown file with YAML frontmatter (`name`, `description`, `tools`, `model`) followed by a system-prompt body. Files live in `.claude/agents/` at the repo root and are committed to git. A small Python validator script (`scripts/validate_agents.py`) lints the frontmatter so a broken file can't ship. No runtime code, no new dependencies.

**Tech Stack:** Markdown, YAML frontmatter, Python 3 stdlib (for the validator — stdlib only, no PyYAML), `.claude/agents/` conventions as understood by Claude Code.

**Source of truth for agent prompts:** `docs/superpowers/specs/2026-04-18-claude-code-agent-team-design.md` section "Agent System Prompts". Each task below references the exact subsection whose content must be copied verbatim into the system-prompt body of the corresponding file. Per the project's CLAUDE.md, plan documents do not embed full prose bodies that already live in an approved spec — the spec is the canonical source and rewriting it here would double-maintain.

---

## File Structure

Files created by this plan:

- `.claude/agents/planner.md` — planner agent
- `.claude/agents/researcher.md` — researcher agent
- `.claude/agents/implementer.md` — implementer agent
- `.claude/agents/reviewer.md` — reviewer agent
- `.claude/agents/tester.md` — tester agent
- `.claude/agents/promotion-gate-auditor.md` — promotion-gate-auditor agent
- `scripts/validate_agents.py` — stdlib-only validator that checks every `.claude/agents/*.md` file has required frontmatter fields and a non-empty body
- `.claude/agents/README.md` — one-page index explaining the team, linking back to the spec

No files are modified. No `.gitignore` change is required (the repo's `.gitignore` already excludes nothing under `.claude/agents/`).

## Frontmatter Contract (applies to every agent file)

```yaml
---
name: <kebab-case agent name, matches filename without .md>
description: <one sentence, in the third person, describing when to dispatch — this is what the orchestrator reads to decide>
tools: <comma-separated list of tool names, or omitted to inherit all>
model: <sonnet | opus | haiku>
---
```

Body: the system prompt, verbatim from the spec's corresponding subsection.

---

## Task 1: Scaffolding — directory + validator + README

**Files:**
- Create: `.claude/agents/` (directory)
- Create: `scripts/validate_agents.py`
- Create: `.claude/agents/README.md`

- [ ] **Step 1: Create the agents directory**

Run: `mkdir -p .claude/agents`
Expected: directory exists. Verify with `ls -la .claude/agents` — should be empty.

- [ ] **Step 2: Write the validator script**

Create `scripts/validate_agents.py` with the following content. It parses frontmatter manually (no PyYAML dependency), enforces `name`, `description`, `model`, and a non-empty body, and exits non-zero on any failure.

```python
#!/usr/bin/env python3
"""Validate every .claude/agents/*.md file has well-formed frontmatter and a body.

Usage: python scripts/validate_agents.py
Exits 0 on success, 1 on any failure. Prints one line per file checked.
"""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_FIELDS = {"name", "description", "model"}
ALLOWED_MODELS = {"sonnet", "opus", "haiku"}
AGENTS_DIR = Path(".claude/agents")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening --- frontmatter fence")
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("missing closing --- frontmatter fence")
    fields: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if ":" not in raw:
            raise ValueError(f"malformed frontmatter line: {raw!r}")
        key, _, value = raw.partition(":")
        fields[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1:]).strip()
    return fields, body


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"{path}: {exc}"]
    missing = REQUIRED_FIELDS - fields.keys()
    if missing:
        errors.append(f"{path}: missing frontmatter fields: {sorted(missing)}")
    if fields.get("name") != path.stem:
        errors.append(f"{path}: frontmatter name {fields.get('name')!r} does not match filename stem {path.stem!r}")
    model = fields.get("model")
    if model and model not in ALLOWED_MODELS:
        errors.append(f"{path}: model {model!r} not in {sorted(ALLOWED_MODELS)}")
    if not body:
        errors.append(f"{path}: empty body (system prompt required)")
    return errors


def main() -> int:
    if not AGENTS_DIR.is_dir():
        print(f"no agents directory at {AGENTS_DIR}", file=sys.stderr)
        return 1
    files = sorted(p for p in AGENTS_DIR.glob("*.md") if p.name != "README.md")
    if not files:
        print(f"no agent files in {AGENTS_DIR}", file=sys.stderr)
        return 1
    all_errors: list[str] = []
    for path in files:
        errs = check_file(path)
        status = "OK" if not errs else "FAIL"
        print(f"{status}  {path}")
        all_errors.extend(errs)
    if all_errors:
        print("", file=sys.stderr)
        for e in all_errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the validator — expect failure (no agents yet)**

Run: `python scripts/validate_agents.py`
Expected: exit code 1, stderr says `no agent files in .claude/agents`. This confirms the script detects the empty state. Do not treat this failure as a blocker — it is the intended baseline.

- [ ] **Step 4: Write the team README**

Create `.claude/agents/README.md`:

```markdown
# Claude Code Agent Team — algo-betting

Six project-level subagents dispatched by the primary Claude Code session. See the design spec at `docs/superpowers/specs/2026-04-18-claude-code-agent-team-design.md` for the full rationale and system prompts.

| Agent | Role | Model |
|---|---|---|
| `planner` | Turns specs into plans | sonnet |
| `researcher` | Wiki / paper / market-microstructure research | sonnet |
| `implementer` | Codes to a given plan | sonnet |
| `reviewer` | Read-only code review against spec + CLAUDE.md | opus |
| `tester` | Writes + runs tests | sonnet |
| `promotion-gate-auditor` | Read-only audit before real-money-adjacent changes | opus |

Validate with: `python scripts/validate_agents.py`
```

- [ ] **Step 5: Commit scaffolding**

Run:
```bash
git add .claude/agents/README.md scripts/validate_agents.py
git commit -m "scaffold Claude Code agent team directory and validator"
```

---

## Task 2: `planner` agent

**Files:**
- Create: `.claude/agents/planner.md`

**Spec reference:** section "Agent System Prompts → `planner`" in `docs/superpowers/specs/2026-04-18-claude-code-agent-team-design.md`.

- [ ] **Step 1: Create `planner.md`**

File structure:

```markdown
---
name: planner
description: Use when a spec exists and needs a step-by-step implementation plan, or when a feature needs to be decomposed into tasks.
tools: Read, Grep, Glob, Write, WebFetch
model: sonnet
---

<copy the planner system prompt verbatim from the spec section "Agent System Prompts → planner">
```

The frontmatter above is the complete, final frontmatter — do not edit it. The body is the blockquoted prose in the spec subsection, copied verbatim (strip the leading `> ` markdown quote markers).

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: `OK  .claude/agents/planner.md` on stdout, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/planner.md
git commit -m "add planner subagent"
```

---

## Task 3: `researcher` agent

**Files:**
- Create: `.claude/agents/researcher.md`

**Spec reference:** section "Agent System Prompts → `researcher`".

- [ ] **Step 1: Create `researcher.md`**

```markdown
---
name: researcher
description: Use for wiki, paper, or market-microstructure research for this project, especially when findings should land in the Obsidian vault at wiki/.
tools: Read, Grep, Glob, Write, WebFetch, WebSearch
model: sonnet
---

<copy the researcher system prompt verbatim from the spec section "Agent System Prompts → researcher">
```

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: `OK` lines for both `planner.md` and `researcher.md`, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/researcher.md
git commit -m "add researcher subagent"
```

---

## Task 4: `implementer` agent

**Files:**
- Create: `.claude/agents/implementer.md`

**Spec reference:** section "Agent System Prompts → `implementer`".

- [ ] **Step 1: Create `implementer.md`**

```markdown
---
name: implementer
description: Use when a plan exists and code needs to be written or edited to match it.
tools: Read, Edit, Write, Bash, Grep, Glob
model: sonnet
---

<copy the implementer system prompt verbatim from the spec section "Agent System Prompts → implementer">
```

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: all three agents `OK`, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/implementer.md
git commit -m "add implementer subagent"
```

---

## Task 5: `reviewer` agent

**Files:**
- Create: `.claude/agents/reviewer.md`

**Spec reference:** section "Agent System Prompts → `reviewer`".

- [ ] **Step 1: Create `reviewer.md`**

```markdown
---
name: reviewer
description: Use proactively after any non-trivial implementer output, before marking a task complete. Read-only review against the spec and CLAUDE.md invariants.
tools: Read, Grep, Glob
model: opus
---

<copy the reviewer system prompt verbatim from the spec section "Agent System Prompts → reviewer">
```

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: all four agents `OK`, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/reviewer.md
git commit -m "add reviewer subagent"
```

---

## Task 6: `tester` agent

**Files:**
- Create: `.claude/agents/tester.md`

**Spec reference:** section "Agent System Prompts → `tester`".

- [ ] **Step 1: Create `tester.md`**

```markdown
---
name: tester
description: Use to write or run tests for recently implemented code. May only edit test files — never source.
tools: Read, Edit, Write, Bash, Grep, Glob
model: sonnet
---

<copy the tester system prompt verbatim from the spec section "Agent System Prompts → tester">
```

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: all five agents `OK`, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/tester.md
git commit -m "add tester subagent"
```

---

## Task 7: `promotion-gate-auditor` agent

**Files:**
- Create: `.claude/agents/promotion-gate-auditor.md`

**Spec reference:** section "Agent System Prompts → `promotion-gate-auditor`".

- [ ] **Step 1: Create `promotion-gate-auditor.md`**

```markdown
---
name: promotion-gate-auditor
description: Use BEFORE any strategy lifecycle transition (hypothesis→backtest→paper→awaiting-approval→live) or any edit to risk_manager/, execution/, or strategy-registry state-transition code. Returns GO or NO-GO.
tools: Read, Grep, Glob
model: opus
---

<copy the promotion-gate-auditor system prompt verbatim from the spec section "Agent System Prompts → promotion-gate-auditor">
```

- [ ] **Step 2: Run the validator**

Run: `python scripts/validate_agents.py`
Expected: all six agents `OK`, exit code 0.

- [ ] **Step 3: Commit**

Run:
```bash
git add .claude/agents/promotion-gate-auditor.md
git commit -m "add promotion-gate-auditor subagent"
```

---

## Task 8: End-to-end verification

**Files:** none created or modified.

- [ ] **Step 1: Final validator run**

Run: `python scripts/validate_agents.py`
Expected output (order may vary):
```
OK  .claude/agents/implementer.md
OK  .claude/agents/planner.md
OK  .claude/agents/promotion-gate-auditor.md
OK  .claude/agents/researcher.md
OK  .claude/agents/reviewer.md
OK  .claude/agents/tester.md
```
Exit code 0.

- [ ] **Step 2: Confirm file count and names**

Run: `ls .claude/agents/*.md`
Expected: exactly 7 files — the six agents plus `README.md`.

- [ ] **Step 3: Spot-check one agent file manually**

Read `.claude/agents/promotion-gate-auditor.md`. Confirm:
- Frontmatter has `name`, `description`, `tools`, `model` — none blank.
- Body opens with the auditor's persona sentence and lists the seven numbered checks from the spec.
- Body ends with the "read-only ... never edit, test, or commit" constraint paragraph.

If any mismatch against the spec is found, fix it and re-run the validator before continuing.

- [ ] **Step 4: Smoke dispatch (optional, manual)**

In a fresh Claude Code session at the repo root, type `/agents`. Expected: the six agents appear in the list with their descriptions. (This step is optional because it requires the user to run the Claude Code CLI themselves; the validator provides sufficient automated coverage.)

- [ ] **Step 5: Final commit if anything changed in Step 3**

If Step 3 required edits:
```bash
git add .claude/agents/
git commit -m "fix agent prompt discrepancy surfaced during verification"
```
Otherwise, no commit needed — the team is already fully committed from Tasks 1–7.

---

## Self-Review Notes

- **Spec coverage:** Spec sections "Roster" and "Agent System Prompts" are covered by Tasks 2–7. Spec "Invariants" (project-level only, least-privilege tools, promotion gate, CLAUDE.md inheritance) are enforced via per-agent tool lists and explicit constraint paragraphs in each system prompt, which the validator ensures are present. Spec "Non-Goals" (no runtime agents, no user-level agents, no MCP/settings changes) are honored by the plan — no such files are touched.
- **Placeholder scan:** no "TBD" / "TODO" / "fill in later" patterns. Bodies are specified by verbatim reference to a fixed, already-written spec subsection, not left to interpretation.
- **Type consistency:** frontmatter field names and allowed model values are defined once in `validate_agents.py` (Task 1, Step 2) and re-used identically by Tasks 2–7.
