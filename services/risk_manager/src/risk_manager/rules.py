"""Pure pre-flight safety rules for the risk manager.

All functions are I/O-free so they can be unit-tested offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from algobet_common.config import Settings
from algobet_common.schemas import OrderSignal, Venue

_KNOWN_VENUES = {Venue.BETFAIR, Venue.KALSHI}


@dataclass
class RuleResult:
    passed: bool
    severity: Literal["warn", "critical"] | None
    reason: str | None

    @classmethod
    def ok(cls) -> RuleResult:
        return cls(passed=True, severity=None, reason=None)


def check_kill_switch(signal: OrderSignal, settings: Settings) -> RuleResult:
    """Block or warn when the global kill-switch is active."""
    if not settings.risk_kill_switch:
        return RuleResult.ok()
    if signal.mode == "live":
        return RuleResult(
            passed=False,
            severity="critical",
            reason="kill-switch active; live signals blocked",
        )
    return RuleResult(
        passed=False,
        severity="warn",
        reason="kill-switch active; paper signals paused",
    )


def check_exposure(signal: OrderSignal, settings: Settings) -> RuleResult:
    """Reject a signal whose stake exceeds the per-signal exposure cap."""
    if signal.stake > settings.risk_max_strategy_exposure_gbp:
        return RuleResult(
            passed=False,
            severity="warn",
            reason=(f"stake {signal.stake} exceeds cap {settings.risk_max_strategy_exposure_gbp}"),
        )
    return RuleResult.ok()


def check_venue_notional(signal: OrderSignal, settings: Settings) -> RuleResult:
    """Reject signals for unrecognised venues or signals breaching a venue cap."""
    if signal.venue not in _KNOWN_VENUES:
        return RuleResult(
            passed=False,
            severity="warn",
            reason=f"unrecognised venue: {signal.venue!r}",
        )
    cap = settings.risk_venue_notionals.get(signal.venue.value)
    if cap is None:
        return RuleResult.ok()
    if signal.stake > cap:
        return RuleResult(
            passed=False,
            severity="warn",
            reason=(f"stake {signal.stake} exceeds venue cap {cap} for {signal.venue.value}"),
        )
    return RuleResult.ok()


def check_registry_mode(
    signal: OrderSignal,
    strategy_status: str | None,
    run_mode: str | None,
) -> RuleResult:
    """Validate strategy registry state against the incoming signal."""
    if strategy_status is None:
        return RuleResult(
            passed=False,
            severity="warn",
            reason=f"strategy {signal.strategy_id!r} not found in registry",
        )
    if signal.mode == "live" and strategy_status != "live":
        return RuleResult(
            passed=False,
            severity="warn",
            reason=(
                f"live signal rejected: strategy status is {strategy_status!r}, expected 'live'"
            ),
        )
    if run_mode is not None and run_mode != signal.mode:
        return RuleResult(
            passed=False,
            severity="warn",
            reason=(f"signal mode {signal.mode!r} does not match latest run mode {run_mode!r}"),
        )
    return RuleResult.ok()
