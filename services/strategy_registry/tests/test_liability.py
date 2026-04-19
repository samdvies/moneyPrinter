"""Integration tests for open-liability CRUD helpers.

Requires Postgres with migration 0003 applied.
Tests seed orders via raw SQL to isolate from simulator changes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from algobet_common.db import Database
from strategy_registry import crud
from strategy_registry.models import Mode, Status

pytestmark = pytest.mark.integration

_VENUE = "betfair"
_MARKET = "1.99"


@pytest.fixture
async def db(postgres_dsn: str, require_postgres: None) -> AsyncGenerator[Database, None]:
    database = Database(postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def live_strategy(db: Database) -> AsyncGenerator[uuid.UUID, None]:
    """Create a strategy promoted to 'live', plus a live strategy_run. Yields strategy UUID."""
    strategy = await crud.create_strategy(db, slug=f"liability-test-{uuid.uuid4().hex[:8]}")
    sid = strategy.id
    await crud.transition(db, sid, Status.BACKTESTING)
    await crud.transition(db, sid, Status.PAPER)
    await crud.transition(db, sid, Status.AWAITING_APPROVAL)
    await crud.transition(db, sid, Status.LIVE, approved_by="test-automation")
    await crud.start_run(db, sid, Mode.LIVE)
    yield sid
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM orders WHERE strategy_id = $1", sid)
        await conn.execute("DELETE FROM strategy_runs WHERE strategy_id = $1", sid)
        await conn.execute("DELETE FROM strategies WHERE id = $1", sid)


async def _insert_order(
    db: Database,
    strategy_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    venue: str = _VENUE,
    market_id: str = _MARKET,
    side: str,
    stake: Decimal,
    price: Decimal,
    status: str = "placed",
    selection_id: str | None = None,
) -> uuid.UUID:
    """Insert an order row directly, bypassing the simulator."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO orders (strategy_id, run_id, mode, venue, market_id, side,
                                stake, price, status, selection_id)
            VALUES ($1, $2, 'live', $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            strategy_id,
            run_id,
            venue,
            market_id,
            side,
            stake,
            price,
            status,
            selection_id,
        )
    assert row is not None
    return uuid.UUID(str(row["id"]))


async def _get_run_id(db: Database, strategy_id: uuid.UUID) -> uuid.UUID:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM strategy_runs WHERE strategy_id = $1 ORDER BY started_at DESC LIMIT 1",
            strategy_id,
        )
    assert row is not None
    return uuid.UUID(str(row["id"]))


# ---------------------------------------------------------------------------
# Case 1: No open orders → get_open_liability == 0
# ---------------------------------------------------------------------------


async def test_no_open_orders_liability_is_zero(db: Database, live_strategy: uuid.UUID) -> None:
    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("0")

    components = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "A")
    assert components.market_liability == Decimal("0")


# ---------------------------------------------------------------------------
# Case 2: Back 100 @ 3.0, selection 'A' → market_liability = 100
# ---------------------------------------------------------------------------


async def test_single_back_order(db: Database, live_strategy: uuid.UUID) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("100"),
        price=Decimal("3.0"),
        selection_id="A",
    )
    # back_stake=100, lay_stake=0, back_winnings=200, lay_liability=0
    # loss_outcome = 100 - 0 = 100; win_outcome = 0 - 200 = -200
    # market_liability = max(0, 100, -200) = 100
    components = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "A")
    assert components.back_stake == Decimal("100")
    assert components.lay_stake == Decimal("0")
    assert components.market_liability == Decimal("100")

    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("100")


# ---------------------------------------------------------------------------
# Case 3: Lay 100 @ 3.0, selection 'A' → market_liability = 200
# ---------------------------------------------------------------------------


async def test_single_lay_order(db: Database, live_strategy: uuid.UUID) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="lay",
        stake=Decimal("100"),
        price=Decimal("3.0"),
        selection_id="A",
    )
    # back_stake=0, lay_stake=100, back_winnings=0, lay_liability=200
    # loss_outcome = 0 - 100 = -100; win_outcome = 200 - 0 = 200
    # market_liability = max(0, -100, 200) = 200
    components = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "A")
    assert components.lay_stake == Decimal("100")
    assert components.lay_liability == Decimal("200")
    assert components.market_liability == Decimal("200")

    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("200")


# ---------------------------------------------------------------------------
# Case 4: Back 100 @ 2.0 + Lay 100 @ 2.0, same selection 'A' → nets to 0
# ---------------------------------------------------------------------------


