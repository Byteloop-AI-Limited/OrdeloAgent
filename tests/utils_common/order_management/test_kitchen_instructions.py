"""Shared, channel-free kitchen wording and UK pickup-time formatting."""

from datetime import datetime, timezone

import pytest

from utils_common.order_management.kitchen_instructions import KitchenInstruction, hold, no_rider, start


@pytest.mark.parametrize("order_type,expected", [
    ("delivery", KitchenInstruction("⏳ Don't start cooking yet — we're finding a rider.", "Start when the kitchen receipt arrives.")),
    ("takeaway", None),
])
def test_hold(order_type, expected):
    assert hold(order_type) == expected


@pytest.mark.parametrize("pickup,at", [
    ("2026-11-17T23:14:00Z", "11:14 PM"),
    (datetime(2026, 11, 17, 23, 14, tzinfo=timezone.utc), "11:14 PM"),
    ("2026-07-17T12:14:00Z", "1:14 PM"),  # BST
    (None, None),
])
@pytest.mark.parametrize("order_type", ["delivery", "takeaway"])
def test_start(order_type, pickup, at):
    detail = ((f"Rider found · ready for pickup at {at}" if at else "Rider found") if order_type == "delivery"
              else (f"Ready for collection at {at}" if at else "Get it ready for collection"))
    assert start(order_type, pickup) == KitchenInstruction("🍳 Please start preparing now", detail)


def test_no_rider():
    assert no_rider("STRK-FPBH-33") == KitchenInstruction(
        "❌ No rider found for STRK-FPBH-33.", "The order is cancelled — please don't prepare it.")
