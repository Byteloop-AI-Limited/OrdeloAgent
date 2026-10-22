"""ordelo.agents.rider_threads: the Python side of the rider thread functions (D46, D47).

The pool is faked with the SQL functions' return shapes (ordelo_datamodels/agent_threads/rider_threads.sql); the SQL itself
is proven in tests/sql/test_rider_threads_sql.py. Every result value is mapped: open -> OpenOutcome; touch / active ->
RiderThread only when OPEN; describe / for_dispatch -> a snapshot open or closed; close -> bool. Unexpected shapes raise.
"""

from __future__ import annotations

import pytest

from ordelo.agents import rider_threads
from ordelo.agents.rider_threads import OpenOutcome, RiderThread

SNAP = {"thread_id": "ORDELO-dispatch-10", "rider_id": "447700900601", "is_active": True, "dispatch_id": 10,
        "order_number": "ELAS-ABCD-1", "dispatch_status": "assigned", "channel": "telegram", "tcid": 555}


@pytest.fixture
def pool(patch_pg_pool, monkeypatch):
    monkeypatch.setattr(rider_threads.project_settings, "rest_ref", "ORDELO")
    return patch_pg_pool


def _last(pool):
    e = pool.all_executes[-1]
    return e.sql, e.params


@pytest.mark.parametrize("result", ["opened", "existing", "closed", "not_found"])
async def test_open_for_dispatch_maps_every_result(pool, result):
    pool.register_sql("rider_thread_open", [({"result": result, "thread_id": "ORDELO-dispatch-10",
                                              "closed": ["ORDELO-old"] if result == "opened" else []},)])
    out = await rider_threads.open_for_dispatch("447700900601", 10)
    assert out == OpenOutcome(result, "ORDELO-dispatch-10", ["ORDELO-old"] if result == "opened" else [])
    assert out.is_new is (result == "opened")
    assert _last(pool) == ("SELECT public.rider_thread_open(%s, %s, %s)", ("ORDELO", "447700900601", 10))


async def test_touch_returns_the_thread_only_when_open(pool):
    pool.register_sql("rider_thread_touch", [({**SNAP, "result": "active"},)])
    assert await rider_threads.touch("ORDELO-dispatch-10") == RiderThread(**SNAP)
    pool.register_sql("rider_thread_touch", [({**SNAP, "is_active": False, "result": "inactive"},)])
    assert await rider_threads.touch("ORDELO-dispatch-10") is None
    pool.register_sql("rider_thread_touch", [({"result": "not_found"},)])
    assert await rider_threads.touch("nope") is None


async def test_active_for_rider_passes_the_touch_flag(pool):
    pool.register_sql("rider_thread_active", [({**SNAP, "result": "active"},)])
    thread = await rider_threads.active_for_rider("447700900601", touch=False)
    assert thread.channel == "telegram" and thread.tcid == 555 and thread.is_dispatch_thread
    assert _last(pool)[1] == ("ORDELO", "447700900601", False)
    pool.register_sql("rider_thread_active", [({"result": "none"},)])
    assert await rider_threads.active_for_rider("447700900601") is None
    assert _last(pool)[1] == ("ORDELO", "447700900601", True)


async def test_a_legacy_thread_is_whatsapp_without_a_dispatch(pool):
    pool.register_sql("rider_thread_active", [({"result": "active", "thread_id": "ORDELO-uuid", "rider_id": "447700900601",
                                                "is_active": True, "dispatch_id": None, "order_number": None,
                                                "dispatch_status": None, "channel": "whatsapp", "tcid": None},)])
    thread = await rider_threads.active_for_rider("447700900601")
    assert thread == RiderThread("ORDELO-uuid", "447700900601") and not thread.is_dispatch_thread


async def test_describe_and_for_dispatch_return_closed_threads_too(pool):
    pool.register_sql("rider_thread_describe", [({**SNAP, "is_active": False, "result": "found"},)])
    assert (await rider_threads.describe("ORDELO-dispatch-10")).is_active is False
    assert _last(pool) == ("SELECT public.rider_thread_describe(%s, NULL)", ("ORDELO-dispatch-10",))
    assert (await rider_threads.for_dispatch(10)).dispatch_id == 10
    assert _last(pool) == ("SELECT public.rider_thread_describe(NULL, %s)", (10,))
    pool.register_sql("rider_thread_describe", [({"result": "not_found"},)])
    assert await rider_threads.for_dispatch(11) is None


async def test_close_reports_whether_it_was_open(pool):
    pool.register_sql("rider_thread_close", [({"result": "closed", "thread_id": "t"},)])
    assert await rider_threads.close("t") is True
    pool.register_sql("rider_thread_close", [({"result": "not_active", "thread_id": "t"},)])
    assert await rider_threads.close("t") is False


async def test_an_unexpected_response_raises(pool):
    pool.register_sql("rider_thread_close", [(None,)])
    with pytest.raises(RuntimeError, match="unexpected rider thread response"):
        await rider_threads.close("t")
