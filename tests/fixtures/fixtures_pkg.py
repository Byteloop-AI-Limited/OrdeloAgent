"""Pytest plugin entry point that re-exports all fixtures.

Loaded by ``tests/conftest.py`` via ``pytest_plugins``. Each fixture lives in a
focused module under ``tests/fixtures/`` for readability; this file simply
re-exports them so ``conftest`` only references one plugin.

Key Functions:
  - (re-exports of fixtures via star imports)
"""

from __future__ import annotations

# Each module below defines one or more pytest fixtures. They are picked up by
# pytest's plugin system through this module's namespace.
from tests.fixtures.fake_supabase import *  # noqa: F401,F403
from tests.fixtures.fake_pool import *  # noqa: F401,F403
from tests.fixtures.fake_wa import *  # noqa: F401,F403
from tests.fixtures.fake_llm import *  # noqa: F401,F403
from tests.fixtures.builders import *  # noqa: F401,F403
