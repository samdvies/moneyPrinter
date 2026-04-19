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
    body = "\n".join(lines[end + 1 :]).strip()
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
        errors.append(
            f"{path}: frontmatter name {fields.get('name')!r} "
            f"does not match filename stem {path.stem!r}"
        )
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
