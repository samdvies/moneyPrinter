# strategy_registry

Python library providing typed CRUD and lifecycle state-machine for the algo-betting strategy registry.

## Public API

```python
from strategy_registry import (
    Strategy, StrategyRun, Status, Mode,
    create_strategy, get_strategy, list_strategies,
    transition, start_run, end_run,
)
```

All functions are `async` and accept an `algobet_common.db.Database` instance as their first argument.

| Function | Description |
|---|---|
| `create_strategy(db, *, slug, parameters, wiki_path)` | Insert a new strategy at `hypothesis` status. |
| `get_strategy(db, strategy_id)` | Fetch a single `Strategy` by UUID. |
| `list_strategies(db, *, status=None)` | Return all strategies, optionally filtered by status. |
| `transition(db, strategy_id, to_status, *, approved_by=None)` | Move a strategy to a new lifecycle status (see gate below). |
| `start_run(db, strategy_id, mode, *, metrics=None)` | Create a `strategy_runs` row for a new run. |
| `end_run(db, run_id, *, metrics=None)` | Mark a run as ended and record final metrics. |

## Lifecycle

```
hypothesis
    │
    ▼
backtesting ──────────────────────┐
    │                             │
    ▼                             │
paper ──────────────────────────  │
    │                             ▼
    ▼                           retired
awaiting-approval ─────────────►  ▲
    │                             │
    ▼                             │
  live ───────────────────────────┘
```

Allowed transitions:

| From | To | Notes |
|---|---|---|
| `hypothesis` | `backtesting` | |
| `backtesting` | `paper` | |
| `backtesting` | `retired` | |
| `paper` | `awaiting-approval` | |
| `paper` | `retired` | |
| `awaiting-approval` | `live` | **requires non-empty `approved_by`** |
| `awaiting-approval` | `retired` | |
| `live` | `retired` | |

`retired` is terminal — no further transitions are permitted.

### The `awaiting-approval → live` gate

This is the only path to `live`. It requires a non-empty `approved_by` string identifying the human operator who approved promotion. When the transition succeeds, `approved_by` and `approved_at` are stamped atomically in the same transaction.

The `transition()` function uses `SELECT ... FOR UPDATE` to prevent TOCTOU races: if two callers concurrently attempt the same transition, exactly one will succeed and the other will receive `InvalidTransitionError`.

**Operator identity** is a free-form string in this phase. The dashboard (Phase 5) will introduce real authentication; until then any non-empty string is accepted.

## Naming note: `backtesting` vs `backtest`

CLAUDE.md describes the lifecycle as `hypothesis → backtest → paper → awaiting-approval → live`. The database CHECK constraint uses `backtesting` (not `backtest`) as the column value. This package uses the DB values verbatim. A future migration may rename this; until then, use `Status.BACKTESTING` in code and expect `"backtesting"` in the database.

The `mode` column in `strategy_runs` and `orders` uses `backtest` (without the `-ing` suffix), matching the `Mode.BACKTEST` enum value.

## Errors

| Exception | Raised when |
|---|---|
| `StrategyNotFoundError` | `get_strategy` or `transition` called with an unknown UUID |
| `InvalidTransitionError` | The requested transition is not in the allowed map |
| `ApprovalRequiredError` | `awaiting-approval → live` called without a non-empty `approved_by` |

## Promotion gate

Before merging, invoke `promotion-gate-auditor` to audit `transitions.py` and `crud.py::transition`. The auditor must return GO. No code path other than `crud.transition()` may write `status='live'` to the strategies table.
