"""ordelo/pauses.py: the typed wrapper over pause_start / pause_end / pause_current / pause_options (ADR 0013), and the two
text helpers the bots use (duration_label, ends_text).

The rules themselves are proven against Postgres in tests/sql/test_pauses_sql.py; here: argument names, every result
shape, timestamp parsing, and that a malformed response fails loudly.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ordelo import pauses


class FakePauseDb:
    """Returns canned RPC results and records the calls (same result vocabulary as availability/pauses.sql)."""

    def __init__(self, data):
        self.data = data
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, args):
        self.calls.append((name, args))
        return type("Q", (), {"execute": lambda s: type("R", (), {"data": self.data})()})()


@pytest.fixture
def db(monkeypatch):
    def install(data):
        fake = FakePauseDb(data)
        monkeypatch.setattr("ordelo.pauses.client_ordelo_service", fake)
        return fake

    return install


@pytest.mark.parametrize("result", ["paused", "extended"])
async def test_pause_started(db, result):
    fake = db({"result": result, "pause_id": 7, "ends_at": "2026-10-22T18:00:00+00:00"})
    out = await pauses.pause(pauses.RIDER, "447700900501", "6h", by="111")
    assert out.result == result and out.is_paused
    assert out.pause.pause_id == 7 and out.pause.ends_at == datetime.fromisoformat("2026-10-22T18:00:00+00:00")
    assert fake.calls == [("pause_start", {"p_audience": "rider", "p_principal": "447700900501", "p_scope": None,
                                           "p_duration": "6h", "p_via": "telegram", "p_by": "111"})]


@pytest.mark.parametrize("result", ["bad_duration", "bad_audience", "not_admin", "not_allowed"])
async def test_pause_refused(db, result):
    db({"result": result})
    out = await pauses.pause(pauses.REST_ADMIN, "447700900501", "6h", scope="ELAS")
    assert out.result == result and not out.is_paused and out.pause is None


async def test_resume(db):
    fake = db({"result": "resumed", "pause_id": 7})
    assert (await pauses.resume(pauses.RIDER, "447700900501")).result == "resumed"
    assert fake.calls[0] == ("pause_end", {"p_audience": "rider", "p_principal": "447700900501", "p_scope": None,
                                           "p_reason": "resumed"})
    fake = db({"result": "not_paused"})
    assert (await pauses.resume(pauses.RIDER, "447700900501", operator=True)).result == "not_paused"
    assert fake.calls[0][1]["p_reason"] == "operator"


async def test_current(db):
    db({"result": "paused", "pause_id": 3, "starts_at": "2026-10-22T12:00:00+00:00", "ends_at": "2026-10-22T18:00:00+00:00"})
    cur = await pauses.current(pauses.RIDER, "447700900501")
    assert cur.pause_id == 3 and cur.starts_at.hour == 12
    db({"result": "not_paused"})
    assert await pauses.current(pauses.RIDER, "447700900501") is None


async def test_malformed_response_raises(db):
    db(None)
    with pytest.raises(RuntimeError):
        await pauses.pause(pauses.RIDER, "447700900501", "6h")


async def test_options(db):
    fake = db(["6h", "1d", "3d"])
    assert await pauses.options(pauses.RIDER) == ["6h", "1d", "3d"]
    assert fake.calls == [("pause_options", {"p_audience": "rider"})]
    db(None)
    with pytest.raises(RuntimeError):
        await pauses.options(pauses.RIDER)


@pytest.mark.parametrize("key, label", [("6h", "6 hours"), ("1h", "1 hour"), ("1d", "1 day"), ("3d", "3 days"), ("12H", "12 hours")])
def test_duration_label(key, label):
    assert pauses.duration_label(key) == label


def test_ends_text_reads_in_uk_time():
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo("UTC"))  # 13:00 in London (BST)
    assert pauses.ends_text(datetime.fromisoformat("2026-10-22T17:30:00+00:00"), now) == "6:30 PM"
    assert pauses.ends_text(datetime.fromisoformat("2026-10-23T08:05:00+00:00"), now) == "tomorrow 9:05 AM"
    assert pauses.ends_text(datetime.fromisoformat("2026-10-25T12:00:00+00:00"), now) == "Sun 25 Oct, 12:00 PM"  # GMT again
