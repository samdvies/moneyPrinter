"""Check Python↔Rust execution schema parity.

The Rust helper binary emits one JSON line per type with serialized field names.
This script compares that output against expected Python contract fields.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EMIT_SCHEMA_CMD = [
    "rustup",
    "run",
    "1.95.0",
    "cargo",
    "run",
    "--quiet",
    "-p",
    "execution-core",
    "--bin",
    "emit_schema",
]

EXPECTED_FIELDS: dict[str, list[str]] = {
    "OrderRequest": [
        "client_order_id",
        "market_id",
        "price",
        "schema_version",
        "selection_id",
        "side",
        "stake",
    ],
    "OrderState": [],
    "ExecutionResult": [
        "avg_fill_price",
        "client_order_id",
        "filled_stake",
        "schema_version",
        "state",
        "ts_utc",
        "venue_order_id",
    ],
}

EXPECTED_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "OrderRequest": [],
    "OrderState": [],
    "ExecutionResult": ["avg_fill_price", "venue_order_id"],
}


def _run_emit_schema() -> dict[str, dict[str, Any]]:
    """Return emitted schema payloads keyed by type name."""
    proc = subprocess.run(
        EMIT_SCHEMA_CMD,
        cwd=REPO_ROOT / "execution",
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"emit_schema failed ({proc.returncode}): {stderr}")

    parsed: dict[str, dict[str, Any]] = {}
    for line in proc.stdout.splitlines():
        payload = json.loads(line)
        type_name = payload["type"]
        parsed[type_name] = payload
    return parsed


def main() -> int:
    """Program entrypoint."""
    actual_payloads = _run_emit_schema()
    failures: list[str] = []

    expected_types = set(EXPECTED_FIELDS.keys())
    actual_types = set(actual_payloads.keys())
    missing_types = sorted(expected_types - actual_types)
    extra_types = sorted(actual_types - expected_types)

    if missing_types:
        failures.append(f"missing Rust schema types: {missing_types}")
    if extra_types:
        failures.append(f"unexpected Rust schema types: {extra_types}")

    for type_name, expected_fields in EXPECTED_FIELDS.items():
        if type_name not in actual_payloads:
            continue
        actual_fields = actual_payloads[type_name].get("fields", [])
        if actual_fields != expected_fields:
            failures.append(
                f"{type_name} field mismatch: expected={expected_fields}, actual={actual_fields}",
            )
        expected_optional_fields = EXPECTED_OPTIONAL_FIELDS[type_name]
        actual_optional_fields = actual_payloads[type_name].get("optional_fields", [])
        if actual_optional_fields != expected_optional_fields:
            failures.append(
                (
                    f"{type_name} optional-field mismatch: "
                    f"expected={expected_optional_fields}, actual={actual_optional_fields}"
                ),
            )

    if failures:
        print("Schema parity check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Schema parity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
