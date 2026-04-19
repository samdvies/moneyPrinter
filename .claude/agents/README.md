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
