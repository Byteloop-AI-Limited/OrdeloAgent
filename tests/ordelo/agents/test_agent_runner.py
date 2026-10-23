"""Tests for rider agent runner orchestration helpers.

The graph builder, checkpointer, context schema and ordelo.agents.rider_threads (R2: one thread per dispatch) are
patched with lightweight fakes so no Postgres checkpointer or LangGraph runtime is required.

Key Functions:
  - test_is_food_already_picked_up_reads_state_key_via_rpc
  - test_is_food_already_picked_up_false_when_absent_or_not_verified
  - test_is_food_already_picked_up_false_when_rpc_fails
  - test_run_rider_agent_w_custom_msg_builds_messages_updates_state_and_returns_ai_content
  - test_run_never_creates_a_thread
  - test_run_by_dispatch_uses_that_thread_and_refuses_a_closed_one
  - test_run_by_dispatch_falls_back_to_the_open_legacy_thread
  - test_telegram_thread_gets_a_telegram_messenger
  - test_clear_cues_do_not_create_threads
  - test_init_ordelo_graph_updates_initial_state_and_invokes_graph
  - test_init_ordelo_graph_is_idempotent_when_the_hook_fires_again
  - test_init_ordelo_graph_retries_only_thread_acquisition
  - test_init_ordelo_graph_propagates_second_thread_acquisition_failure
  - test_init_ordelo_graph_does_not_retry_non_operational_error
  - test_debug_state_values_returns_shortened_state_values
  - test_debug_thread_fetches_recipient_and_uses_thread_config
  - test_job_end_stale_conversations_uses_supplied_handler
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from psycopg import OperationalError

from ordelo.agents import agent_runner, rider_threads
from ordelo.agents.rider_threads import RiderThread
from tests.channels.telegram.conftest import RecordingSession
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from tests.fixtures.fake_supabase import FakeSupabaseResponse


class _FakeGraph:
    def __init__(self):
        self.updates = []
        self.invocations = []
        self.state = SimpleNamespace(values={"messages": [HumanMessage("hello")], "dispatch_id": 10})

    async def aupdate_state(self, config, values, as_node=None):
        self.updates.append({"config": config, "values": values, "as_node": as_node})

    async def ainvoke(self, input, config, context):
        self.invocations.append({"input": input, "config": config, "context": context})
        return {"messages": [*input["messages"], AIMessage("AI response")]}

    async def aget_state(self, config):
        self.last_state_config = config
        return self.state


class _FakeBuilder:
    def __init__(self, graph):
        self.graph = graph
        self.checkpointers = []

    def compile(self, checkpointer=None):
        self.checkpointers.append(checkpointer)
        return self.graph


def _summary(**overrides) -> DeliverySummary:
    row = {
        "order_number": "ELAS-ABCD-1",
        "rest_id": "REST001",
        "rest_name": "Elai",
        "rest_lon": -0.1278,
        "rest_lat": 51.5074,
        "rest_address": "1 Test Street",
        "town": "London",
        "customer_id": "447400000000",
        "customer_name": "Test Customer",
        "customer_lon": -0.1378,
        "customer_lat": 51.5174,
        "customer_address": "2 Customer Road",
        "status": "assigned",
        "rest_confirmation_code": 11,
        "cust_confirmation_code": 22,
        "pickup_date": date(2026, 5, 9),
        "dt": date(2026, 5, 9),
        "dtts": datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return DeliverySummary(**row)


THREAD = RiderThread(thread_id="ORDELO-dispatch-10", rider_id="RIDER01", dispatch_id=10, order_number="ELAS-ABCD-1")


class _FakeThreads:
    """Stands in for ordelo.agents.rider_threads (the SQL is tested in tests/sql/test_rider_threads_sql.py)."""

    OpenOutcome = rider_threads.OpenOutcome

    def __init__(self):
        self.open_results = ["opened"]
        self.open_calls = []
        self.touched = []
        self.active = THREAD
        self.by_dispatch = THREAD

    async def open_for_dispatch(self, rider_id, dispatch_id):
        self.open_calls.append((rider_id, dispatch_id))
        result = self.open_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return rider_threads.OpenOutcome(result, f"ORDELO-dispatch-{dispatch_id}", [])

    async def touch(self, thread_id):
        self.touched.append(thread_id)
        return THREAD if thread_id == THREAD.thread_id else None

    async def describe(self, thread_id):
        return THREAD if thread_id == THREAD.thread_id else None

    async def for_dispatch(self, dispatch_id):
        return self.by_dispatch

    async def active_for_rider(self, rider_id, touch=True):
        if touch and self.active is not None:
            self.touched.append(self.active.thread_id)
        return self.active


@pytest.fixture
def patched_runner(monkeypatch, patch_pg_pool):
    graph = _FakeGraph()
    builder = _FakeBuilder(graph)
    threads = _FakeThreads()
    monkeypatch.setattr(agent_runner, "builder", builder)
    monkeypatch.setattr(agent_runner, "AsyncPostgresSaver", lambda pool: SimpleNamespace(pool=pool))
    monkeypatch.setattr(agent_runner, "ContextSchema", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(agent_runner, "rider_threads", threads)
    return graph, builder, threads


async def test_is_food_already_picked_up_reads_state_key_via_rpc(patch_supabase_client) -> None:
    patch_supabase_client.register_rpc("get_latest_state", FakeSupabaseResponse(data=True))

    assert await agent_runner.is_food_already_picked_up("RIDER01") is True

    args = patch_supabase_client.rpc_calls[-1].payload["args"]
    assert args["p_recipient"] == "RIDER01"
    assert args["p_state_key"] == "is_restaurant_confirmation_code_verified"
    assert args["p_agent"] == agent_runner.project_settings.rest_ref


@pytest.mark.parametrize("state_value", [False, None])
async def test_is_food_already_picked_up_false_when_absent_or_not_verified(
    patch_supabase_client, state_value
) -> None:
    patch_supabase_client.register_rpc("get_latest_state", FakeSupabaseResponse(data=state_value))

    assert await agent_runner.is_food_already_picked_up("RIDER01") is False


async def test_is_food_already_picked_up_false_when_rpc_fails(patch_supabase_client) -> None:
    patch_supabase_client.register_rpc("get_latest_state", RuntimeError("db down"))

    assert await agent_runner.is_food_already_picked_up("RIDER01") is False


CONFIG = {"configurable": {"thread_id": "ORDELO-dispatch-10"}}


async def test_run_rider_agent_w_custom_msg_builds_messages_updates_state_and_returns_ai_content(patched_runner) -> None:
    graph, _builder, threads = patched_runner

    result = await agent_runner.run_rider_agent_w_custom_msg(
        "RIDER01",
        human_msg="hello",
        ai_msg="previous",
        system_msg="system",
        state_update_dict={"dispatch_id": 10},
    )

    assert result == "AI response"
    assert graph.updates == [{"config": CONFIG, "values": {"dispatch_id": 10}, "as_node": "toolNode"}]
    assert [type(msg).__name__ for msg in graph.invocations[-1]["input"]["messages"]] == ["SystemMessage", "AIMessage", "HumanMessage"]
    ctx = graph.invocations[-1]["context"]
    assert ctx.thread_id == "ORDELO-dispatch-10" and ctx.recipient == "RIDER01" and ctx.dispatch_id == 10
    assert ctx.messenger.channel == "whatsapp"
    assert threads.touched == ["ORDELO-dispatch-10"]  # every run refreshes last_access_dtts


async def test_run_never_creates_a_thread(patched_runner) -> None:
    graph, _builder, threads = patched_runner
    threads.active = None

    assert await agent_runner.run_rider_agent_w_custom_msg("RIDER01", human_msg="late tap") is None
    assert graph.invocations == [] and threads.open_calls == []


async def test_run_by_dispatch_uses_that_thread_and_refuses_a_closed_one(patched_runner) -> None:
    graph, _builder, threads = patched_runner
    assert await agent_runner.run_rider_agent_w_custom_msg("RIDER01", system_msg="x", dispatch_id=10) == "AI response"
    assert graph.invocations[-1]["config"] == CONFIG

    threads.by_dispatch = RiderThread("ORDELO-dispatch-10", "RIDER01", is_active=False, dispatch_id=10)
    assert await agent_runner.run_rider_agent_w_custom_msg("RIDER01", system_msg="x", dispatch_id=10) is None
    assert len(graph.invocations) == 1


async def test_run_by_dispatch_falls_back_to_the_open_legacy_thread(patched_runner) -> None:
    graph, _builder, threads = patched_runner
    legacy = RiderThread("ORDELO-1234-uuid", "RIDER01")
    threads.by_dispatch, threads.active = None, legacy  # a thread opened before R2 has no dispatch row
    assert await agent_runner.resolve_rider_thread("RIDER01", dispatch_id=10) is legacy


async def test_telegram_thread_gets_a_telegram_messenger(patched_runner) -> None:
    from aiogram import Bot

    graph, _builder, threads = patched_runner
    bot = Bot(token="654321:TEST-rider", session=RecordingSession())  # offline
    tg_thread = RiderThread("ORDELO-dispatch-11", "RIDER01", dispatch_id=11, channel="telegram", tcid=555)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("config.rider_bot", bot)
        await agent_runner.run_rider_agent(tg_thread, human_msg="hi")
    ctx = graph.invocations[-1]["context"]
    assert ctx.messenger.channel == "telegram" and ctx.messenger.tcid == 555


async def test_clear_cues_do_not_create_threads(patched_runner) -> None:
    graph, _builder, threads = patched_runner
    await agent_runner.clear_pickup_alert_cue("RIDER01", dispatch_id=10)
    assert graph.updates[-1]["values"] == {"pickup_alert_offset": None, "pickup_alert_phase": None}
    assert graph.updates[-1]["config"] == CONFIG
    threads.by_dispatch, threads.active = None, None
    await agent_runner.clear_wa_location_request("RIDER01")
    assert len(graph.updates) == 1


async def test_init_ordelo_graph_updates_initial_state_and_invokes_graph(monkeypatch, patched_runner) -> None:
    graph, _builder, threads = patched_runner
    retry_delays = []

    async def _record_retry_delay(delay):
        retry_delays.append(delay)

    monkeypatch.setattr(agent_runner.asyncio, "sleep", _record_retry_delay)

    await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)

    assert threads.open_calls == [("RIDER01", 10)]
    update = graph.updates[-1]
    assert update["values"]["dispatch_id"] == 10
    assert update["values"]["order_number"] == "ELAS-ABCD-1"
    assert "start_live_tracking_url" not in update["values"]
    assert update["values"]["rider_name"] == "Bas"
    assert graph.invocations[-1]["config"] == CONFIG
    assert retry_delays == []


async def test_init_ordelo_graph_is_idempotent_when_the_hook_fires_again(patched_runner) -> None:
    graph, _builder, threads = patched_runner
    threads.open_results = ["existing"]
    await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)
    assert graph.updates == [] and graph.invocations == []


async def test_init_ordelo_graph_retries_only_thread_acquisition(monkeypatch, patched_runner) -> None:
    graph, _builder, threads = patched_runner
    retry_delays = []
    # First attempt: the connection drops (it may or may not have committed); second sees the thread as existing.
    threads.open_results = [OperationalError("SSL connection has been closed unexpectedly"), "existing"]

    async def _record_retry_delay(delay):
        retry_delays.append(delay)

    monkeypatch.setattr(agent_runner.asyncio, "sleep", _record_retry_delay)

    await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)

    assert len(threads.open_calls) == 2
    assert retry_delays == [agent_runner._THREAD_ACQUISITION_RETRY_DELAY_SECONDS]
    assert len(graph.updates) == 1  # 'existing' after a failed attempt still initialises once
    assert len(graph.invocations) == 1


async def test_init_ordelo_graph_propagates_second_thread_acquisition_failure(
    monkeypatch, patched_runner
) -> None:
    graph, _builder, threads = patched_runner
    threads.open_results = [OperationalError("SSL connection has been closed unexpectedly")] * 2

    async def _skip_retry_delay(delay):
        return None

    monkeypatch.setattr(agent_runner.asyncio, "sleep", _skip_retry_delay)

    with pytest.raises(OperationalError, match="SSL connection has been closed unexpectedly"):
        await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)

    assert len(threads.open_calls) == 2
    assert graph.updates == []
    assert graph.invocations == []


async def test_init_ordelo_graph_does_not_retry_non_operational_error(
    monkeypatch, patched_runner
) -> None:
    graph, _builder, threads = patched_runner
    threads.open_results = [RuntimeError("thread function failed")]

    with pytest.raises(RuntimeError, match="thread function failed"):
        await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)

    assert len(threads.open_calls) == 1
    assert graph.updates == []
    assert graph.invocations == []


async def test_debug_state_values_returns_shortened_state_values(monkeypatch, patched_runner) -> None:
    graph, _builder, threads = patched_runner
    monkeypatch.setattr(agent_runner, "get_state_values", lambda values: {"dispatch_id": values["dispatch_id"]})

    result = await agent_runner.debug_state_values(recipient="RIDER01")

    assert result == {"dispatch_id": 10}
    assert graph.last_state_config == CONFIG
    assert threads.touched == []  # debug reads never touch (or create) a thread


async def test_debug_thread_fetches_recipient_and_uses_thread_config(monkeypatch, patched_runner, patch_supabase_client) -> None:
    graph, _builder, _threads = patched_runner
    patch_supabase_client.register(
        table="thread",
        verb="select",
        response=FakeSupabaseResponse(data=[{"thread_id": "thread-9", "recipient": "RIDER09"}]),
    )
    monkeypatch.setattr(agent_runner, "get_state_values", lambda values: {"dispatch_id": values["dispatch_id"]})
    monkeypatch.setattr(agent_runner, "shorten_state_messages", lambda messages: ["short"])

    result = await agent_runner.debug_thread("thread-9")

    assert result == {"dispatch_id": 10, "messages": ["short"]}
    assert graph.last_state_config == {"configurable": {"thread_id": "thread-9", "recipient": "RIDER09"}}


async def test_debug_thread_raises_when_thread_missing(patched_runner, patch_supabase_client) -> None:
    patch_supabase_client.register(table="thread", verb="select", response=FakeSupabaseResponse(data=[]))

    with pytest.raises(ValueError, match="Thread not found"):
        await agent_runner.debug_thread("missing")


async def test_job_end_stale_conversations_uses_supplied_handler() -> None:
    class _Handler:
        def __init__(self):
            self.requested_minutes = None

        async def get_stale_active_threads(self, stale_minutes):
            self.requested_minutes = stale_minutes
            return [{"thread_id": "thread-1", "recipient": "RIDER01"}]

    handler = _Handler()

    await agent_runner.job_end_stale_conversations(thread_handler=handler, stale_minutes=15)

    assert handler.requested_minutes == 15
