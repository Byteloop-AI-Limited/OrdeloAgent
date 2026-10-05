"""Tests for the payment-mode rule (plan D32, simplified by R3.1 / D35).

Key Functions:
  - test_test_restaurant_is_test_without_asking
  - test_overwatch_recipient_can_request_test_elsewhere
  - test_everyone_else_pays_live_and_overwatch_lookup_failure_refuses
  - test_failed_test_list_lookup_fails_the_order_instead_of_going_live
"""

from __future__ import annotations

import pytest

from utils_common.payment_ms import payment_mode


def _config(monkeypatch, test_refs=frozenset({"BNAT"}), overwatch=lambda: ["447400000000"]):
    seen = []

    async def _csv(key, **kwargs):
        seen.append((key, kwargs))
        return frozenset(test_refs)

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    monkeypatch.setattr(payment_mode, "get_overwatch_list", overwatch)
    return seen


async def test_test_restaurant_is_test_without_asking(monkeypatch) -> None:
    seen = _config(monkeypatch)
    assert await payment_mode.resolve_payment_mode("W7K2M9QX4TPA", "bnat", requested=False) == ("test", "test_restaurant")
    assert await payment_mode.resolve_payment_mode("447411111111", "BNAT", requested=False) == ("test", "test_restaurant")
    assert seen[0] == ("TEST_PAYMENT_REST_REFS", {"fail_on_error": True})


async def test_overwatch_recipient_can_request_test_elsewhere(monkeypatch) -> None:
    _config(monkeypatch)
    assert await payment_mode.resolve_payment_mode("447400000000", "elas", requested=True) == ("test", "overwatch_recipient")
    # Not requested: left to today's overwatch + delivery rule in FoodOrder.
    assert await payment_mode.resolve_payment_mode("447400000000", "elas", requested=False) == (None, "not_requested")


async def test_everyone_else_pays_live_and_overwatch_lookup_failure_refuses(monkeypatch) -> None:
    def _broken():
        raise ValueError("No config found for overwatch_list")

    _config(monkeypatch, overwatch=_broken)
    assert await payment_mode.resolve_payment_mode("447411111111", "sfcs", requested=True) == (None, "not_allowed")
    assert await payment_mode.resolve_payment_mode("W7K2M9QX4TPA", "crms", requested=True) == (None, "not_allowed")


async def test_failed_test_list_lookup_fails_the_order_instead_of_going_live(monkeypatch) -> None:
    """A test restaurant must never silently take a live payment."""
    async def _csv(key, **kwargs):
        if kwargs.get("fail_on_error"):
            raise RuntimeError("database down")
        return frozenset()

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    with pytest.raises(RuntimeError):
        await payment_mode.resolve_payment_mode("447411111111", "bnat", requested=False)
