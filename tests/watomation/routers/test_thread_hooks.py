"""Tests for thread webhook router helpers.

Thread hook tests cover system-message execution, debug
endpoint delegation, and state-by-thread graph inspection using patched graph and
Supabase fakes. Stale-thread selection and restaurant dispatch now live entirely
in the scheduled PostgreSQL function.

Key Functions:
  - test_run_system_message_uses_recipient_or_fetches_active_thread
  - test_run_system_message_raises_when_thread_missing
  - test_debug_endpoint_wrappers_delegate_to_agent_runner
  - test_debug_state_by_thread_path_builds_graph_config
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from watomation.routers import thread_hooks


async def test_run_system_message_uses_recipient_or_fetches_active_thread(
    monkeypatch, patch_supabase_client
) -> None:
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(thread_hooks, "run_rider_agent_w_custom_msg", _fake_run)
    request = thread_hooks.RunSystemMessageRequest(
        thread_id="thread-1",
        recipient="RIDER01",
        update_message="wake",
        state_update_dict={"x": 1},
    )

    result = await thread_hooks.run_system_message(request)
    assert result["recipient"] == "RIDER01"
    assert calls[-1] == {
        "recipient": "RIDER01",
        "system_msg": "wake",
        "state_update_dict": {"x": 1},
        "thread_id": "thread-1",  # R2: exactly the named thread, not "the rider's thread"
    }

    patch_supabase_client.register(
        table="thread",
        verb="select",
        response=FakeSupabaseResponse(
            data=[{"thread_id": "thread-2", "recipient": "RIDER02"}]
        ),
    )
    request = thread_hooks.RunSystemMessageRequest(
        thread_id="thread-2", update_message="wake"
    )
    result = await thread_hooks.run_system_message(request)
    assert result["recipient"] == "RIDER02"


async def test_run_system_message_404_when_the_named_thread_is_closed(monkeypatch) -> None:
    async def _closed(**kwargs):
        return None  # run_rider_agent_w_custom_msg never creates a thread; a closed one gives None

    monkeypatch.setattr(thread_hooks, "run_rider_agent_w_custom_msg", _closed)
    request = thread_hooks.RunSystemMessageRequest(thread_id="ORDELO-dispatch-9", recipient="RIDER01", update_message="wake")
    with pytest.raises(thread_hooks.HTTPException) as exc:
        await thread_hooks.run_system_message(request)
    assert exc.value.status_code == 404


async def test_run_system_message_raises_when_thread_missing(
    patch_supabase_client,
) -> None:
    patch_supabase_client.register(
        table="thread", verb="select", response=FakeSupabaseResponse(data=[])
    )

    with pytest.raises(HTTPException) as missing:
        await thread_hooks.run_system_message(
            thread_hooks.RunSystemMessageRequest(
                thread_id="missing", update_message="wake"
            )
        )
    assert missing.value.status_code == 404


async def test_debug_endpoint_wrappers_delegate_to_agent_runner(monkeypatch) -> None:
    async def _values(recipient):
        return {"recipient": recipient, "values": True}

    async def _state(recipient):
        return {"recipient": recipient, "state": True}

    async def _thread(thread_id):
        return {"thread_id": thread_id}

    monkeypatch.setattr(thread_hooks, "debug_state_values", _values)
    monkeypatch.setattr(thread_hooks, "debug_state", _state)
    monkeypatch.setattr(thread_hooks, "debug_thread", _thread)

    assert await thread_hooks.debug_state_values_path("RIDER01") == {
        "recipient": "RIDER01",
        "values": True,
    }
    assert await thread_hooks.debug_state_path("RIDER01") == {
        "recipient": "RIDER01",
        "state": True,
    }
    assert await thread_hooks.debug_admin_state_path("ADMIN01") == {
        "recipient": "ADMIN01",
        "state": True,
    }
    assert await thread_hooks.debug_thread_path("thread-1") == {"thread_id": "thread-1"}


async def test_debug_state_by_thread_path_builds_graph_config(
    monkeypatch, patch_supabase_client, patch_pg_pool
) -> None:
    patch_supabase_client.register(
        table="thread",
        verb="select",
        response=FakeSupabaseResponse(
            data=[{"thread_id": "thread-1", "recipient": "RIDER01"}]
        ),
    )
    seen = {}

    class _Graph:
        async def aget_state(self, config):
            seen["config"] = config
            return SimpleNamespace(values={"messages": ["hello"], "dispatch_id": 10})

    class _Builder:
        def compile(self, checkpointer=None):
            seen["checkpointer"] = checkpointer
            return _Graph()

    monkeypatch.setattr(thread_hooks, "builder", _Builder())
    monkeypatch.setattr(
        thread_hooks, "AsyncPostgresSaver", lambda pool: SimpleNamespace(pool=pool)
    )
    monkeypatch.setattr(
        thread_hooks,
        "get_state_values",
        lambda values: {"dispatch_id": values["dispatch_id"]},
    )
    monkeypatch.setattr(
        thread_hooks, "shorten_state_messages", lambda messages: ["short"]
    )

    result = await thread_hooks.debug_state_by_thread_path("thread-1")

    assert seen["config"] == {
        "configurable": {"thread_id": "thread-1", "recipient": "RIDER01"}
    }
    assert result == {"dispatch_id": 10, "messages": ["short"]}
