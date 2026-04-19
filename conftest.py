"""Root conftest: make the repo root importable so `scripts.*` is resolvable."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that `import scripts.migrate` works
# from any test regardless of where pytest is invoked from.
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Re-export shared integration fixtures for all service test suites.
from services.common.tests.conftest import (  # noqa: F401,E402
    _flush_redis,
    postgres_dsn,
    redis_url,
    require_postgres,
    require_redis,
)
