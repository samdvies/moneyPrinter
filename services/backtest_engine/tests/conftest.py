"""pytest conftest for backtest_engine tests.

Import strategy note:
    Every service's ``tests/`` directory is a top-level package named ``tests``
    (see ``services/simulator/tests/__init__.py``). Under
    ``--import-mode=importlib`` (root ``pyproject.toml``), these do not collide
    at collection time, but a relative import like ``from .fixtures import ...``
    inside ``test_harness.py`` resolves against whichever ``tests`` package
    loaded first into ``sys.modules`` — which is non-deterministic across
    services.

    Instead of relying on the ``tests.`` prefix, this conftest prepends the
    service's ``tests/`` directory to ``sys.path`` so ``fixtures`` is
    importable as a top-level package. Tests then use the unambiguous
    ``from fixtures.always_back_below_two import on_tick`` form.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
