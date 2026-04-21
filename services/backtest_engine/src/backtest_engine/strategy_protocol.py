"""Protocols bridging the harness and user code.

``StrategyModule`` is the contract every research-generated strategy must
satisfy — a single pure ``on_tick`` callable. Phase 6c will enforce purity
via AST walk; 6a only documents the shape.

``TickSource`` is the async iterator contract implemented by ``SyntheticSource``
(in-memory ticks for determinism tests) and ``ArchiveSource`` (cursor over
the ``market_data_archive`` hypertable).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from algobet_common.schemas import MarketData, OrderSignal


class StrategyModule(Protocol):
    """Strategy contract: pure tick → optional signal.

    Implementations MUST NOT perform I/O, access ``os.environ``, or import
    network modules. The harness itself does not enforce this; the 6c safety
    check (AST walk at load time) will.
    """

    def on_tick(
        self,
        snapshot: MarketData,
        params: dict[str, Any],
        now: datetime,
    ) -> OrderSignal | None: ...


class TickSource(Protocol):
    """Timestamp-ordered async tick source.

    Implementations emit ``MarketData`` whose ``timestamp`` is monotonically
    non-decreasing and lies within the closed ``time_range`` interval.
    """

    def iter_ticks(
        self,
        time_range: tuple[datetime, datetime],
    ) -> AsyncIterator[MarketData]: ...
