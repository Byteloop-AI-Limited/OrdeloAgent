"""Focused contract tests for WaLocation's safety-critical primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from config.pg_setting import PgSetting
from ordelo.wa_location import WaLocation, WaLocationConflict, WaLocationForbidden, _DeliveryContext
from ordelo_datamodels.wa_location_pymodels import WaLocationDemand


def _context(*, status: str = "pickedup") -> _DeliveryContext:
    return _DeliveryContext(
        order_number="SFCS-123",
        customer_id="447700900000",
        dispatch_id=17,
        rider_id="447700900111",
        dispatch_status=status,
        admins=["447700900222"],
    )


def test_demand_requires_credential_free_https_callback() -> None:
    demand = WaLocationDemand(
        rest_ref="SFCS",
        order_number="SFCS-123",
        location_requested_by="customer",
        requester_id="447700900000",
        callback_url="https://service.example.com/wa-location",
    )

    assert demand.callback_url == "https://service.example.com/wa-location"
    with pytest.raises(ValueError, match="callback_url_must_be_public_https"):
        WaLocationDemand(
            rest_ref="SFCS",
            order_number="SFCS-123",
            location_requested_by="customer",
            requester_id="447700900000",
            callback_url="http://service.example.com/wa-location",
        )
    with pytest.raises(ValueError, match="callback_url_must_be_public_https"):
        WaLocationDemand(
            rest_ref="SFCS",
            order_number="SFCS-123",
            location_requested_by="customer",
            requester_id="447700900000",
            callback_url="https://user:pass@service.example.com/wa-location",
        )


async def test_private_callback_destination_is_rejected(monkeypatch) -> None:
    class _Loop:
        async def getaddrinfo(self, *_args, **_kwargs):
            return [(None, None, None, None, ("127.0.0.1", 443))]

    monkeypatch.setattr("ordelo.wa_location.asyncio.get_running_loop", lambda: _Loop())
    service = WaLocation(wa_client=SimpleNamespace())

    with pytest.raises(WaLocationForbidden, match="callback_url_not_public"):
        await service._validate_public_callback_url("https://service.example.com/wa-location")


async def test_customer_requires_exact_inflight_before_pickedup_check(monkeypatch) -> None:
    service = WaLocation(wa_client=SimpleNamespace())

    async def _not_inflight(*_args, **_kwargs):
        return False

    monkeypatch.setattr(service, "_exact_inflight_assignment_exists_in_cursor", _not_inflight)
    demand = WaLocationDemand(
        rest_ref="SFCS",
        order_number="SFCS-123",
        location_requested_by="customer",
        requester_id="447700900000",
        callback_url="https://service.example.com/wa-location",
    )

    with pytest.raises(WaLocationConflict, match="delivery_not_inflight"):
        await service._validate_demand(SimpleNamespace(), demand, _context())


async def test_customer_identity_is_checked_before_inflight_state(monkeypatch) -> None:
    service = WaLocation(wa_client=SimpleNamespace())

    async def _unexpected_inflight(*_args, **_kwargs):
        raise AssertionError("inflight state must not be revealed to another customer")

    monkeypatch.setattr(service, "_exact_inflight_assignment_exists_in_cursor", _unexpected_inflight)
    demand = WaLocationDemand(
        rest_ref="SFCS",
        order_number="SFCS-123",
        location_requested_by="customer",
        requester_id="447700999999",
        callback_url="https://service.example.com/wa-location",
    )

    with pytest.raises(WaLocationForbidden, match="customer_order_mismatch"):
        await service._validate_demand(SimpleNamespace(), demand, _context())


async def test_customer_before_pickup_is_not_eligible_even_when_inflight(monkeypatch) -> None:
    service = WaLocation(wa_client=SimpleNamespace())

    async def _inflight(*_args, **_kwargs):
        return True

    monkeypatch.setattr(service, "_exact_inflight_assignment_exists_in_cursor", _inflight)
    demand = WaLocationDemand(
        rest_ref="SFCS",
        order_number="SFCS-123",
        location_requested_by="customer",
        requester_id="447700900000",
        callback_url="https://service.example.com/wa-location",
    )

    with pytest.raises(WaLocationConflict, match="food_not_picked_up"):
        await service._validate_demand(SimpleNamespace(), demand, _context(status="assigned"))


async def test_exact_inflight_query_never_uses_rider_id_alone() -> None:
    executed: list[tuple[str, tuple]] = []

    class _Cursor:
        async def execute(self, sql, params):
            executed.append((sql, params))

        async def fetchone(self):
            return {"?column?": 1}

    service = WaLocation(wa_client=SimpleNamespace())
    assert await service._exact_inflight_assignment_exists_in_cursor(_Cursor(), _context())
    assert "order_number = %s AND dispatch_id = %s AND rider_id = %s" in executed[0][0]
    assert executed[0][1] == ("SFCS-123", 17, "447700900111")


async def test_fulfilled_request_posts_open_callback_before_marking_delivered(
    monkeypatch,
) -> None:
    request_id = uuid4()
    row = {
        "request_id": request_id,
        "order_number": "SFCS-123",
        "dispatch_id": 17,
        "rider_id": "447700900111",
        "requester_id": "447700900000",
        "location_requested_by": "customer",
        "callback_url": "https://service.example.com/wa-location",
        "customer_id": "447700900000",
        "latitude": 51.5,
        "longitude": -0.12,
        "source": "whatsapp_current",
        "observed_at": datetime.now(timezone.utc),
    }

    class _Cursor:
        async def execute(self, *_args, **_kwargs):
            return None

        async def fetchone(self):
            return row

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Connection:
        def cursor(self, *_args, **_kwargs):
            return _Cursor()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Pool:
        def connection(self):
            return _Connection()

    callback = {}

    class _Response:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, **kwargs):
            callback["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json):
            callback["url"] = url
            callback["payload"] = json
            return _Response()

    service = WaLocation(wa_client=SimpleNamespace())

    async def _pool(_self):
        return _Pool()

    async def _public_url(_url):
        return None

    async def _inflight(_context):
        return True

    delivered = []

    async def _mark_delivered(value):
        delivered.append(value)

    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr(service, "_validate_public_callback_url", _public_url)
    monkeypatch.setattr(service, "_exact_inflight_assignment_exists", _inflight)
    monkeypatch.setattr(service, "_mark_delivered", _mark_delivered)
    monkeypatch.setattr("ordelo.wa_location.httpx.AsyncClient", _Client)

    assert await service.route_fulfilled_request(request_id) == "delivered"

    assert callback["url"] == "https://service.example.com/wa-location"
    assert callback["payload"]["requester_id"] == "447700900000"
    assert callback["payload"]["location"]["latitude"] == 51.5
    assert callback["client_kwargs"]["follow_redirects"] is False
    assert delivered == [request_id]


def test_migration_expires_matching_requests_when_inflight_ends() -> None:
    migration = Path("ordelo_datamodels/migrations/create_wa_location_tables.sql").read_text()

    assert "AFTER DELETE ON public.delivery_inflight" in migration
    assert "order_number = OLD.order_number" in migration
    assert "dispatch_id = OLD.dispatch_id" in migration
    assert "rider_id = OLD.rider_id" in migration


def test_migrations_store_callback_url_for_new_and_existing_installations() -> None:
    initial = Path("ordelo_datamodels/migrations/create_wa_location_tables.sql").read_text()
    forward = Path("ordelo_datamodels/migrations/add_wa_location_request_callback_url.sql").read_text()

    assert "callback_url TEXT NOT NULL" in initial
    assert "ADD COLUMN IF NOT EXISTS callback_url TEXT" in forward


async def test_record_prompt_sent_and_mark_prompt_failed_coerce_string_request_id(
    monkeypatch,
) -> None:
    """wa_location_request_id round-trips through LangGraph state as a str;
    the DB helpers must not pass that straight through as the request_id
    parameter without coercing it back to a UUID."""
    request_id = uuid4()
    saved = []
    failed = []

    async def _save(_self, req_id, message_id):
        saved.append((req_id, message_id))

    async def _fail(_self, req_id, reason):
        failed.append((req_id, reason))

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(WaLocation, "_save_prompt_message_id", _save)
    monkeypatch.setattr(WaLocation, "_mark_prompt_failed", _fail)

    await service.record_prompt_sent(str(request_id), "wamid.1")
    await service.mark_prompt_failed(str(request_id), "boom")

    assert saved == [(request_id, "wamid.1")]
    assert isinstance(saved[0][0], type(request_id))
    assert failed == [(request_id, "boom")]


def _demand(**overrides) -> WaLocationDemand:
    payload = dict(
        rest_ref="SFCS",
        order_number="SFCS-123",
        location_requested_by="customer",
        requester_id="447700900000",
        callback_url="https://service.example.com/wa-location",
    )
    payload.update(overrides)
    return WaLocationDemand(**payload)


async def test_request_schedules_prompt_via_background_task_and_returns_waiting(
    monkeypatch,
) -> None:
    request_id = uuid4()
    fetchone_results = [
        {  # _load_delivery_context
            "order_number": "SFCS-123",
            "customer_id": "447700900000",
            "dispatch_id": 17,
            "rider_id": "447700900111",
            "dispatch_status": "assigned",
            "admins": ["447700900222"],
        },
        {"exists": 1},  # _exact_inflight_assignment_exists_in_cursor (in _validate_demand)
        {"request_id": request_id},  # INSERT ... RETURNING request_id
        None,  # fresh-observation lookup
        None,  # recent-prompt cooldown lookup
        {"exists": 1},  # post-txn _exact_inflight_assignment_exists
    ]

    class _Cursor:
        async def execute(self, *_args, **_kwargs):
            return None

        async def fetchone(self):
            return fetchone_results.pop(0)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Txn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Connection:
        def cursor(self, *_args, **_kwargs):
            return _Cursor()

        def transaction(self):
            return _Txn()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Pool:
        def connection(self):
            return _Connection()

    async def _pool(_self):
        return _Pool()

    async def _no_dns_check(_url):
        return None

    scheduled = []

    def _schedule(func, *args):
        scheduled.append((func, args))

    called_with = []

    async def _fake_prompt(_self, req_id, context, demand):
        called_with.append((req_id, context, demand))

    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr(WaLocation, "_prompt_rider_via_agent", _fake_prompt)

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(service, "_validate_public_callback_url", _no_dns_check)

    demand = _demand(location_requested_by="restaurant_admin", requester_id="447700900222")

    outcome = await service.request(demand, schedule=_schedule)

    assert outcome.status == "waiting_for_rider"
    assert outcome.request_id == request_id
    assert scheduled[0][0] == service._prompt_rider_via_agent

    # Invoking exactly as BackgroundTasks.add_task would must run the prompt.
    func, args = scheduled[0]
    await func(*args)
    assert called_with == [(request_id, args[1], demand)]


async def test_prompt_rider_via_agent_falls_back_to_direct_send_when_thread_inactive(
    monkeypatch,
) -> None:
    request_id = uuid4()
    context = _context()
    demand = _demand()

    sent_calls = []

    class _FakeWa:
        async def request_location(self, **kwargs):
            sent_calls.append(kwargs)
            return SimpleNamespace(id="wamid.fallback.1")

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return None

    async def _pool(_self):
        return object()

    recorded = []

    async def _record(_self, req_id, message_id):
        recorded.append((req_id, message_id))

    service = WaLocation(wa_client=_FakeWa())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(WaLocation, "record_prompt_sent", _record)

    await service._prompt_rider_via_agent(request_id, context, demand)

    assert sent_calls[0]["to"] == context.rider_id
    assert recorded == [(request_id, "wamid.fallback.1")]


async def test_direct_send_failure_does_not_create_a_thread_to_clear_state(
    monkeypatch,
) -> None:
    """When the rider has no active thread and the direct-send fallback itself
    raises, the failure handler must not call clear_wa_location_request --
    that runs get_or_create_thread() and would spawn a thread purely to clear
    state nothing ever wrote to, undoing the reason the fallback exists."""
    request_id = uuid4()
    context = _context()
    demand = _demand()

    class _FakeWa:
        async def request_location(self, **_kwargs):
            raise RuntimeError("wa down")

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return None

    async def _pool(_self):
        return object()

    failed = []

    async def _mark_failed(_self, req_id, reason):
        failed.append((req_id, reason))

    async def _clear(recipient):
        raise AssertionError("clear_wa_location_request must not run a thread was never used")

    service = WaLocation(wa_client=_FakeWa())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(WaLocation, "mark_prompt_failed", _mark_failed)
    monkeypatch.setattr("ordelo.agents.agent_runner.clear_wa_location_request", _clear)

    await service._prompt_rider_via_agent(request_id, context, demand)

    assert failed == [(request_id, "RuntimeError")]


async def test_prompt_rider_via_agent_runs_graph_and_names_requester(monkeypatch) -> None:
    request_id = uuid4()
    context = _context()
    demand = _demand(location_requested_by="restaurant_admin", requester_id="447700900222")

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return {"thread_id": "t1"}

    async def _pool(_self):
        return object()

    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    async def _prompt_message_id(_self, _request_id):
        return "wamid.agent.1"

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )
    monkeypatch.setattr(WaLocation, "_prompt_message_id", _prompt_message_id)

    await service._prompt_rider_via_agent(request_id, context, demand)

    assert len(calls) == 1
    assert calls[0]["recipient"] == context.rider_id
    assert "restaurant" in calls[0]["system_msg"]
    assert calls[0]["state_update_dict"] == {"wa_location_request_id": str(request_id)}


async def test_prompt_rider_via_agent_retries_deterministically_then_marks_failed(
    monkeypatch,
) -> None:
    request_id = uuid4()
    context = _context()
    demand = _demand()

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return {"thread_id": "t1"}

    async def _pool(_self):
        return object()

    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    async def _always_none(_self, _request_id):
        return None

    async def _still_pending(_self, _request_id):
        return "pending"

    failed = []

    async def _mark_failed(_self, req_id, reason):
        failed.append((req_id, reason))

    cleared = []

    async def _clear(recipient):
        cleared.append(recipient)

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )
    monkeypatch.setattr("ordelo.agents.agent_runner.clear_wa_location_request", _clear)
    monkeypatch.setattr(WaLocation, "_prompt_message_id", _always_none)
    monkeypatch.setattr(WaLocation, "_request_status", _still_pending)
    monkeypatch.setattr(WaLocation, "mark_prompt_failed", _mark_failed)

    await service._prompt_rider_via_agent(request_id, context, demand)

    # First call is the LLM cue, second is the forced deterministic retry.
    assert len(calls) == 2
    assert calls[1]["state_update_dict"] == {"force_wa_location_prompt": True}
    assert failed == [(request_id, "prompt_not_sent")]
    assert cleared == [context.rider_id]


async def test_prompt_rider_via_agent_skips_retry_when_tool_already_marked_failed(
    monkeypatch,
) -> None:
    """The request_rider_current_location tool marks a send failure itself and
    clears wa_location_request_id. The retry can't fire in that state (its
    forced tool call needs wa_location_request_id set), so it must be skipped
    rather than overwrite the tool's real failure reason with 'prompt_not_sent'."""
    request_id = uuid4()
    context = _context()
    demand = _demand()

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return {"thread_id": "t1"}

    async def _pool(_self):
        return object()

    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    async def _always_none(_self, _request_id):
        return None

    async def _already_failed(_self, _request_id):
        return "failed"

    async def _mark_failed(_self, req_id, reason):
        raise AssertionError("mark_prompt_failed must not run again")

    cleared = []

    async def _clear(recipient):
        cleared.append(recipient)

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _fake_run
    )
    monkeypatch.setattr("ordelo.agents.agent_runner.clear_wa_location_request", _clear)
    monkeypatch.setattr(WaLocation, "_prompt_message_id", _always_none)
    monkeypatch.setattr(WaLocation, "_request_status", _already_failed)
    monkeypatch.setattr(WaLocation, "mark_prompt_failed", _mark_failed)

    await service._prompt_rider_via_agent(request_id, context, demand)

    # Only the initial LLM-cue call runs; no forced retry, no re-marking.
    assert len(calls) == 1
    assert cleared == []


async def test_prompt_rider_via_agent_contains_graph_failures(monkeypatch) -> None:
    request_id = uuid4()
    context = _context()
    demand = _demand()

    class _FakeThreadHandler:
        def __init__(self, _pool):
            pass

        async def get_active_thread(self, _recipient):
            return {"thread_id": "t1"}

    async def _pool(_self):
        return object()

    async def _boom(**_kwargs):
        raise RuntimeError("llm timeout")

    failed = []

    async def _mark_failed(_self, req_id, reason):
        failed.append((req_id, reason))

    cleared = []

    async def _clear(recipient):
        cleared.append(recipient)

    service = WaLocation(wa_client=SimpleNamespace())
    monkeypatch.setattr(PgSetting, "get_pool", _pool)
    monkeypatch.setattr("ordelo.wa_location.ThreadHandler", _FakeThreadHandler)
    monkeypatch.setattr(
        "ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", _boom
    )
    monkeypatch.setattr("ordelo.agents.agent_runner.clear_wa_location_request", _clear)
    monkeypatch.setattr(WaLocation, "mark_prompt_failed", _mark_failed)

    await service._prompt_rider_via_agent(request_id, context, demand)

    assert failed == [(request_id, "RuntimeError")]
    assert cleared == [context.rider_id]
