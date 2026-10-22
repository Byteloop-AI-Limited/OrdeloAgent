"""ordelo/rider_shift.py: the typed wrapper over rider_set_shift (availability/rider_shift.sql, phase R5).

The rule itself is proven against Postgres in tests/sql/test_rider_shift_sql.py; here: the argument names, every result
shape, and that an unexpected response fails loudly.
"""

from __future__ import annotations

import pytest

from ordelo import rider_shift


class FakeShiftDb:
    def __init__(self, data):
        self.data = data
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, args):
        self.calls.append((name, args))
        return type("Q", (), {"execute": lambda s: type("R", (), {"data": self.data})()})()


@pytest.fixture
def db(monkeypatch):
    def install(data):
        fake = FakeShiftDb(data)
        monkeypatch.setattr("ordelo.rider_shift.client_ordelo_service", fake)
        return fake

    return install


@pytest.mark.parametrize("data, expected", [
    ({"result": "on"}, rider_shift.ShiftOutcome("on")),
    ({"result": "not_active", "status": "inactive"}, rider_shift.ShiftOutcome("not_active", status="inactive")),
    ({"result": "off"}, rider_shift.ShiftOutcome("off")),
    ({"result": "on_job", "order_number": "ELAS-A-1"}, rider_shift.ShiftOutcome("on_job", order_number="ELAS-A-1")),
    ({"result": "not_found"}, rider_shift.ShiftOutcome("not_found")),
])
async def test_every_result(db, data, expected):
    fake = db(data)
    assert await rider_shift.set_shift("447700900501", True) == expected
    assert fake.calls == [("rider_set_shift", {"p_rider_id": "447700900501", "p_on": True})]


@pytest.mark.parametrize("data", [None, {}, {"result": "maybe"}, ["on"]])
async def test_unexpected_response_raises(db, data):
    db(data)
    with pytest.raises(RuntimeError):
        await rider_shift.set_shift("447700900501", False)