async def test_back_plus_lay_same_selection_nets_to_zero(
    db: Database, live_strategy: uuid.UUID
) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="lay",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    # back_stake=100, lay_stake=100, back_winnings=100, lay_liability=100
    # loss_outcome = 0; win_outcome = 0; market_liability = 0
    components = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "A")
    assert components.back_stake == Decimal("100")
    assert components.lay_stake == Decimal("100")
    assert components.back_winnings == Decimal("100")
    assert components.lay_liability == Decimal("100")
    assert components.market_liability == Decimal("0")

    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("0")


# ---------------------------------------------------------------------------
# Case 5: Back on sel 'A' + Lay on sel 'B' — two groups → total = 200
# Multi-runner safety: no cross-selection netting
# ---------------------------------------------------------------------------


async def test_multi_runner_no_cross_selection_netting(
    db: Database, live_strategy: uuid.UUID
) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        selection_id="A",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="lay",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        selection_id="B",
    )
    # Group A: back_stake=100, market_liability=100
    # Group B: lay_stake=100, lay_liability=100, market_liability=100
    # Total = 200
    comp_a = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "A")
    assert comp_a.market_liability == Decimal("100")

    comp_b = await crud.get_market_liability_components(db, live_strategy, _VENUE, _MARKET, "B")
    assert comp_b.market_liability == Decimal("100")

    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("200")


# ---------------------------------------------------------------------------
# Case 6: Two markets → 100 + 150 = 250
# ---------------------------------------------------------------------------


async def test_two_markets_separate_groups(db: Database, live_strategy: uuid.UUID) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        venue="betfair",
        market_id="market-A",
        side="back",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        selection_id="X",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        venue="betfair",
        market_id="market-B",
        side="lay",
        stake=Decimal("50"),
        price=Decimal("4.0"),
        selection_id="Y",
    )
    # Market A, sel X: back_stake=100, market_liability=100
    # Market B, sel Y: lay_stake=50, lay_liability=150, market_liability=150
    # Total = 250
    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("250")


# ---------------------------------------------------------------------------
# Case 7: Orders with status 'filled' or 'cancelled' do NOT contribute
# ---------------------------------------------------------------------------


async def test_closed_orders_do_not_contribute(db: Database, live_strategy: uuid.UUID) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("500"),
        price=Decimal("2.0"),
        status="filled",
        selection_id="A",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("300"),
        price=Decimal("2.0"),
        status="cancelled",
        selection_id="A",
    )
    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("0")


# ---------------------------------------------------------------------------
# Case 8: 'partially_filled' contributes FULL stake (conservative)
# ---------------------------------------------------------------------------


async def test_partially_filled_contributes_full_stake(
    db: Database, live_strategy: uuid.UUID
) -> None:
    run_id = await _get_run_id(db, live_strategy)
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("300"),
        price=Decimal("2.0"),
        status="partially_filled",
        selection_id="A",
    )
    # back_stake=300, market_liability=300 (full stake, not filled portion)
    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("300")


# ---------------------------------------------------------------------------
# Case 9: Legacy NULL-selection rows — each treated as own group (no netting)
# ---------------------------------------------------------------------------


async def test_null_selection_rows_no_cross_netting(db: Database, live_strategy: uuid.UUID) -> None:
    run_id = await _get_run_id(db, live_strategy)
    # Two back orders on the same market with selection_id=NULL
    # Each gets its own key 'order:<uuid>' in the view → two separate groups
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        status="placed",
        selection_id=None,
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("100"),
        price=Decimal("2.0"),
        status="placed",
        selection_id=None,
    )
    # Two separate groups each with market_liability=100 → total=200 (conservative)
    total = await crud.get_open_liability(db, live_strategy)
    assert total == Decimal("200")


# ---------------------------------------------------------------------------
# Case 10: Invariant — get_open_liability >= each selection's market_liability
# ---------------------------------------------------------------------------


async def test_invariant_total_ge_each_selection_liability(
    db: Database, live_strategy: uuid.UUID
) -> None:
    """For any (venue, market, selection), total liability >= that selection's market_liability."""
    run_id = await _get_run_id(db, live_strategy)
    # Mixed orders: back sel A, lay sel B, partially_filled sel C
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("200"),
        price=Decimal("3.0"),
        selection_id="A",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="lay",
        stake=Decimal("100"),
        price=Decimal("4.0"),
        selection_id="B",
    )
    await _insert_order(
        db,
        live_strategy,
        run_id,
        side="back",
        stake=Decimal("50"),
        price=Decimal("2.0"),
        status="partially_filled",
        selection_id="C",
    )

    total = await crud.get_open_liability(db, live_strategy)

    for sel_id in ("A", "B", "C"):
        sel_components = await crud.get_market_liability_components(
            db, live_strategy, _VENUE, _MARKET, sel_id
        )
        assert total >= sel_components.market_liability, (
            f"Invariant violated for selection {sel_id!r}: "
            f"total={total} < market_liability={sel_components.market_liability}"
        )
