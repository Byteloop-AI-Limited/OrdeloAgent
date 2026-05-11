"""In-memory fake for ``psycopg_pool.AsyncConnectionPool`` used by OrdeloAgent.

Production code reaches the pool via ``await pg_settings.get_pool()`` and uses
``async with pool.connection() as conn`` followed by ``conn.cursor()``.

Tests register canned cursor results per SQL fragment and assert which
``execute`` calls were made.

Key Functions:
  - FakeAsyncCursor - records execute(), returns scripted fetch results
  - FakeAsyncConnection - context manager yielding a FakeAsyncCursor
  - FakeAsyncConnectionPool - context manager yielding a FakeAsyncConnection
  - fake_pool - pytest fixture yielding a fresh pool
  - patch_pg_pool - pytest fixture wiring fake into pg_settings.get_pool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import pytest


@dataclass
class _RecordedExec:
    sql: str
    params: Any | None = None


class FakeAsyncCursor:
    """Records execute() calls; returns scripted fetch results."""

    def __init__(self, conn: "FakeAsyncConnection") -> None:
        self._conn = conn
        self._next_rows: list[tuple] = []
        self._next_row: tuple | None = None
        self.rowcount: int = 0

    async def execute(self, sql: str, params: Any | None = None) -> "FakeAsyncCursor":
        rec = _RecordedExec(sql=sql, params=params)
        self._conn.executes.append(rec)

        # Match the SQL fragment to a registered fixture
        for fragment, response in self._conn.pool._sql_responses.items():
            if fragment in sql:
                if isinstance(response, Exception):
                    raise response
                rows = list(response) if isinstance(response, Iterable) else []
                self._next_rows = rows
                self._next_row = rows[0] if rows else None
                self.rowcount = len(rows)
                break
        else:
            self._next_rows = []
            self._next_row = None
            self.rowcount = 0
        return self

    async def fetchone(self):
        return self._next_row

    async def fetchall(self):
        return list(self._next_rows)

    async def __aenter__(self) -> "FakeAsyncCursor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeAsyncConnection:
    """Context manager yielding a single ``FakeAsyncCursor``."""

    def __init__(self, pool: "FakeAsyncConnectionPool") -> None:
        self.pool = pool
        self.executes: list[_RecordedExec] = []

    def cursor(self, *args: Any, **kwargs: Any) -> FakeAsyncCursor:
        return FakeAsyncCursor(self)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def __aenter__(self) -> "FakeAsyncConnection":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeAsyncConnectionPool:
    """Replacement for ``psycopg_pool.AsyncConnectionPool``."""

    def __init__(self) -> None:
        self.closed: bool = False
        self.connections: list[FakeAsyncConnection] = []
        self._sql_responses: dict[str, Any] = {}

    def register_sql(
        self,
        sql_fragment: str,
        rows: list[tuple] | Exception,
    ) -> None:
        """Register canned rows for any SQL containing ``sql_fragment``."""
        self._sql_responses[sql_fragment] = rows

    def connection(self) -> FakeAsyncConnection:
        conn = FakeAsyncConnection(self)
        self.connections.append(conn)
        return conn

    async def open(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    @property
    def all_executes(self) -> list[_RecordedExec]:
        return [e for c in self.connections for e in c.executes]


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_pool() -> FakeAsyncConnectionPool:
    return FakeAsyncConnectionPool()


@pytest.fixture
def patch_pg_pool(monkeypatch, fake_pool) -> FakeAsyncConnectionPool:
    """Wire ``fake_pool`` into ``pg_settings.get_pool``."""
    from config import pg_setting

    async def _fake_get_pool(self):  # noqa: ARG001
        return fake_pool

    monkeypatch.setattr(pg_setting.PgSetting, "get_pool", _fake_get_pool, raising=True)
    return fake_pool
