"""Offline unit tests for risk_manager.rules — no I/O required."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest
from algobet_common.config import Settings
from algobet_common.schemas import OrderSide, OrderSignal, Venue
from risk_manager.rules import (
    RuleResult,
    check_exposure,
    check_kill_switch,
    check_registry_mode,
    check_venue_notional,
)

pytestmark = pytest.mark.unit


def _signal(
    *,
    mode: Literal["paper", "live"] = "paper",
    stake: Decimal = Decimal("10"),
    venue: Venue = Venue.BETFAIR,
) -> OrderSignal:
    return OrderSignal(
        strategy_id="00000000-0000-0000-0000-000000000001",
        mode=mode,
        venue=venue,
        market_id="1.23",
        side=OrderSide.BACK,
        stake=stake,
        price=Decimal("2.0"),
    )


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"service_name": "test"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# check_kill_switch
# ---------------------------------------------------------------------------


class TestCheckKillSwitch:
    def test_kill_switch_off_passes(self) -> None:
        result = check_kill_switch(_signal(mode="live"), _settings(risk_kill_switch=False))
        assert result == RuleResult.ok()

    def test_kill_switch_on_live_critical_reject(self) -> None:
        result = check_kill_switch(_signal(mode="live"), _settings(risk_kill_switch=True))
        assert not result.passed
        assert result.severity == "critical"
        assert result.reason is not None

    def test_kill_switch_on_paper_warn_reject(self) -> None:
        result = check_kill_switch(_signal(mode="paper"), _settings(risk_kill_switch=True))
        assert not result.passed
        assert result.severity == "warn"
        assert result.reason is not None


# ---------------------------------------------------------------------------
# check_exposure
# ---------------------------------------------------------------------------


class TestCheckExposure:
    def test_stake_at_cap_passes(self) -> None:
        result = check_exposure(
            _signal(stake=Decimal("1000")),
            _settings(risk_max_strategy_exposure_gbp=Decimal("1000")),
        )
        assert result == RuleResult.ok()

    def test_stake_above_cap_warn_reject(self) -> None:
        result = check_exposure(
            _signal(stake=Decimal("1001")),
            _settings(risk_max_strategy_exposure_gbp=Decimal("1000")),
        )
        assert not result.passed
        assert result.severity == "warn"
        assert "1001" in (result.reason or "")


# ---------------------------------------------------------------------------
# check_venue_notional
# ---------------------------------------------------------------------------


class TestCheckVenueNotional:
    def test_no_cap_configured_passes(self) -> None:
        result = check_venue_notional(_signal(venue=Venue.BETFAIR), _settings())
        assert result == RuleResult.ok()

    def test_cap_configured_under_passes(self) -> None:
        result = check_venue_notional(
            _signal(venue=Venue.BETFAIR, stake=Decimal("100")),
            _settings(risk_venue_notionals={"betfair": Decimal("5000")}),
        )
        assert result == RuleResult.ok()

    def test_cap_configured_over_warn_reject(self) -> None:
        result = check_venue_notional(
            _signal(venue=Venue.BETFAIR, stake=Decimal("6000")),
            _settings(risk_venue_notionals={"betfair": Decimal("5000")}),
        )
        assert not result.passed
        assert result.severity == "warn"

    def test_unrecognised_venue_warn_reject(self) -> None:
        # Construct a signal with a venue string that doesn't match known venues.
        # We bypass the Venue enum by using model_construct to inject a bad value.
        # For testing the unrecognised-venue guard we mock the enum check directly.
        # Actually, Venue is a StrEnum and can only hold known values, so we patch
        # the known set by passing a signal with venue=Venue.KALSHI and removing
        # KALSHI from the known set. Instead, test the guard path via the rules
        # module's internal _KNOWN_VENUES set.
        import risk_manager.rules as rules_mod

        original = rules_mod._KNOWN_VENUES.copy()
        rules_mod._KNOWN_VENUES.discard(Venue.KALSHI)
        try:
            result = check_venue_notional(_signal(venue=Venue.KALSHI), _settings())
            assert not result.passed
            assert result.severity == "warn"
            assert "unrecognised" in (result.reason or "")
        finally:
            rules_mod._KNOWN_VENUES = original


# ---------------------------------------------------------------------------
# check_registry_mode
# ---------------------------------------------------------------------------


class TestCheckRegistryMode:
    def test_strategy_not_found_warn_reject(self) -> None:
        result = check_registry_mode(_signal(), strategy_status=None, run_mode=None)
        assert not result.passed
        assert result.severity == "warn"

    def test_live_signal_wrong_strategy_status_warn_reject(self) -> None:
        result = check_registry_mode(
            _signal(mode="live"),
            strategy_status="paper",
            run_mode="live",
        )
        assert not result.passed
        assert result.severity == "warn"

    def test_run_mode_mismatch_warn_reject(self) -> None:
        result = check_registry_mode(
            _signal(mode="paper"),
            strategy_status="paper",
            run_mode="live",
        )
        assert not result.passed
        assert result.severity == "warn"

    def test_all_match_passes(self) -> None:
        result = check_registry_mode(
            _signal(mode="live"),
            strategy_status="live",
            run_mode="live",
        )
        assert result == RuleResult.ok()

    def test_paper_signal_no_run_mode_passes(self) -> None:
        result = check_registry_mode(
            _signal(mode="paper"),
            strategy_status="paper",
            run_mode=None,
        )
        assert result == RuleResult.ok()
