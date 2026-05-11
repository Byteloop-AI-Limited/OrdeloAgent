"""Tests for delivery-related Pydantic models and DB lookup helpers.

The classmethod lookup tests use ``FakeSupabaseClient`` so they exercise the
real query-chain code without touching Supabase.

Key Functions:
  - test_delivery_detail_google_maps_url
  - test_delivery_summary_validates_required_fields_and_lengths
  - test_delivery_dispatch_validates_rider_id_length
  - test_delivery_detail_from_order_number_fetches_first_row
  - test_delivery_summary_from_order_number_raises_when_missing
  - test_delivery_dispatch_from_dispatch_id_fetches_first_row
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from ordelo_datamodels.delivery_pymodels import (
    DeliveryDetail,
    DeliveryDispatch,
    DeliverySummary,
)
from tests.fixtures.fake_supabase import FakeSupabaseResponse


def _delivery_detail_row(**overrides):
    row = {
        "order_number": "ORD123",
        "vehicle_type": "bike",
        "rider_payout": 5.5,
        "distance": 2.3,
        "rest_id": "REST001",
        "rest_name": "Test Restaurant",
        "rest_lon": -0.1278,
        "rest_lat": 51.5074,
        "rest_address": "1 Test Street",
        "town": "London",
        "customer_id": "CUST001",
        "customer_name": "Test Customer",
        "customer_lon": -0.1378,
        "customer_lat": 51.5174,
        "customer_address": "2 Customer Road",
        "status": "assigned",
        "dispatch_id": 10,
        "rider_id": "447400000001",
    }
    row.update(overrides)
    return row


def _delivery_summary_row(**overrides):
    row = {
        "order_number": "ORD123",
        "rest_id": "REST001",
        "rest_name": "Test Restaurant",
        "rest_lon": -0.1278,
        "rest_lat": 51.5074,
        "rest_address": "1 Test Street",
        "town": "London",
        "customer_id": "CUST001",
        "customer_name": "Test Customer",
        "customer_lon": -0.1378,
        "customer_lat": 51.5174,
        "customer_address": "2 Customer Road",
        "status": "unassigned",
        "rest_confirmation_code": 1111,
        "cust_confirmation_code": 2222,
        "pickup_date": date(2026, 5, 9),
        "dt": date(2026, 5, 9),
        "dtts": datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _dispatch_row(**overrides):
    row = {
        "dispatch_id": 10,
        "order_number": "ORD123",
        "rider_id": "447400000001",
        "rider_payout": 5.5,
        "vehicle_type": "bike",
        "distance": 2.3,
        "status": "pending",
    }
    row.update(overrides)
    return row


def test_delivery_detail_google_maps_url() -> None:
    detail = DeliveryDetail(**_delivery_detail_row())

    assert detail.google_maps_url == "https://maps.google.com/maps?dirflg=d&saddr=51.5074,-0.1278&daddr=51.5174,-0.1378"


def test_delivery_summary_validates_required_fields_and_lengths() -> None:
    summary = DeliverySummary(**_delivery_summary_row(rest_id="R" * 12))
    assert summary.restaurant_confirmation_status == "restaurant_unconfirmed"

    with pytest.raises(ValidationError):
        DeliverySummary(**_delivery_summary_row(rest_id="R" * 13))


def test_delivery_dispatch_validates_rider_id_length() -> None:
    DeliveryDispatch(**_dispatch_row(rider_id="1" * 12))

    with pytest.raises(ValidationError):
        DeliveryDispatch(**_dispatch_row(rider_id="1" * 13))


def test_delivery_detail_from_order_number_fetches_first_row(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_detail",
        verb="select",
        response=FakeSupabaseResponse(data=[_delivery_detail_row()]),
    )

    detail = DeliveryDetail.from_order_number("ORD123")

    assert detail.order_number == "ORD123"
    assert patch_supabase_client.calls[-1].filters["eq:order_number"] == "ORD123"


def test_delivery_summary_from_order_number_raises_when_missing(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_summary",
        verb="select",
        response=FakeSupabaseResponse(data=[]),
    )

    with pytest.raises(ValueError, match="No delivery summary found"):
        DeliverySummary.from_order_number("MISSING")


def test_delivery_dispatch_from_dispatch_id_fetches_first_row(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[_dispatch_row()]),
    )

    dispatch = DeliveryDispatch.from_dispatch_id(10)

    assert dispatch.dispatch_id == 10
    assert patch_supabase_client.calls[-1].filters["eq:dispatch_id"] == 10
