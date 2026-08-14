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
