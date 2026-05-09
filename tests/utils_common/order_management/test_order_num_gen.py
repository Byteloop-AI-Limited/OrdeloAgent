"""Tests for order-number generation and decoding utilities.

These tests freeze the module's ``datetime`` dependency so the generated hash is
stable while still exercising the real SHA-256 based implementation.

Key Functions:
  - test_create_order_number_is_deterministic_for_same_day
  - test_create_order_number_uses_last_four_digits
  - test_create_order_number_rejects_non_four_digit_suffix
  - test_decode_order_number_round_trips_encoded_suffix
  - test_decode_order_number_rejects_wrong_length
"""

from __future__ import annotations

import pytest

from utils_common.order_management import order_num_gen


class _FrozenDateTime:
    @classmethod
    def now(cls):
        return cls()

    def strftime(self, fmt: str) -> str:
        assert fmt == "%Y%m%d"
        return "20260509"


def test_create_order_number_is_deterministic_for_same_day(monkeypatch) -> None:
    monkeypatch.setattr(order_num_gen, "datetime", _FrozenDateTime)

    first = order_num_gen.create_order_number("447448440754")
    second = order_num_gen.create_order_number("0754")

    assert first == second
    assert len(first) == 4
    assert first.islower()
    assert first.isalpha()


def test_create_order_number_uses_last_four_digits(monkeypatch) -> None:
    monkeypatch.setattr(order_num_gen, "datetime", _FrozenDateTime)

    assert order_num_gen.create_order_number("447448440754") == order_num_gen.create_order_number("000000000754")


def test_create_order_number_rejects_non_four_digit_suffix(monkeypatch) -> None:
    monkeypatch.setattr(order_num_gen, "datetime", _FrozenDateTime)

    with pytest.raises(ValueError, match="4-digit"):
        order_num_gen.create_order_number("abc")

    with pytest.raises(ValueError, match="4-digit"):
        order_num_gen.create_order_number("44740000ABCD")


def test_decode_order_number_round_trips_encoded_suffix(monkeypatch) -> None:
    monkeypatch.setattr(order_num_gen, "datetime", _FrozenDateTime)
    encoded = order_num_gen.create_order_number("447448440754")

    assert order_num_gen.decode_order_number(encoded) == "0754"


def test_decode_order_number_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="4 characters"):
        order_num_gen.decode_order_number("abc")
