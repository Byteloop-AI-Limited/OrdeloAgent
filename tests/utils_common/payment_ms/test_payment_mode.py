"""Tests for test-payment permission (plan D32).

Key Functions:
  - test_overwatch_recipient_is_allowed
  - test_listed_restaurant_is_allowed_for_web_customer
  - test_everyone_else_is_refused_and_lookup_failures_refuse
"""

from __future__ import annotations

from utils_common.payment_ms import payment_mode


async def test_overwatch_recipient_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(payment_mode, "get_overwatch_list", lambda: ["447400000000"])

    async def _csv(key):
        return frozenset()

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    assert await payment_mode.is_test_payment_allowed("447400000000", "elas") == (True, "overwatch_recipient")


async def test_listed_restaurant_is_allowed_for_web_customer(monkeypatch) -> None:
    monkeypatch.setattr(payment_mode, "get_overwatch_list", lambda: ["447400000000"])
    seen = []

    async def _csv(key):
        seen.append(key)
        return frozenset({"BNAT"})

    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    assert await payment_mode.is_test_payment_allowed("W7K2M9QX4TPA", "bnat") == (True, "test_restaurant")
    assert seen == ["TEST_PAYMENT_REST_REFS"]


async def test_everyone_else_is_refused_and_lookup_failures_refuse(monkeypatch) -> None:
    def _broken():
        raise ValueError("No config found for overwatch_list")

    async def _csv(key):
        return frozenset({"BNAT"})

    monkeypatch.setattr(payment_mode, "get_overwatch_list", _broken)
    monkeypatch.setattr(payment_mode, "config_csv", _csv)
    assert await payment_mode.is_test_payment_allowed("447411111111", "sfcs") == (False, "not_allowed")
