"""Tests for rider agent runner orchestration helpers.

The graph builder, checkpointer, context schema, and thread config helper are
patched with lightweight fakes so no Postgres checkpointer or LangGraph runtime
is required.

Key Functions:
  - test_run_rider_agent_w_custom_msg_builds_messages_updates_state_and_returns_ai_content
  - test_init_ordelo_graph_updates_initial_state_and_invokes_graph
  - test_debug_state_values_returns_shortened_state_values
  - test_debug_thread_fetches_recipient_and_uses_thread_config
  - test_job_end_stale_conversations_uses_supplied_handler
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ordelo.agents import agent_runner
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


@pytest.fixture
def patched_runner(monkeypatch, patch_pg_pool):
    graph = _FakeGraph()
    builder = _FakeBuilder(graph)
    monkeypatch.setattr(agent_runner, "builder", builder)
    monkeypatch.setattr(agent_runner, "AsyncPostgresSaver", lambda pool: SimpleNamespace(pool=pool))
    monkeypatch.setattr(agent_runner, "ContextSchema", lambda **kwargs: SimpleNamespace(**kwargs))

    async def _fake_config(recipient, pool):
        return {"configurable": {"thread_id": "thread-1", "recipient": recipient}}, False

    monkeypatch.setattr(agent_runner, "get_config_for_recipient", _fake_config)
    return graph, builder


async def test_run_rider_agent_w_custom_msg_builds_messages_updates_state_and_returns_ai_content(patched_runner) -> None:
    graph, _builder = patched_runner

    result = await agent_runner.run_rider_agent_w_custom_msg(
        "RIDER01",
        human_msg="hello",
        ai_msg="previous",
        system_msg="system",
        state_update_dict={"dispatch_id": 10},
    )

    assert result == "AI response"
    assert graph.updates == [
        {
            "config": {"configurable": {"thread_id": "thread-1", "recipient": "RIDER01"}},
            "values": {"dispatch_id": 10},
            "as_node": "toolNode",
        }
    ]
    assert [type(msg).__name__ for msg in graph.invocations[-1]["input"]["messages"]] == ["SystemMessage", "AIMessage", "HumanMessage"]


async def test_init_ordelo_graph_updates_initial_state_and_invokes_graph(monkeypatch, patched_runner) -> None:
    graph, _builder = patched_runner

    async def _fake_start_config(summary, rider_id):
        return "https://track.example.com/start"

    monkeypatch.setattr(agent_runner, "create_start_job_config", _fake_start_config)

    await agent_runner.init_ordelo_graph(_summary(), "RIDER01", "Bas", 10)

    update = graph.updates[-1]
    assert update["values"]["dispatch_id"] == 10
    assert update["values"]["order_number"] == "ELAS-ABCD-1"
    assert update["values"]["start_live_tracking_url"] == "https://track.example.com/start"
    assert update["values"]["rider_name"] == "Bas"
    assert graph.invocations[-1]["config"] == {"configurable": {"thread_id": "thread-1", "recipient": "RIDER01"}}


async def test_debug_state_values_returns_shortened_state_values(monkeypatch, patched_runner) -> None:
    graph, _builder = patched_runner
    monkeypatch.setattr(agent_runner, "get_state_values", lambda values: {"dispatch_id": values["dispatch_id"]})

    result = await agent_runner.debug_state_values(recipient="RIDER01")

    assert result == {"dispatch_id": 10}
    assert graph.last_state_config == {"configurable": {"thread_id": "thread-1", "recipient": "RIDER01"}}


async def test_debug_thread_fetches_recipient_and_uses_thread_config(monkeypatch, patched_runner, patch_supabase_client) -> None:
    graph, _builder = patched_runner
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
