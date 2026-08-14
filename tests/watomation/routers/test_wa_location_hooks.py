"""Tests for the open WaLocation endpoint boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ordelo.wa_location import WaLocationCallbackDeliveryFailed, WaLocationConflict
from watomation.routers import wa_location_hooks


class _Request:
    def __init__(self, payload: dict) -> None:
        self._raw_body = json.dumps(payload).encode()

    async def body(self) -> bytes:
        return self._raw_body


async def test_open_endpoint_accepts_unsigned_valid_demand(monkeypatch) -> None:
    captured = []

    class _WaLocation:
        def __init__(self, **_kwargs) -> None:
            pass

        async def request(self, demand):
            captured.append(demand)
            return SimpleNamespace(
                status="rider_prompted",
                model_dump=lambda **_kwargs: {
                    "request_id": str(uuid4()),
                    "status": "rider_prompted",
                    "source": None,
                },
            )

    monkeypatch.setattr(wa_location_hooks, "WaLocation", _WaLocation)
    response = await wa_location_hooks.request_location(
        _Request(
            {
                "rest_ref": "SFCS",
                "order_number": "SFCS-123",
                "location_requested_by": "customer",
                "requester_id": "447700900000",
                "callback_url": "https://service.example.com/wa-location",
            }
        )
    )

    assert response.status_code == 202
    assert captured[0].callback_url == "https://service.example.com/wa-location"


def test_callback_delivery_failure_maps_to_gateway_error() -> None:
    assert (
        wa_location_hooks._http_error_for(WaLocationCallbackDeliveryFailed()).status_code
        == 502
    )


class _FakeLogger:
    def __init__(self) -> None:
        self.exception_calls: list[tuple] = []

    def exception(self, *args, **kwargs) -> None:
        self.exception_calls.append((args, kwargs))


_DEMAND_PAYLOAD = {
    "rest_ref": "BNAT",
    "order_number": "BNAT-EGCS-27",
    "location_requested_by": "customer",
    "requester_id": "447700900000",
    "callback_url": "https://service.example.com/wa-location",
}


async def test_unhandled_exception_is_logged_with_order_context(monkeypatch) -> None:
    """A genuinely unexpected failure must not disappear silently as a bare 500.

    Before this, WaLocation.request's own except block only recorded the
    exception's class name in wa_location_request.route_error -- nothing
    ever logged a traceback, so a real 500 like BNAT-EGCS-27 was
    undiagnosable from the application logs.
    """

    class _WaLocation:
        def __init__(self, **_kwargs) -> None:
            pass

        async def request(self, demand):
            raise RuntimeError("boom")

    fake_logger = _FakeLogger()
    monkeypatch.setattr(wa_location_hooks, "WaLocation", _WaLocation)
    monkeypatch.setattr(wa_location_hooks, "logger", fake_logger)

    with pytest.raises(HTTPException) as exc_info:
        await wa_location_hooks.request_location(_Request(_DEMAND_PAYLOAD))

    assert exc_info.value.status_code == 500
    assert len(fake_logger.exception_calls) == 1
    args, _kwargs = fake_logger.exception_calls[0]
    assert "BNAT-EGCS-27" in args
    assert "BNAT" in args
    assert "447700900000" in args


async def test_typed_conflict_does_not_trigger_unexpected_error_logging(
    monkeypatch,
) -> None:
    """Expected, typed outcomes (404/403/409/502) are not unexpected failures."""

    class _WaLocation:
        def __init__(self, **_kwargs) -> None:
            pass

        async def request(self, demand):
            raise WaLocationConflict("food_not_picked_up")

    fake_logger = _FakeLogger()
    monkeypatch.setattr(wa_location_hooks, "WaLocation", _WaLocation)
    monkeypatch.setattr(wa_location_hooks, "logger", fake_logger)

    with pytest.raises(HTTPException) as exc_info:
        await wa_location_hooks.request_location(_Request(_DEMAND_PAYLOAD))

    assert exc_info.value.status_code == 409
    assert fake_logger.exception_calls == []
