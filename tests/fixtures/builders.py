"""Test data builders for OrdeloAgent Pydantic models.

Centralised factory functions yielding valid model instances with sensible
defaults so individual tests stay focused on the fields they care about.

Key Functions:
  - delivery_summary - DeliverySummary builder
  - delivery_dispatch - DeliveryDispatch builder
  - delivery_detail - DeliveryDetail builder
  - restaurant_master - RestaurantMaster builder
  - customer_master - CustomerMaster builder
"""

from __future__ import annotations

from typing import Any

import pytest


def _merge(defaults: dict, overrides: dict) -> dict:
    out = dict(defaults)
    out.update(overrides)
    return out


@pytest.fixture
def delivery_summary():
    """Factory returning a ``DeliverySummary`` with overridable defaults."""

    def _build(**overrides: Any):
        from ordelo_datamodels.delivery_pymodels import DeliverySummary

        defaults = {
            "order_number": "ORD12345",
            "rest_id": "REST001",
            "rest_name": "Test Restaurant",
            "rest_lat": 51.5074,
            "rest_lon": -0.1278,
            "rest_address": "1 Test Street, London",
            "customer_id": 42,
            "customer_name": "Test Customer",
            "customer_lat": 51.5174,
            "customer_lon": -0.1378,
            "customer_address": "2 Customer Avenue, London",
            "customer_phone": "447400000000",
            "vehicle_type": "bike",
            "rider_payout": 5.0,
            "status": "unassigned",
            "dtts": "2026-01-15T12:00:00Z",
        }
        return DeliverySummary(**_merge(defaults, overrides))

    return _build


@pytest.fixture
def delivery_dispatch():
    def _build(**overrides: Any):
        from ordelo_datamodels.delivery_pymodels import DeliveryDispatch

        defaults = {
            "order_number": "ORD12345",
            "rider_id": "447400000001",
            "rider_payout": 5.0,
            "dispatch_id": 1,
            "status": "pending",
        }
        return DeliveryDispatch(**_merge(defaults, overrides))

    return _build


@pytest.fixture
def delivery_detail():
    def _build(**overrides: Any):
        from ordelo_datamodels.delivery_pymodels import DeliveryDetail

        defaults = {
            "order_number": "ORD12345",
            "vehicle_type": "bike",
            "rider_payout": 5.0,
            "rest_lat": 51.5074,
            "rest_lon": -0.1278,
            "customer_lat": 51.5174,
            "customer_lon": -0.1378,
        }
        return DeliveryDetail(**_merge(defaults, overrides))

    return _build


@pytest.fixture
def restaurant_master():
    def _build(**overrides: Any):
        from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

        defaults = {
            "rest_ref": "TEST",
            "rest_id": "REST001",
            "rest_name": "Test Restaurant",
        }
        return RestaurantMaster(**_merge(defaults, overrides))

    return _build


@pytest.fixture
def customer_master():
    def _build(**overrides: Any):
        from ordelo_datamodels.customer_master_pymodel import CustomerMaster

        defaults = {
            "cust_id": "447400000000",
            "cust_name": "Test Customer",
        }
        return CustomerMaster(**_merge(defaults, overrides))

    return _build
