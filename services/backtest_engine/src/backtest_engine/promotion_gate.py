"""Deterministic promotion criteria from wiki thresholds or project defaults."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, cast

import yaml

# Defaults when wiki omits ``promotion_thresholds`` (plan §validate).
DEFAULT_THRESHOLDS: dict[str, float] = {
    "sharpe": 0.5,
    "max_dd_pct": -20.0,
    "hit_rate": 0.45,
    "p_value_sharpe": 0.05,
    "walkforward_degradation": 0.5,
}


def load_thresholds(
    strategy_slug: str,
    wiki_root: Path = Path("wiki/30-Strategies"),
) -> dict[str, float]:
    """Parse strategy wiki frontmatter for ``promotion_thresholds`` mapping."""
    path = wiki_root / f"{strategy_slug}.md"
    if not path.is_file():
        return dict(DEFAULT_THRESHOLDS)
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return dict(DEFAULT_THRESHOLDS)
    fm = yaml.safe_load(m.group(1)) or {}
    raw = fm.get("promotion_thresholds")
    if not isinstance(raw, dict) or not raw:
        return dict(DEFAULT_THRESHOLDS)
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return {**DEFAULT_THRESHOLDS, **out}


def _report_to_dict(report: Any) -> dict[str, Any]:
    """Accept BacktestReport or plain dict (CLI JSON)."""
    if hasattr(report, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(report)
    return dict(report)


def check_promotion_criteria(report: Any, thresholds: dict[str, float]) -> tuple[bool, list[str]]:
    """Return (passed, failure_reasons) against numeric thresholds."""
    r = _report_to_dict(report)
    reasons: list[str] = []
    metrics = cast(dict[str, Any], r.get("metrics") or {})
    sig = cast(dict[str, Any], r.get("significance") or {})
    wf = cast(dict[str, Any], r.get("walkforward") or {})

    sharpe = float(metrics.get("sharpe", 0.0))
    if sharpe < thresholds["sharpe"]:
        reasons.append(f"sharpe {sharpe:.4f} below minimum {thresholds['sharpe']}")

    raw_mdd = metrics.get("max_drawdown")
    mdd = raw_mdd if isinstance(raw_mdd, dict) else {}
    depth_pct = float(mdd.get("depth_pct", 0.0)) * 100.0
    if depth_pct < thresholds["max_dd_pct"]:
        reasons.append(
            f"max drawdown {depth_pct:.2f}% worse than threshold {thresholds['max_dd_pct']}%"
        )

    hit = float(metrics.get("hit_rate", 0.0))
    if hit < thresholds["hit_rate"]:
        reasons.append(f"hit_rate {hit:.4f} below minimum {thresholds['hit_rate']}")

    raw_rb = sig.get("random_baseline")
    rb = raw_rb if isinstance(raw_rb, dict) else {}
    p_sh = float(rb.get("p_value_sharpe", sig.get("p_value_sharpe", 1.0)))
    if p_sh == 1.0 and isinstance(sig.get("t_test"), dict):
        p_sh = float(sig["t_test"].get("p_value", 1.0))
    if p_sh > thresholds["p_value_sharpe"]:
        reasons.append(f"p_value_sharpe {p_sh:.4f} above alpha {thresholds['p_value_sharpe']}")

    deg = float(wf.get("degradation_ratio", 0.0))
    if math.isfinite(deg) and deg < thresholds["walkforward_degradation"]:
        reasons.append(
            f"walkforward OOS/IS degradation {deg:.4f} below minimum "
            f"{thresholds['walkforward_degradation']} (OOS Sharpe too weak vs IS)"
        )

    return (len(reasons) == 0, reasons)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--report path`` to JSON from validate artifact."""
    args = argv if argv is not None else sys.argv[1:]
    report_path: Path | None = None
    it = iter(args)
    for a in it:
        if a == "--report":
            report_path = Path(next(it))
        else:
            print(f"unknown arg: {a}", file=sys.stderr)
            return 2
    if report_path is None or not report_path.is_file():
        print(
            "usage: python -m backtest_engine.promotion_gate --report <report.json>",
            file=sys.stderr,
        )
        return 2
    data = json.loads(report_path.read_text(encoding="utf-8"))
    slug = str(data.get("strategy_slug", ""))
    th = load_thresholds(slug) if slug else dict(DEFAULT_THRESHOLDS)
    ok, reasons = check_promotion_criteria(data, th)
    if ok:
        print("PASS")
        return 0
    print("FAIL")
    for line in reasons:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
