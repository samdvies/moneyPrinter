# Phase 1 Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **On approval:** This plan file lives at `.claude/plans/continue-with-the-algo-vast-reef.md` (plan mode artifact). Copy it to the canonical location `C:\Users\davie\algo-betting\docs\superpowers\plans\2026-04-18-phase1-scaffolding.md` as the first execution step.

## Context

Phase 0 (research + design) is complete. The full system design is locked at `docs/superpowers/specs/2026-04-18-algo-betting-design.md`. What does **not** exist yet: any code. The `services/` and `scripts/` directories are empty; there is no `pyproject.toml`, no `docker-compose.yml`, no CI, no database migrations.

This plan creates the minimal runnable skeleton for Phase 1, item #1 of the 11-step roadmap: **scaffolding + CI + Docker Compose**. After this plan executes, `docker compose up` brings up TimescaleDB + Redis locally, migrations create the Strategy Registry tables from the design spec, a shared `algobet_common` Python package exposes a Redis Streams bus client and pydantic message schemas, and a minimal `ingestion` service publishes one dummy `market.data` event that a smoke test reads back.

**Out of scope:** any real Betfair or Kalshi integration (Phase 2), simulator (Phase 4), Rust execution engine (user explicitly deferred to item #9's own plan). The existing unexecuted plan `docs/superpowers/plans/2026-04-18-obsidian-mcp-and-research.md` remains a prerequisite for the Research Orchestrator (Phase 7) but does not block scaffolding.

**Goal:** One sentence — a runnable local development skeleton with lint, typecheck, tests, and CI, onto which Phase 2+ services can be added incrementally.

**Architecture:** uv-managed Python monorepo. Root workspace declares two member packages (`services/common`, `services/ingestion`). Docker Compose provisions TimescaleDB (via `timescale/timescaledb:latest-pg16`) and Redis 7. Migrations are raw SQL files applied by a Python runner script. CI is GitHub Actions running ruff + mypy + pytest (unit tests offline, integration tests against Postgres + Redis service containers).

**Tech Stack:** Python 3.12, uv 0.5+, pydantic v2, pydantic-settings, redis-py (async), asyncpg, pytest + pytest-asyncio, ruff (lint + format), mypy, pre-commit, Docker Compose v2, GitHub Actions, TimescaleDB pg16, Redis 7.

---

## File Structure

```
algo-betting/
├── pyproject.toml                      # uv workspace root (no source)
├── uv.lock                             # committed
├── .python-version                     # 3.12
├── ruff.toml                           # lint + format config
├── mypy.ini                            # strict-ish type config
├── .pre-commit-config.yaml             # ruff + mypy on commit
├── docker-compose.yml                  # postgres + redis
├── .env.example                        # documented env vars
├── .dockerignore
├── .gitignore                          # extended
├── .github/workflows/ci.yml            # lint + typecheck + test matrix
├── services/
│   ├── common/
│   │   ├── pyproject.toml
│   │   ├── src/algobet_common/
│   │   │   ├── __init__.py
│   │   │   ├── config.py               # Settings via pydantic-settings
│   │   │   ├── schemas.py              # pydantic models for bus messages
│   │   │   ├── bus.py                  # async Redis Streams wrapper
│   │   │   └── db.py                   # asyncpg pool wrapper
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_config.py          # unit
│   │       ├── test_schemas.py         # unit
│   │       ├── test_bus.py             # integration (Redis)
│   │       └── test_db.py              # integration (Postgres)
│   └── ingestion/
│       ├── pyproject.toml
│       ├── src/ingestion/
│       │   ├── __init__.py
│       │   └── __main__.py             # publishes one dummy market.data tick
│       └── tests/
│           ├── __init__.py
│           └── test_hello.py
└── scripts/
    ├── db/
    │   └── migrations/
    │       ├── 0001_enable_timescaledb.sql
    │       └── 0002_strategy_registry.sql
    ├── migrate.py                      # applies migrations in order
    └── smoke.py                        # end-to-end publish → consume assertion
```

**Responsibility boundaries:**
- `algobet_common` is the only place bus and DB clients live. Every future service imports from here. Never re-implement bus logic in a service.
- `scripts/migrate.py` is the canonical migration runner. Not Alembic — raw SQL files applied in numeric order, recorded in a `schema_migrations` table.
- `docker-compose.yml` is local-dev only. Hetzner/Oracle production deploys are later plans.

---

## Task 1: Initialize uv workspace and tooling baseline

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `ruff.toml`
- Create: `mypy.ini`
- Modify: `.gitignore`

- [ ] **Step 1.1: Install uv**

Run: `which uv || winget install --id astral-sh.uv`
Expected: prints a path like `/c/Users/davie/.local/bin/uv`. If missing, install via winget. Confirm version ≥ 0.5 with `uv --version`.

- [ ] **Step 1.2: Pin Python 3.12**

Create `.python-version`:
```
3.12
```

Run: `uv python install 3.12`
Expected: downloads CPython 3.12 into uv's managed location.

- [ ] **Step 1.3: Write root `pyproject.toml`**

```toml
[project]
name = "algo-betting"
version = "0.0.1"
requires-python = ">=3.12,<3.13"
description = "Agentic algorithmic betting ecosystem for Betfair + Kalshi"

[tool.uv.workspace]
members = ["services/common", "services/ingestion"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
    "mypy>=1.13",
    "pre-commit>=4.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["services/common/tests", "services/ingestion/tests"]
```

- [ ] **Step 1.4: Write `ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = []

[format]
quote-style = "double"
```

- [ ] **Step 1.5: Write `mypy.ini`**

```ini
[mypy]
python_version = 3.12
strict = True
warn_unused_configs = True
disallow_untyped_defs = True
no_implicit_optional = True
plugins = pydantic.mypy

[mypy-tests.*]
disallow_untyped_defs = False
```

- [ ] **Step 1.6: Extend `.gitignore`**

Append these lines (don't overwrite — the file already exists):
```
.venv/
__pycache__/
*.pyc
.mypy_cache/
.pytest_cache/
.ruff_cache/
dist/
*.egg-info/
.env
!.env.example
```

- [ ] **Step 1.7: Run `uv sync`**

Run: `uv sync`
Expected: creates `.venv/` and `uv.lock`. Exit code 0.

- [ ] **Step 1.8: Commit**

```bash
git add pyproject.toml .python-version ruff.toml mypy.ini .gitignore uv.lock
git commit -m "chore: initialise uv workspace with ruff/mypy/pytest baseline"
```

---

## Task 2: Write Docker Compose stack (TimescaleDB + Redis)

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.dockerignore`

- [ ] **Step 2.1: Write `.env.example`**

```bash
# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=algobet
POSTGRES_USER=algobet
POSTGRES_PASSWORD=devpassword

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Service identity (used by bus consumer groups)
SERVICE_NAME=ingestion-dev
```

- [ ] **Step 2.2: Write `.dockerignore`**

```
.venv/
__pycache__/
*.pyc
.mypy_cache/
.pytest_cache/
.ruff_cache/
.git/
.github/
wiki/
docs/
```

- [ ] **Step 2.3: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-algobet}
      POSTGRES_USER: ${POSTGRES_USER:-algobet}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpassword}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-algobet}"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 2.4: Bring the stack up**

Run: `docker compose up -d`
Expected: `postgres` and `redis` containers show `Started` and `healthy` within ~15 seconds. Verify with `docker compose ps` — both services `Up (healthy)`.

- [ ] **Step 2.5: Verify services reachable**

Run: `docker compose exec postgres psql -U algobet -d algobet -c "SELECT 1;"`
Expected: returns `1` in a one-row table.

Run: `docker compose exec redis redis-cli ping`
Expected: `PONG`.

- [ ] **Step 2.6: Bring the stack down**

Run: `docker compose down`
Expected: containers removed, volumes persist.

- [ ] **Step 2.7: Commit**

```bash
git add docker-compose.yml .env.example .dockerignore
git commit -m "feat(infra): add docker-compose for TimescaleDB + Redis"
```

---

## Task 3: Database migrations (strategy registry schema from design spec)

**Files:**
- Create: `scripts/db/migrations/0001_enable_timescaledb.sql`
- Create: `scripts/db/migrations/0002_strategy_registry.sql`
- Create: `scripts/migrate.py`
- Create: `services/common/pyproject.toml`
- Create: `services/common/src/algobet_common/__init__.py`

- [ ] **Step 3.1: Scaffold the common package**

Create `services/common/pyproject.toml`:
```toml
[project]
name = "algobet-common"
version = "0.0.1"
requires-python = ">=3.12,<3.13"
dependencies = [
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "redis>=5.2",
    "asyncpg>=0.30",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/algobet_common"]
```

Create `services/common/src/algobet_common/__init__.py`:
```python
"""Shared infrastructure for algo-betting services."""

__version__ = "0.0.1"
```

Run: `uv sync`
Expected: installs pydantic, redis, asyncpg into the venv. Exit 0.

- [ ] **Step 3.2: Write migration 0001 (TimescaleDB extension + bookkeeping)**

Create `scripts/db/migrations/0001_enable_timescaledb.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version       text PRIMARY KEY,
    applied_at    timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 3.3: Write migration 0002 (strategy registry — direct from design spec §4)**

Create `scripts/db/migrations/0002_strategy_registry.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE strategies (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug         text NOT NULL UNIQUE,
    status       text NOT NULL CHECK (status IN (
                   'hypothesis', 'backtesting', 'paper',
                   'awaiting-approval', 'live', 'retired')),
    parameters   jsonb NOT NULL DEFAULT '{}'::jsonb,
    wiki_path    text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    approved_at  timestamptz,
    approved_by  text
);

CREATE INDEX idx_strategies_status ON strategies (status);

CREATE TABLE strategy_runs (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id  uuid NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    mode         text NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    metrics      jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_strategy_runs_strategy_id ON strategy_runs (strategy_id);
CREATE INDEX idx_strategy_runs_mode ON strategy_runs (mode);

CREATE TABLE orders (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id    uuid NOT NULL REFERENCES strategies(id),
    run_id         uuid NOT NULL REFERENCES strategy_runs(id),
    mode           text NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
    venue          text NOT NULL CHECK (venue IN ('betfair', 'kalshi')),
    market_id      text NOT NULL,
    side           text NOT NULL CHECK (side IN ('back', 'lay', 'yes', 'no')),
    stake          numeric(12, 4) NOT NULL,
    price          numeric(10, 4) NOT NULL,
    status         text NOT NULL CHECK (status IN (
                     'pending', 'placed', 'partially_filled',
                     'filled', 'cancelled', 'rejected')),
    placed_at      timestamptz,
    filled_at      timestamptz,
    filled_price   numeric(10, 4),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_orders_strategy_id ON orders (strategy_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_venue_market ON orders (venue, market_id);
```

- [ ] **Step 3.4: Write the test for the migration runner (failing)**

Create `services/common/tests/__init__.py` (empty).

Create `services/common/tests/test_migrate.py`:
```python
import asyncio
from pathlib import Path

import asyncpg
import pytest

from scripts.migrate import apply_migrations, load_migrations


def test_load_migrations_returns_sorted_by_version() -> None:
    migrations_dir = Path("scripts/db/migrations")
    migrations = load_migrations(migrations_dir)
    assert [m.version for m in migrations] == ["0001", "0002"]
    assert "timescaledb" in migrations[0].sql.lower()


@pytest.mark.asyncio
async def test_apply_migrations_creates_strategies_table(postgres_dsn: str) -> None:
    await apply_migrations(postgres_dsn, Path("scripts/db/migrations"))

    conn = await asyncpg.connect(postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT to_regclass('strategies') AS tbl"
        )
        assert row["tbl"] == "strategies"

        versions = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        assert [r["version"] for r in versions] == ["0001", "0002"]
    finally:
        await conn.close()
```

Create `services/common/tests/conftest.py`:
```python
import os
from collections.abc import AsyncIterator

import asyncpg
import pytest


@pytest.fixture
def postgres_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "algobet")
    password = os.environ.get("POSTGRES_PASSWORD", "devpassword")
    db = os.environ.get("POSTGRES_DB", "algobet")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(autouse=True)
async def _reset_db(postgres_dsn: str) -> AsyncIterator[None]:
    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute("""
            DROP TABLE IF EXISTS orders CASCADE;
            DROP TABLE IF EXISTS strategy_runs CASCADE;
            DROP TABLE IF EXISTS strategies CASCADE;
            DROP TABLE IF EXISTS schema_migrations CASCADE;
        """)
    finally:
        await conn.close()
    yield
```

- [ ] **Step 3.5: Run the test — confirm it fails**

Run: `docker compose up -d postgres && uv run pytest services/common/tests/test_migrate.py -v`
Expected: `ImportError: cannot import name 'apply_migrations' from 'scripts.migrate'` (module doesn't exist yet).

- [ ] **Step 3.6: Implement `scripts/migrate.py` (minimal pass)**

Create `scripts/migrate.py`:
```python
"""Apply ordered SQL migrations from scripts/db/migrations."""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg

_VERSION_RE = re.compile(r"^(\d{4})_.+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str


def load_migrations(migrations_dir: Path) -> list[Migration]:
    migrations: list[Migration] = []
    for entry in sorted(migrations_dir.iterdir()):
        match = _VERSION_RE.match(entry.name)
        if not match:
            continue
        migrations.append(
            Migration(
                version=match.group(1),
                path=entry,
                sql=entry.read_text(encoding="utf-8"),
            )
        )
    return migrations


async def apply_migrations(dsn: str, migrations_dir: Path) -> None:
    migrations = load_migrations(migrations_dir)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        already_applied = {
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_migrations")
        }
        for m in migrations:
            if m.version in already_applied:
                continue
            async with conn.transaction():
                await conn.execute(m.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    m.version,
                )
    finally:
        await conn.close()


def _dsn_from_env() -> str:
    import os
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "algobet")
    password = os.environ.get("POSTGRES_PASSWORD", "devpassword")
    db = os.environ.get("POSTGRES_DB", "algobet")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


if __name__ == "__main__":
    dsn = _dsn_from_env()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scripts/db/migrations")
    asyncio.run(apply_migrations(dsn, target))
    print(f"Applied migrations from {target}")
```

Create `scripts/__init__.py` (empty) so tests can import.

- [ ] **Step 3.7: Run test — confirm it passes**

Run: `uv run pytest services/common/tests/test_migrate.py -v`
Expected: 2 passed.

- [ ] **Step 3.8: Manual sanity check**

Run: `uv run python -m scripts.migrate`
Expected: prints `Applied migrations from scripts/db/migrations`.

**Note:** use `python -m scripts.migrate` (not `python scripts/migrate.py`) so the repo root is on `sys.path` and `scripts` resolves as a package. Same applies to `scripts.smoke` in Task 9.

Run: `docker compose exec postgres psql -U algobet -d algobet -c "\dt"`
Expected: lists `strategies`, `strategy_runs`, `orders`, `schema_migrations`.

- [ ] **Step 3.9: Commit**

```bash
git add scripts/db/migrations scripts/migrate.py scripts/__init__.py \
        services/common/pyproject.toml services/common/src services/common/tests uv.lock
git commit -m "feat(db): add strategy registry schema + migration runner"
```

---

## Task 4: Config loader (pydantic-settings)

**Files:**
- Create: `services/common/src/algobet_common/config.py`
- Create: `services/common/tests/test_config.py`

- [ ] **Step 4.1: Write the failing test**

Create `services/common/tests/test_config.py`:
```python
import pytest

from algobet_common.config import Settings


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.example")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "testdb")
    monkeypatch.setenv("POSTGRES_USER", "tester")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("REDIS_HOST", "redis.example")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("SERVICE_NAME", "unit-test")

    settings = Settings()

    assert settings.postgres_dsn == "postgresql://tester:secret@db.example:5433/testdb"
    assert settings.redis_url == "redis://redis.example:6380/0"
    assert settings.service_name == "unit-test"


def test_settings_requires_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
```

- [ ] **Step 4.2: Run test — confirm it fails**

Run: `uv run pytest services/common/tests/test_config.py -v`
Expected: `ImportError` — `algobet_common.config` not found.

- [ ] **Step 4.3: Implement `config.py`**

Create `services/common/src/algobet_common/config.py`:
```python
"""Environment-driven settings for all services."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "algobet"
    postgres_user: str = "algobet"
    postgres_password: str = "devpassword"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    service_name: str = Field(..., description="Identifier used for consumer groups and logs.")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
```

- [ ] **Step 4.4: Run test — confirm it passes**

Run: `uv run pytest services/common/tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 4.5: Commit**

```bash
git add services/common/src/algobet_common/config.py services/common/tests/test_config.py
git commit -m "feat(common): add env-driven Settings loader"
```

---

## Task 5: Bus message schemas (pydantic models matching design spec)

**Files:**
- Create: `services/common/src/algobet_common/schemas.py`
- Create: `services/common/tests/test_schemas.py`

- [ ] **Step 5.1: Write failing tests**

Create `services/common/tests/test_schemas.py`:
```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from algobet_common.schemas import MarketData, OrderSide, OrderSignal, Venue


def test_market_data_roundtrip() -> None:
    msg = MarketData(
        venue=Venue.BETFAIR,
        market_id="1.234",
        timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        bids=[(Decimal("2.50"), Decimal("100.0"))],
        asks=[(Decimal("2.52"), Decimal("80.0"))],
        last_trade=None,
    )
    as_json = msg.model_dump_json()
    restored = MarketData.model_validate_json(as_json)
    assert restored == msg


def test_order_signal_requires_mode() -> None:
    with pytest.raises(ValidationError):
        OrderSignal(  # type: ignore[call-arg]
            strategy_id="abc",
            venue=Venue.BETFAIR,
            market_id="1.234",
            side=OrderSide.BACK,
            stake=Decimal("10.0"),
            price=Decimal("2.5"),
        )


def test_order_signal_rejects_non_positive_stake() -> None:
    with pytest.raises(ValidationError):
        OrderSignal(
            strategy_id="abc",
            mode="paper",
            venue=Venue.BETFAIR,
            market_id="1.234",
            side=OrderSide.BACK,
            stake=Decimal("0"),
            price=Decimal("2.5"),
        )
```

- [ ] **Step 5.2: Run test — confirm it fails**

Run: `uv run pytest services/common/tests/test_schemas.py -v`
Expected: `ImportError` — module missing.

- [ ] **Step 5.3: Implement `schemas.py`**

Create `services/common/src/algobet_common/schemas.py`:
```python
"""Pydantic schemas for Redis Streams bus messages.

These mirror the contracts in docs/superpowers/specs/2026-04-18-algo-betting-design.md.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Venue(StrEnum):
    BETFAIR = "betfair"
    KALSHI = "kalshi"


class OrderSide(StrEnum):
    BACK = "back"
    LAY = "lay"
    YES = "yes"
    NO = "no"


class _BaseMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketData(_BaseMessage):
    venue: Venue
    market_id: str
    timestamp: datetime
    bids: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    asks: list[tuple[Decimal, Decimal]] = Field(default_factory=list)
    last_trade: Decimal | None = None


class OrderSignal(_BaseMessage):
    strategy_id: str
    mode: Literal["paper", "live"]
    venue: Venue
    market_id: str
    side: OrderSide
    stake: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)


class ExecutionResult(_BaseMessage):
    order_id: str
    strategy_id: str
    mode: Literal["paper", "live"]
    status: Literal["placed", "partially_filled", "filled", "cancelled", "rejected"]
    filled_stake: Decimal = Decimal("0")
    filled_price: Decimal | None = None
    timestamp: datetime


class RiskAlert(_BaseMessage):
    source: str
    severity: Literal["info", "warn", "critical"]
    message: str
    timestamp: datetime
```

- [ ] **Step 5.4: Run test — confirm it passes**

Run: `uv run pytest services/common/tests/test_schemas.py -v`
Expected: 3 passed.

- [ ] **Step 5.5: Commit**

```bash
git add services/common/src/algobet_common/schemas.py services/common/tests/test_schemas.py
git commit -m "feat(common): add pydantic schemas for bus messages"
```

---

## Task 6: Redis Streams bus client

**Files:**
- Create: `services/common/src/algobet_common/bus.py`
- Create: `services/common/tests/test_bus.py`

- [ ] **Step 6.1: Write failing tests**

Create `services/common/tests/test_bus.py`:
```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData, Venue


@pytest.mark.asyncio
async def test_publish_and_consume_roundtrip(redis_url: str) -> None:
    client = BusClient(redis_url, service_name="test-service")
    await client.connect()
    try:
        msg = MarketData(
            venue=Venue.BETFAIR,
            market_id="test-market",
            timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
            bids=[(Decimal("1.5"), Decimal("50.0"))],
            asks=[(Decimal("1.6"), Decimal("30.0"))],
        )
        await client.publish(Topic.MARKET_DATA, msg)

        received = [
            received async for received in client.consume(
                Topic.MARKET_DATA, MarketData, count=1, block_ms=2000
            )
        ]
        assert len(received) == 1
        assert received[0].market_id == "test-market"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_consumer_group_isolation(redis_url: str) -> None:
    """Different service names form different consumer groups."""
    publisher = BusClient(redis_url, service_name="pub")
    await publisher.connect()
    try:
        msg = MarketData(
            venue=Venue.KALSHI,
            market_id="isolation-test",
            timestamp=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        )
        await publisher.publish(Topic.MARKET_DATA, msg)
    finally:
        await publisher.close()

    # Two independent consumers should both see the message
    for name in ("svc-a", "svc-b"):
        c = BusClient(redis_url, service_name=name)
        await c.connect()
        try:
            received = [
                m async for m in c.consume(
                    Topic.MARKET_DATA, MarketData, count=1, block_ms=2000
                )
            ]
            assert any(m.market_id == "isolation-test" for m in received)
        finally:
            await c.close()
```

Add to `services/common/tests/conftest.py`:
```python
@pytest.fixture
def redis_url() -> str:
    host = os.environ.get("REDIS_HOST", "localhost")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/15"  # DB 15 = isolated test db


@pytest.fixture(autouse=True)
async def _flush_redis(redis_url: str) -> AsyncIterator[None]:
    import redis.asyncio as redis
    client = redis.from_url(redis_url)
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield
```

- [ ] **Step 6.2: Run test — confirm it fails**

Run: `uv run pytest services/common/tests/test_bus.py -v`
Expected: `ImportError: cannot import name 'BusClient' from 'algobet_common.bus'`.

- [ ] **Step 6.3: Implement `bus.py`**

Create `services/common/src/algobet_common/bus.py`:
```python
"""Thin async wrapper around Redis Streams for service-to-service messaging.

The bus is the only path between services. Every service constructs one
BusClient with its service_name; publish() emits to a topic, consume()
reads via consumer-group semantics so multiple replicas share work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import TypeVar

import redis.asyncio as redis
from pydantic import BaseModel


class Topic(StrEnum):
    MARKET_DATA = "market.data"
    ORDER_SIGNALS = "order.signals"
    ORDER_SIGNALS_APPROVED = "order.signals.approved"
    EXECUTION_RESULTS = "execution.results"
    RESEARCH_EVENTS = "research.events"
    RISK_ALERTS = "risk.alerts"


M = TypeVar("M", bound=BaseModel)


class BusClient:
    def __init__(self, url: str, service_name: str) -> None:
        self._url = url
        self._service = service_name
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("BusClient not connected — call connect() first")
        return self._client

    async def publish(self, topic: Topic, message: BaseModel) -> str:
        client = self._require()
        payload = {"json": message.model_dump_json()}
        return await client.xadd(topic.value, payload)

    async def _ensure_group(self, topic: Topic) -> None:
        client = self._require()
        try:
            await client.xgroup_create(
                name=topic.value,
                groupname=self._service,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self,
        topic: Topic,
        model: type[M],
        count: int = 10,
        block_ms: int = 5000,
    ) -> AsyncIterator[M]:
        """Yield parsed messages from topic. Exits after one XREADGROUP batch."""
        client = self._require()
        await self._ensure_group(topic)
        consumer = f"{self._service}-0"
        response = await client.xreadgroup(
            groupname=self._service,
            consumername=consumer,
            streams={topic.value: ">"},
            count=count,
            block=block_ms,
        )
        if not response:
            return
        for _stream, entries in response:
            for entry_id, fields in entries:
                try:
                    yield model.model_validate_json(fields["json"])
                finally:
                    await client.xack(topic.value, self._service, entry_id)
```

- [ ] **Step 6.4: Run test — confirm it passes**

Run: `docker compose up -d redis && uv run pytest services/common/tests/test_bus.py -v`
Expected: 2 passed.

- [ ] **Step 6.5: Commit**

```bash
git add services/common/src/algobet_common/bus.py services/common/tests/test_bus.py \
        services/common/tests/conftest.py
git commit -m "feat(common): add Redis Streams bus client with consumer groups"
```

---

## Task 7: Postgres pool client

**Files:**
- Create: `services/common/src/algobet_common/db.py`
- Create: `services/common/tests/test_db.py`

- [ ] **Step 7.1: Write failing tests**

Create `services/common/tests/test_db.py`:
```python
import pytest

from algobet_common.db import Database


@pytest.mark.asyncio
async def test_database_pool_roundtrip(postgres_dsn: str) -> None:
    db = Database(postgres_dsn)
    await db.connect()
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 AS value")
            assert row["value"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_database_acquire_before_connect_raises(postgres_dsn: str) -> None:
    db = Database(postgres_dsn)
    with pytest.raises(RuntimeError):
        async with db.acquire():
            pass
```

- [ ] **Step 7.2: Run test — confirm it fails**

Run: `uv run pytest services/common/tests/test_db.py -v`
Expected: `ImportError`.

- [ ] **Step 7.3: Implement `db.py`**

Create `services/common/src/algobet_common/db.py`:
```python
"""asyncpg connection pool wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


class Database:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=self._min_size, max_size=self._max_size
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        async with self._pool.acquire() as conn:
            yield conn
```

- [ ] **Step 7.4: Run test — confirm it passes**

Run: `uv run pytest services/common/tests/test_db.py -v`
Expected: 2 passed.

- [ ] **Step 7.5: Commit**

```bash
git add services/common/src/algobet_common/db.py services/common/tests/test_db.py
git commit -m "feat(common): add asyncpg pool wrapper"
```

---

## Task 8: Ingestion service skeleton (hello-world publisher)

**Files:**
- Create: `services/ingestion/pyproject.toml`
- Create: `services/ingestion/src/ingestion/__init__.py`
- Create: `services/ingestion/src/ingestion/__main__.py`
- Create: `services/ingestion/tests/__init__.py`
- Create: `services/ingestion/tests/test_hello.py`

- [ ] **Step 8.1: Scaffold the ingestion package**

Create `services/ingestion/pyproject.toml`:
```toml
[project]
name = "ingestion"
version = "0.0.1"
requires-python = ">=3.12,<3.13"
dependencies = [
    "algobet-common",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ingestion"]

[tool.uv.sources]
algobet-common = { workspace = true }
```

Create `services/ingestion/src/ingestion/__init__.py`:
```python
"""Market data ingestion service (scaffold — real feeds come in Phase 2)."""
```

- [ ] **Step 8.2: Write failing test**

Create `services/ingestion/tests/__init__.py` (empty).

Create `services/ingestion/tests/test_hello.py`:
```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from algobet_common.bus import BusClient, Topic
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_dummy_tick


@pytest.mark.asyncio
async def test_publish_dummy_tick_writes_to_market_data(redis_url: str) -> None:
    bus = BusClient(redis_url, service_name="ingestion-test")
    await bus.connect()
    try:
        await publish_dummy_tick(bus, market_id="smoke-1.234")

        received = [
            m async for m in bus.consume(
                Topic.MARKET_DATA, MarketData, count=1, block_ms=2000
            )
        ]
        assert received[0].market_id == "smoke-1.234"
        assert received[0].bids[0][0] == Decimal("2.50")
    finally:
        await bus.close()
```

Add a `conftest.py` to `services/ingestion/tests/` that reuses the common fixtures:
```python
import os
from collections.abc import AsyncIterator

import pytest


@pytest.fixture
def redis_url() -> str:
    host = os.environ.get("REDIS_HOST", "localhost")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/15"


@pytest.fixture(autouse=True)
async def _flush_redis(redis_url: str) -> AsyncIterator[None]:
    import redis.asyncio as redis
    client = redis.from_url(redis_url)
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield
```

Update root `pyproject.toml` `[tool.pytest.ini_options]`:
```toml
testpaths = ["services/common/tests", "services/ingestion/tests"]
```
(This should already be set from Task 1; verify.)

- [ ] **Step 8.3: Run test — confirm it fails**

Run: `uv sync && uv run pytest services/ingestion/tests -v`
Expected: `ImportError: cannot import name 'publish_dummy_tick' from 'ingestion.__main__'`.

- [ ] **Step 8.4: Implement `__main__.py`**

Create `services/ingestion/src/ingestion/__main__.py`:
```python
"""Ingestion entrypoint.

Phase 1 scaffolding: publishes a single dummy market.data tick so the
end-to-end bus path can be smoke-tested. Real Betfair/Kalshi feeds land
in Phase 2 per the design spec.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.schemas import MarketData, Venue


async def publish_dummy_tick(bus: BusClient, market_id: str = "scaffold.001") -> None:
    tick = MarketData(
        venue=Venue.BETFAIR,
        market_id=market_id,
        timestamp=datetime.now(UTC),
        bids=[(Decimal("2.50"), Decimal("100.0"))],
        asks=[(Decimal("2.52"), Decimal("80.0"))],
    )
    await bus.publish(Topic.MARKET_DATA, tick)


async def _main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()
    try:
        await publish_dummy_tick(bus)
        print(f"[{settings.service_name}] published dummy tick to {Topic.MARKET_DATA.value}")
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 8.5: Run test — confirm it passes**

Run: `uv run pytest services/ingestion/tests -v`
Expected: 1 passed.

- [ ] **Step 8.6: Manual end-to-end check**

Ensure `.env` exists (copy from `.env.example` if not). Run:
```bash
docker compose up -d
uv run python -m ingestion
```
(`python -m ingestion` runs `services/ingestion/src/ingestion/__main__.py` — installed into the workspace venv by `uv sync`.)
Expected: prints `[ingestion-dev] published dummy tick to market.data`.

Verify in Redis:
```bash
docker compose exec redis redis-cli XLEN market.data
```
Expected: `(integer) 1` or higher.

- [ ] **Step 8.7: Commit**

```bash
git add services/ingestion uv.lock
git commit -m "feat(ingestion): add scaffold service publishing a dummy market.data tick"
```

---

## Task 9: End-to-end smoke script

**Files:**
- Create: `scripts/smoke.py`

- [ ] **Step 9.1: Write `scripts/smoke.py`**

```python
"""End-to-end smoke test: migrate → publish → consume → assert.

Run with `uv run python scripts/smoke.py`. Exits 0 on success, non-zero on
any failure. Used locally before committing and by CI.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from algobet_common.bus import BusClient, Topic
from algobet_common.config import Settings
from algobet_common.db import Database
from algobet_common.schemas import MarketData
from ingestion.__main__ import publish_dummy_tick
from scripts.migrate import apply_migrations


async def _main() -> int:
    settings = Settings()  # type: ignore[call-arg]

    print("1/4 applying migrations...")
    await apply_migrations(settings.postgres_dsn, Path("scripts/db/migrations"))

    print("2/4 verifying strategy registry tables exist...")
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT to_regclass('strategies') AS tbl")
            if row["tbl"] != "strategies":
                print("ERROR: strategies table missing", file=sys.stderr)
                return 1
    finally:
        await db.close()

    print("3/4 publishing dummy tick...")
    bus = BusClient(settings.redis_url, settings.service_name)
    await bus.connect()
    try:
        await publish_dummy_tick(bus, market_id="smoke.e2e")

        print("4/4 consuming dummy tick...")
        received = [
            m async for m in bus.consume(
                Topic.MARKET_DATA, MarketData, count=10, block_ms=3000
            )
        ]
        if not any(m.market_id == "smoke.e2e" for m in received):
            print("ERROR: smoke tick not received", file=sys.stderr)
            return 1
    finally:
        await bus.close()

    print("OK — scaffolding is wired end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

- [ ] **Step 9.2: Run it manually**

Ensure stack is up: `docker compose up -d`.
Copy `.env.example` → `.env` if not present.

Run: `uv run python -m scripts.smoke`
Expected:
```
1/4 applying migrations...
2/4 verifying strategy registry tables exist...
3/4 publishing dummy tick...
4/4 consuming dummy tick...
OK — scaffolding is wired end-to-end
```
Exit code 0.

- [ ] **Step 9.3: Commit**

```bash
git add scripts/smoke.py
git commit -m "feat(scripts): add end-to-end scaffolding smoke script"
```

---

## Task 10: Pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 10.1: Write config**

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.9
          - pydantic-settings>=2.6
        files: ^services/

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
        args: [--maxkb=500]
```

- [ ] **Step 10.2: Install and run hooks**

Run: `uv run pre-commit install`
Expected: `pre-commit installed at .git/hooks/pre-commit`.

Run: `uv run pre-commit run --all-files`
Expected: initial run may fix trailing whitespace / EOF newlines. Re-run until clean. All hooks pass.

- [ ] **Step 10.3: Commit**

```bash
git add .pre-commit-config.yaml
# any files pre-commit modified will need re-adding
git add -u
git commit -m "chore: add pre-commit hooks (ruff, mypy, standard checks)"
```

---

## Task 11: GitHub Actions CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 11.1: Write CI workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.x"
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.x"
      - run: uv sync
      - run: uv run mypy services

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_DB: algobet
          POSTGRES_USER: algobet
          POSTGRES_PASSWORD: devpassword
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U algobet"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    env:
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      POSTGRES_DB: algobet
      POSTGRES_USER: algobet
      POSTGRES_PASSWORD: devpassword
      REDIS_HOST: localhost
      REDIS_PORT: 6379
      SERVICE_NAME: ci-test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.x"
      - run: uv sync
      - run: uv run pytest -v

  smoke:
    runs-on: ubuntu-latest
    needs: [lint, typecheck, test]
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_DB: algobet
          POSTGRES_USER: algobet
          POSTGRES_PASSWORD: devpassword
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U algobet"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    env:
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      POSTGRES_DB: algobet
      POSTGRES_USER: algobet
      POSTGRES_PASSWORD: devpassword
      REDIS_HOST: localhost
      REDIS_PORT: 6379
      SERVICE_NAME: ci-smoke
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.x"
      - run: uv sync
      - run: uv run python -m scripts.smoke
```

- [ ] **Step 11.2: Validate workflow syntax locally**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output, exit 0.

- [ ] **Step 11.3: Commit and push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint + typecheck + test + smoke workflow"
git push origin main
```

Check the GitHub Actions tab in the repo. Expected: all four jobs green on first run. If any fail, fix the root cause and push again — **do not** skip hooks or disable checks.

---

## Task 12: Update README + CLAUDE.md with Phase 1 status

**Files:**
- Modify: `C:\Users\davie\algo-betting\README.md`
- Modify: `C:\Users\davie\algo-betting\CLAUDE.md`

- [ ] **Step 12.1: Add "Local development" section to README**

Prepend a "Local development" section to `README.md` (do not overwrite existing content). Example content:
```markdown
## Local development

Requirements: Docker, uv (≥0.5), Python 3.12.

```bash
uv sync                                  # install all workspace deps
cp .env.example .env                     # adjust if ports collide
docker compose up -d                     # postgres + redis
uv run python -m scripts.migrate         # apply SQL migrations
uv run python -m scripts.smoke           # end-to-end sanity
uv run pytest -v                         # run the test suite
```

CI runs the same `smoke.py` in `.github/workflows/ci.yml` against service containers.
```

- [ ] **Step 12.2: Add Phase 1 status note to CLAUDE.md**

Append to the end of `CLAUDE.md`:
```markdown
## Phase 1 Status

Scaffolding complete. The following exists:

- `docker compose up` runs TimescaleDB + Redis locally
- `uv run python -m scripts.migrate` applies SQL migrations (strategies / strategy_runs / orders)
- `algobet_common` package: Settings, pydantic schemas (MarketData, OrderSignal, ExecutionResult, RiskAlert), BusClient (Redis Streams), Database (asyncpg pool)
- `ingestion` service is a hello-world publisher. Real Betfair/Kalshi code is Phase 2.
- CI runs lint + typecheck + tests + end-to-end smoke on push.

Every subsequent service (simulator, risk manager, orchestrator, dashboard, execution-engine) should be a new member of the uv workspace under `services/` and reuse `algobet_common`. Never re-implement bus or DB logic in a service.
```

- [ ] **Step 12.3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: note Phase 1 scaffolding complete in README + CLAUDE.md"
```

---

## Verification — how to confirm Phase 1 is done

Run each of these on a clean clone:

1. **Dependencies install:** `uv sync` → exit 0.
2. **Stack comes up:** `docker compose up -d` → `docker compose ps` shows both services `(healthy)`.
3. **Migrations apply:** `uv run python -m scripts.migrate` → `docker compose exec postgres psql -U algobet -d algobet -c "\dt"` lists `strategies`, `strategy_runs`, `orders`, `schema_migrations`.
4. **Tests pass:** `uv run pytest -v` → all green.
5. **Lint + types clean:** `uv run ruff check . && uv run ruff format --check . && uv run mypy services` → exit 0.
6. **End-to-end smoke:** `uv run python -m scripts.smoke` → exits 0 with `OK — scaffolding is wired end-to-end`.
7. **CI green:** GitHub Actions on the main branch shows all four jobs passing.

If any of these fail, do not mark Phase 1 done — fix the root cause. Do not add `|| true`, `--no-verify`, or skip steps.

---

## Critical files (for executor reference)

- `C:\Users\davie\algo-betting\docs\superpowers\specs\2026-04-18-algo-betting-design.md` — design spec (source of truth for schemas and service contracts)
- `C:\Users\davie\algo-betting\CLAUDE.md` — project invariants
- `C:\Users\davie\algo-betting\docs\superpowers\plans\2026-04-18-obsidian-mcp-and-research.md` — prerequisite plan for Research Orchestrator (Phase 7+); not needed for Phase 1

## Out of scope (explicit non-goals)

- Rust execution engine scaffolding — deferred to item #9's plan per user decision
- Real Betfair or Kalshi API integration — Phase 2
- Market simulator, risk manager, orchestrator, dashboard — each is its own plan
- Production deployment (Hetzner / Oracle / QuantVPS) — later plan
- Alembic — raw SQL migrations are enough at this stage; revisit if schema complexity grows
- TimescaleDB hypertables for market-data ticks — added when ingestion writes real ticks in Phase 2
