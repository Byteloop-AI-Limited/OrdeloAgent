"""Web price audit floor (plans/bnat-menu-undercut-plan.md D10): discounted_price if numeric, else price.

The SQL expression is checked on the isolated Postgres when ORDELO_TEST_DB_URI is set (a local throwaway server,
see .claude/skills/ordelo-sql-test-db); the sweep wiring is checked offline with a fake query.
"""

import os
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest

from utils_common.web_ordering import monitoring

URI = os.environ.get("ORDELO_TEST_DB_URI")


@pytest.mark.skipif(not URI, reason="ORDELO_TEST_DB_URI not set (isolated Postgres required)")
def test_menu_floor_prefers_numeric_discounted_price():
    import psycopg

    assert urlparse(URI).hostname in ("localhost", "127.0.0.1", "::1")
    with psycopg.connect(URI) as conn:
        conn.execute(
            "CREATE TEMP TABLE m (title text, price numeric, discounted_price text);"
            "INSERT INTO m VALUES ('discounted', 9.49, '7.99'), ('stray', 9.49, 'n/a'),"
            " ('plain', 4.99, NULL), ('two rows', 6.00, '5.50'), ('two rows', 5.00, NULL)"
        )
        rows = conn.execute(
            f"SELECT title, {monitoring.MENU_FLOOR} FROM m GROUP BY title ORDER BY title"
        ).fetchall()
    assert {t: str(v) for t, v in rows} == {
        "discounted": "7.99",
        "plain": "4.99",
        "stray": "9.49",
        "two rows": "5.00",
    }


async def test_sweep_uses_menu_floor_and_flags_below_discounted_price(monkeypatch):
    calls = []

    async def fake_query(sql, params=()):
        calls.append(sql)
        if sql.startswith("INSERT INTO web_monitor_run"):
            return [{"run_day": "today"}]
        if "AS menu_price" in sql and "bnat_menu" in sql:
            return [
                {"order_number": "BNAT-1", "product_name": "A", "price": 7.99, "menu_price": 7.99},
                {"order_number": "BNAT-2", "product_name": "B", "price": 7.00, "menu_price": 7.99},
            ]
        return []

    monkeypatch.setattr(monitoring, "query", fake_query)
    monkeypatch.setattr(monitoring, "one", AsyncMock(return_value=None))
    monkeypatch.setattr(monitoring, "RESTAURANTS", {"BNAT": {}})
    notify = AsyncMock()
    import watomation.routers.delivery_hooks as delivery_hooks

    monkeypatch.setattr(delivery_hooks, "notify_overwatch", notify)
    await monitoring.sweep()
    audit = next(sql for sql in calls if "AS menu_price" in sql)
    assert monitoring.MENU_FLOOR in audit
    assert "min(m.price)" not in audit
    assert notify.await_args.args[0] == "Web price audit: check orders BNAT-2"
