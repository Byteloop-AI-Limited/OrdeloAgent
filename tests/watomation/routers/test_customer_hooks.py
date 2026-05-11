"""Tests for customer webhook router helpers.

Customer hooks are tested with fake model upserts, fake Supabase update
responses, and respx restaurant webhook mocks to verify customer creation,
address update, notification failure tolerance, and consent-map updates.

Key Functions:
  - test_create_or_update_customer_creates_new_customer_with_restaurant_city
  - test_create_or_update_customer_updates_existing_customer
  - test_update_address_updates_db_notifies_restaurant_and_handles_missing_customer
  - test_update_cust_rest_map_returns_model_dump
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi import HTTPException

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from watomation.routers import customer_hooks


async def test_create_or_update_customer_creates_new_customer_with_restaurant_city(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(customer_hooks.CustomerMaster, "from_cust_id", staticmethod(lambda cust_id: (_ for _ in ()).throw(ValueError("missing"))))
    monkeypatch.setattr(customer_hooks, "_resolve_rest_ref", lambda rest_ref: "ELAS")
    monkeypatch.setattr(customer_hooks.RestaurantMaster, "from_rest_ref", staticmethod(lambda rest_ref: SimpleNamespace(city="London")))
    monkeypatch.setattr(customer_hooks.CustomerMaster, "upsert", staticmethod(lambda **kwargs: calls.append(("customer", kwargs)) or SimpleNamespace(cust_id=kwargs["cust_id"])))
    monkeypatch.setattr(customer_hooks.CustRestMap, "upsert", staticmethod(lambda **kwargs: calls.append(("map", kwargs))))

    request = customer_hooks.CreateOrUpdateCustomerRequest(cust_id="447400000000", rest_ref="ELAS", cust_name="Bas")
    result = await customer_hooks.create_or_update_customer(request)

    assert result.cust_id == "447400000000"
    assert calls == [
        ("customer", {"cust_id": "447400000000", "rest_ref": "ELAS", "cust_name": "Bas"}),
        ("map", {"cust_id": "447400000000", "rest_ref": "ELAS", "has_consent": False}),
    ]


async def test_create_or_update_customer_updates_existing_customer(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(customer_hooks.CustomerMaster, "from_cust_id", staticmethod(lambda cust_id: SimpleNamespace(cust_id=cust_id)))
    monkeypatch.setattr(customer_hooks.CustomerMaster, "upsert", staticmethod(lambda **kwargs: calls.append(kwargs) or SimpleNamespace(cust_id=kwargs["cust_id"])))

    result = await customer_hooks.create_or_update_customer(
        customer_hooks.CreateOrUpdateCustomerRequest(cust_id="447400000000", rest_ref="ELAS", cust_name="Bas")
    )

    assert result.cust_id == "447400000000"
    assert calls == [{"cust_id": "447400000000", "rest_ref": "ELAS", "cust_name": "Bas"}]


@respx.mock
async def test_update_address_updates_db_notifies_restaurant_and_handles_missing_customer(monkeypatch, patch_supabase_client) -> None:
    async def _webhook(rest_ref, webhook_type):
        return "https://rest.example.com/address-update"

    monkeypatch.setattr(customer_hooks, "get_restaurant_webhook_url_async", _webhook)
    patch_supabase_client.register(table="customer_master", verb="update", response=FakeSupabaseResponse(data=[{"cust_id": "447400000000"}]))
    route = respx.post("https://rest.example.com/address-update/447400000000").mock(return_value=httpx.Response(200, json={"ok": True}))
    request = customer_hooks.UpdateAddressRequest(
        cust_id="447400000000",
        rest_ref="ELAS",
        house_number="1",
        street_name="High Street",
        city="London",
        postcode="BR6 6DN",
        lat=51.5,
        lon=-0.1,
    )

    assert await customer_hooks.update_address(request) == {"success": True, "cust_id": "447400000000"}
    assert patch_supabase_client.calls[-1].payload["postcode"] == "BR6 6DN"
    assert route.called

    patch_supabase_client.register(table="customer_master", verb="update", response=FakeSupabaseResponse(data=[]))
    with pytest.raises(HTTPException) as missing:
        await customer_hooks.update_address(request)
    assert missing.value.status_code == 404


async def test_update_cust_rest_map_returns_model_dump(monkeypatch) -> None:
    consent_dtts = datetime(2026, 5, 10, tzinfo=timezone.utc)
    record = SimpleNamespace(model_dump=lambda: {"cust_id": "4474", "rest_ref": "ELAS", "has_consent": True})
    calls = []
    monkeypatch.setattr(customer_hooks.CustRestMap, "upsert", staticmethod(lambda **kwargs: calls.append(kwargs) or record))

    result = await customer_hooks.update_cust_rest_map(
        customer_hooks.UpdateCustRestMapRequest(cust_id="4474", rest_ref="ELAS", has_consent=True, consent_dtts=consent_dtts)
    )

    assert result == {"success": True, "record": {"cust_id": "4474", "rest_ref": "ELAS", "has_consent": True}}
    assert calls == [{"cust_id": "4474", "rest_ref": "ELAS", "has_consent": True, "consent_dtts": consent_dtts}]
