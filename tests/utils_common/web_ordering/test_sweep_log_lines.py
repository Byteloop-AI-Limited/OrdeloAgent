"""Log lines of the pg_cron-woken web sweeps (plans/telegram-rider-invite-alert-schedule.md 5.4-5.5, ADR 0019).

lifecycle.sweep() logs each claimed payment release before cancelling it; monitoring.sweep() logs whether it claimed the
London day or found it already claimed. Offline, with fake query helpers.
"""

from unittest.mock import AsyncMock

import pytest
from loguru import logger

from utils_common.web_ordering import lifecycle, monitoring


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO")
    yield lines
    logger.remove(sink)


async def test_lifecycle_logs_each_claimed_release_before_releasing(monkeypatch, logs):
    async def fake_query(sql, params=()):
        if sql.startswith("UPDATE web_payment_release"):
            return [{"order_number": "TEST-ABCD-1", "attempts": 3}]
        return []

    seen = []

    async def release(order_number, attempts=1):
        seen.append((order_number, attempts, any("release claimed" in line for line in logs)))

    monkeypatch.setattr(lifecycle, "query", fake_query)
    monkeypatch.setattr(lifecycle, "release", release)
    await lifecycle.sweep()
    assert seen == [("TEST-ABCD-1", 3, True)]   # logged before release() ran
    assert any("web lifecycle: release claimed order=TEST-ABCD-1 attempts=3" in line for line in logs)


async def test_lifecycle_with_nothing_due_logs_no_release(monkeypatch, logs):
    monkeypatch.setattr(lifecycle, "query", AsyncMock(return_value=[]))
    release = AsyncMock()
    monkeypatch.setattr(lifecycle, "release", release)
    await lifecycle.sweep()
    release.assert_not_awaited()
    assert not [line for line in logs if "release claimed" in line]


@pytest.mark.parametrize("claimed", [True, False])
async def test_price_audit_logs_the_day_claim_or_that_it_was_already_claimed(monkeypatch, logs, claimed):
    async def fake_query(sql, params=()):
        if sql.startswith("INSERT INTO web_monitor_run"):
            return [{"run_day": params[0]}] if claimed else []
        return []

    monkeypatch.setattr(monitoring, "query", fake_query)
    monkeypatch.setattr(monitoring, "one", AsyncMock(return_value=None))
    monkeypatch.setattr(monitoring, "RESTAURANTS", {})
    await monitoring.sweep()
    text = "\n".join(logs)
    if claimed:
        assert "web price audit: claimed day " in text and "already claimed" not in text
    else:
        assert "already claimed" in text and "web price audit: claimed day" not in text
