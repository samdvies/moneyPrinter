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
from strategy_registry.models import LiabilityComponents

pytestmark = pytest.mark.unit


def _signal(
    *,
    mode: Literal["paper", "live"] = "paper",
    stake: Decimal = Decimal("10"),
    venue: Venue = Venue.BETFAIR,
    side: OrderSide = OrderSide.BACK,
    price: Decimal = Decimal("2.0"),
    selection_id: str | None = None,
) -> OrderSignal:
    return OrderSignal(
        strategy_id="00000000-0000-0000-0000-000000000001",
        mode=mode,
        venue=venue,
        market_id="1.23",
        side=side,
        stake=stake,
        price=price,
        selection_id=selection_id,
    )


def _zero_components() -> LiabilityComponents:
    return LiabilityComponents(
        back_stake=Decimal("0"),
        lay_stake=Decimal("0"),
        back_winnings=Decimal("0"),
        lay_liability=Decimal("0"),
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
    def test_two_concurrent_backs_same_market(self) -> None:
        # Existing: back 500 @ 2.0. New signal: back 600 @ 2.0.
        # market_after: back_stake=1100, back_winnings=1100, loss=1100, win=-1100 → market=1100
        # projected = 500 - 500 + 1100 = 1100 > 1000 → rejected.
        before = LiabilityComponents(
            back_stake=Decimal("500"),
            lay_stake=Decimal("0"),
            back_winnings=Decimal("500"),
            lay_liability=Decimal("0"),
        )
        result = check_exposure(
            _signal(side=OrderSide.BACK, stake=Decimal("600"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("500"),
            market_components_before=before,
            max_exposure_gbp=Decimal("1000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert not result.passed
        assert result.severity == "warn"
        assert "projected" in (result.reason or "")

    def test_back_plus_lay_same_selection_nets_to_zero(self) -> None:
        # Existing: back 500 @ 2.0. New signal: lay 500 @ 2.0 same selection.
        # after: back_stake=500, lay_stake=500, back_winnings=500, lay_liability=500
        # loss=0, win=0 → market_after=0. projected = 500 - 500 + 0 = 0 ≤ 1000 → approved.
        before = LiabilityComponents(
            back_stake=Decimal("500"),
            lay_stake=Decimal("0"),
            back_winnings=Decimal("500"),
            lay_liability=Decimal("0"),
        )
        result = check_exposure(
            _signal(side=OrderSide.LAY, stake=Decimal("500"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("500"),
            market_components_before=before,
            max_exposure_gbp=Decimal("1000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert result == RuleResult.ok()

    def test_partial_fill_counts_full_stake(self) -> None:
        # Existing: partially_filled order stake=300 @ 2.0 → back_stake=300, back_winnings=300.
        # New signal: back 800 @ 2.0.
        # market_after: (1100,0,1100,0) → market=1100. projected=300-300+1100=1100>1000.
        before = LiabilityComponents(
            back_stake=Decimal("300"),
            lay_stake=Decimal("0"),
            back_winnings=Decimal("300"),
            lay_liability=Decimal("0"),
        )
        result = check_exposure(
            _signal(side=OrderSide.BACK, stake=Decimal("800"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("300"),
            market_components_before=before,
            max_exposure_gbp=Decimal("1000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert not result.passed
        assert result.severity == "warn"
        assert "projected" in (result.reason or "")

    def test_lay_extreme_price_trips_per_signal_ceiling(self) -> None:
        # Signal: lay 60 @ 20.0. signal_liability = (20-1)*60 = 1140 > ceiling 1000.
        result = check_exposure(
            _signal(side=OrderSide.LAY, stake=Decimal("60"), price=Decimal("20.0")),
            strategy_total_liability_before=Decimal("0"),
            market_components_before=_zero_components(),
            max_exposure_gbp=Decimal("1000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert not result.passed
        assert result.severity == "warn"
        assert "per-signal ceiling" in (result.reason or "")

    def test_strategy_override_allows_higher_cap(self) -> None:
        # First signal: back 4500 @ 2.0, cap=5000, per-signal ceiling=5000.
        # signal_liability=4500 ≤ 5000. projected = 0 - 0 + 4500 = 4500 ≤ 5000 → approved.
        result_first = check_exposure(
            _signal(side=OrderSide.BACK, stake=Decimal("4500"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("0"),
            market_components_before=_zero_components(),
            max_exposure_gbp=Decimal("5000"),
            per_signal_cap_gbp=Decimal("5000"),
        )
        assert result_first == RuleResult.ok()

        # Second signal: back 600 @ 2.0, same override. Existing state after first: 4500.
        # market_after: (5100,0,5100,0) → market=5100. projected=4500-4500+5100=5100>5000.
        before_second = LiabilityComponents(
            back_stake=Decimal("4500"),
            lay_stake=Decimal("0"),
            back_winnings=Decimal("4500"),
            lay_liability=Decimal("0"),
        )
        result_second = check_exposure(
            _signal(side=OrderSide.BACK, stake=Decimal("600"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("4500"),
            market_components_before=before_second,
            max_exposure_gbp=Decimal("5000"),
            per_signal_cap_gbp=Decimal("5000"),
        )
        assert not result_second.passed
        assert result_second.severity == "warn"
        assert "projected" in (result_second.reason or "")

    def test_kalshi_yes_at_60_cents_stake_100(self) -> None:
        # Signal: YES, stake=100, price=0.60 (USD-at-risk semantics).
        # signal_liability = 100. Ceiling 1000, cap 1000. projected = 0 - 0 + 100*(0.6-1) negative →
        # back_winnings = 100*(0.60-1) = -40; loss_outcome = 100-0 = 100; win_outcome = 0-(-40) = 40
        # market_liability_after = max(0, 100, 40) = 100. projected = 100 ≤ 1000 → approved.
        result = check_exposure(
            _signal(
                venue=Venue.KALSHI,
                side=OrderSide.YES,
                stake=Decimal("100"),
                price=Decimal("0.60"),
            ),
            strategy_total_liability_before=Decimal("0"),
            market_components_before=_zero_components(),
            max_exposure_gbp=Decimal("1000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert result == RuleResult.ok()

    def test_signal_liability_ceiling_independent_of_cumulative(self) -> None:
        # Signal: back 1500 @ 2.0, ceiling=1000, cap=5000.
        # signal_liability=1500>1000 → rejected with per-signal reason; cap=5000 has room.
        result = check_exposure(
            _signal(side=OrderSide.BACK, stake=Decimal("1500"), price=Decimal("2.0")),
            strategy_total_liability_before=Decimal("0"),
            market_components_before=_zero_components(),
            max_exposure_gbp=Decimal("5000"),
            per_signal_cap_gbp=Decimal("1000"),
        )
        assert not result.passed
        assert result.severity == "warn"
        assert "per-signal ceiling" in (result.reason or "")


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
