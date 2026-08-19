"""Tests for restaurant, customer, and customer-restaurant map models.

The DB-facing classmethods are exercised through the shared fake Supabase
client so tests assert both model validation and query intent.

Key Functions:
  - test_restaurant_master_from_rest_ref_uppercases_lookup
  - test_restaurant_master_get_admins_fetches_live_column
  - test_restaurant_master_auto_accept_defaults_false_and_accepts_true
  - test_customer_master_defaults_missing_address_bits
  - test_customer_master_from_customer_id_alias
  - test_customer_master_upsert_filters_unknown_fields
  - test_cust_rest_map_fetches_uppercase_rest_ref
  - test_cust_rest_map_upsert_serializes_consent_timestamp
  - test_cust_rest_map_ask_for_marketing_consent_branches
  - test_request_models_validate_required_fields
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ordelo_datamodels.cust_rest_map_pymodel import CustRestMap
from ordelo_datamodels.customer_master_pymodel import (
    CreateOrUpdateCustomerRequest,
    CustomerMaster,
    UpdateAddressRequest,
    UpdateCustRestMapRequest,
)
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from tests.fixtures.fake_supabase import FakeSupabaseResponse


def _restaurant_row(**overrides):
    row = {
        "rest_ref": "ELAS",
        "rest_id": "REST001",
        "rest_name": "Elai",
        "rest_email": "ops@example.com",
        "admins": ["447400000001", "447400000002"],
        "house_number": "1",
        "building_name": None,
        "street_name": "Test Street",
        "city": "London",
        "postcode": "SW1A 1AA",
        "lat": 51.5074,
        "lon": -0.1278,
        "dt": date(2026, 5, 9),
        "dtts": datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _customer_row(**overrides):
    row = {
        "cust_id": "447400000000",
        "cust_name": "Test Customer",
        "cust_email": "customer@example.com",
        "house_number": "2",
        "building_name": None,
        "street_name": "Customer Road",
        "city": "London",
        "postcode": "SW1A 2AA",
        "lat": 51.5,
        "lon": -0.12,
    }
    row.update(overrides)
    return row


def test_restaurant_master_from_rest_ref_uppercases_lookup(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="restaurant_master",
        verb="select",
        response=FakeSupabaseResponse(data=[_restaurant_row()]),
    )

    rest = RestaurantMaster.from_rest_ref("elas")

    assert rest.rest_ref == "ELAS"
    assert patch_supabase_client.calls[-1].filters["eq:rest_ref"] == "ELAS"


def test_restaurant_master_get_admins_fetches_live_column(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="restaurant_master",
        verb="select",
        response=FakeSupabaseResponse(data=[{"admins": ["447400000001"]}]),
    )
    rest = RestaurantMaster(**_restaurant_row(admins=[]))

    assert rest.get_admins() == ["447400000001"]


def test_restaurant_master_auto_accept_defaults_false_and_accepts_true() -> None:
    assert RestaurantMaster(**_restaurant_row()).auto_accept is False
    assert RestaurantMaster(**_restaurant_row(auto_accept=True)).auto_accept is True


def test_customer_master_defaults_missing_address_bits() -> None:
    customer = CustomerMaster(cust_id="447400000000", house_number=None, street_name=None)

    assert customer.house_number == "999"
    assert customer.street_name == ""


def test_customer_master_from_customer_id_alias(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="customer_master",
        verb="select",
        response=FakeSupabaseResponse(data=[_customer_row()]),
    )

    customer = CustomerMaster.from_customer_id("447400000000")

    assert customer.cust_id == "447400000000"
    assert patch_supabase_client.calls[-1].filters["eq:cust_id"] == "447400000000"


def test_customer_master_upsert_filters_unknown_fields(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="customer_master",
        verb="upsert",
        response=FakeSupabaseResponse(data=[_customer_row(cust_name="Updated")]),
    )

    customer = CustomerMaster.upsert(
        cust_id="447400000000",
        cust_name="Updated",
        not_a_column="ignored",
    )

    assert customer.cust_name == "Updated"
    assert "not_a_column" not in patch_supabase_client.calls[-1].payload


def test_cust_rest_map_fetches_uppercase_rest_ref(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="cust_rest_map",
        verb="select",
        response=FakeSupabaseResponse(data=[{"cust_id": "447400000000", "rest_ref": "ELAS", "has_consent": True}]),
    )

    crm = CustRestMap.from_cust_id_and_rest_ref("447400000000", "elas")

    assert crm.has_consent is True
    assert patch_supabase_client.calls[-1].filters["eq:rest_ref"] == "ELAS"


def test_cust_rest_map_upsert_serializes_consent_timestamp(patch_supabase_client) -> None:
    consent_dtts = datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc)
    patch_supabase_client.register(
        table="cust_rest_map",
        verb="upsert",
        response=FakeSupabaseResponse(data=[{"cust_id": "447400000000", "rest_ref": "ELAS", "has_consent": True, "consent_dtts": consent_dtts}]),
    )

    crm = CustRestMap.upsert("447400000000", "elas", True, consent_dtts)

    assert crm.rest_ref == "ELAS"
    assert patch_supabase_client.calls[-1].payload["consent_dtts"] == consent_dtts.isoformat()


def test_cust_rest_map_ask_for_marketing_consent_branches() -> None:
    assert CustRestMap(cust_id="1", rest_ref="ELAS", has_consent=True).ask_for_marketing_consent() is False
    assert CustRestMap(cust_id="1", rest_ref="ELAS", has_consent=False, consent_dtts=None).ask_for_marketing_consent() is True
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    old = datetime.now(timezone.utc) - timedelta(days=31)
    assert CustRestMap(cust_id="1", rest_ref="ELAS", has_consent=False, consent_dtts=recent).ask_for_marketing_consent(30) is False
    assert CustRestMap(cust_id="1", rest_ref="ELAS", has_consent=False, consent_dtts=old).ask_for_marketing_consent(30) is True
    with pytest.raises(ValueError):
        CustRestMap(cust_id="1", rest_ref="ELAS").ask_for_marketing_consent(-1)


def test_request_models_validate_required_fields() -> None:
    CreateOrUpdateCustomerRequest(cust_id="1", rest_ref="ELAS")
    UpdateAddressRequest(cust_id="1", rest_ref="ELAS", city="London", postcode="SW1A", lat=51.5, lon=-0.12)
    UpdateCustRestMapRequest(cust_id="1", rest_ref="ELAS", has_consent=False)

    with pytest.raises(ValidationError):
        UpdateAddressRequest(cust_id="1", rest_ref="ELAS", city="London", postcode="SW1A", lat=51.5)
