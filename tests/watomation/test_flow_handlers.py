"""Tests for WhatsApp flow request handlers.

Flow handlers are invoked with lightweight request/completion fakes to verify
initialization, error acknowledgements, data exchange responses, postcode lookup
success/failure, and completion logging paths without pywa network access.

Key Functions:
  - test_customer_address_flow_init_and_error_ack
  - test_customer_address_flow_data_exchange_returns_error_message
  - test_customer_address_flow_completion_returns_none
  - test_postcode_search_init_and_error_ack
  - test_postcode_search_data_exchange_returns_address_or_error
"""

from __future__ import annotations

from types import SimpleNamespace

from watomation import on_flow_request_postcode_search as postcode_flow
from watomation import on_flow_request_wa_handler as address_flow


class _FlowRequest:
    def __init__(self, *, data=None, has_error=False, version="3.0") -> None:
        self.data = data or {}
        self.has_error = has_error
        self.version = version


async def test_customer_address_flow_init_and_error_ack() -> None:
    response = await address_flow.on_customer_address_flow(None, _FlowRequest(data={"hello": "world"}))
    assert response.screen == "START"
    assert response.data["flow_name"] == "CustomerAddressCapture"

    error = await address_flow.on_customer_address_flow(None, _FlowRequest(data={"error": True}, has_error=True))
    assert error.data == {"acknowledged": True}


async def test_customer_address_flow_data_exchange_returns_error_message() -> None:
    response = await address_flow.on_customer_address_flow_data_exchange(None, _FlowRequest(data={"x": 1}))

    assert response.screen == "START"
    assert response.error_message == "You are already registered. Please login"
    assert response.data["customer_name"].startswith("I will give")


async def test_customer_address_flow_completion_returns_none() -> None:
    result = await address_flow.on_customer_address_flow_completion(
        None,
        SimpleNamespace(token="flow-token", response={"ok": True}),
    )

    assert result is None


async def test_postcode_search_init_and_error_ack() -> None:
    response = await postcode_flow.on_pc_search_init(None, _FlowRequest())
    assert response.screen == "START"
    assert response.data["flow_name"] == "PostcodeSearch"

    error = await postcode_flow.on_pc_search_init(None, _FlowRequest(has_error=True))
    assert error.data == {"acknowledged": True}


async def test_postcode_search_data_exchange_returns_address_or_error(monkeypatch) -> None:
    address = SimpleNamespace(
        house_number=None,
        building_name=None,
        street_name=None,
        city="London",
        postcode="BR6 6DN",
    )
    monkeypatch.setattr(postcode_flow.address_resolver, "get_address_from_postcode", lambda postcode: address)

    response = await postcode_flow.on_ip_pc(None, _FlowRequest(data={"ip_postcode": "BR6 6DN"}))

    assert response.screen == "ADDRESS"
    assert response.data["house_number"] == ""
    assert response.data["building"] == ""
    assert response.data["street"] == ""
    assert response.data["city"] == "London"

    monkeypatch.setattr(postcode_flow.address_resolver, "get_address_from_postcode", lambda postcode: SimpleNamespace(house_number=None, building_name=None, street_name=None, city=None))
    error = await postcode_flow.on_ip_pc(None, _FlowRequest(data={"ip_postcode": "BAD"}))
    assert error.error_message == "postcode not found"
