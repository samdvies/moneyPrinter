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
