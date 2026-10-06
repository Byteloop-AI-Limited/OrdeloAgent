"""Tests for order references (plan M1) and customer keys.

Key Functions:
  - test_phone_recipient_keeps_legacy_reference
  - test_web_customer_key_gets_random_reference_from_unambiguous_alphabet
  - test_is_web_customer_key_and_new_web_customer_key
"""

from __future__ import annotations

from utils_common.order_management import order_db_ops_new
from utils_common.order_management.customer_keys import is_web_customer_key, new_web_customer_key
from utils_common.order_management.order_reference import (
    RANDOM_REFERENCE_ALPHABET,
    is_phone_derived,
    new_order_reference,
)


def test_phone_recipient_keeps_legacy_reference() -> None:
    for recipient in ("447448440754", "447400000000", "0754"):
        assert is_phone_derived(recipient)
        assert new_order_reference(recipient, "2026-10-01") == order_db_ops_new.create_order_reference(recipient, "2026-10-01")


def test_web_customer_key_gets_random_reference_from_unambiguous_alphabet() -> None:
    w_id = "W7K2M9QX2345"  # ends in four digits but is a W-id
    assert not is_phone_derived(w_id)
    refs = {new_order_reference(w_id, "2026-10-01") for _ in range(50)}
    assert len(refs) > 1
    for ref in refs:
        assert len(ref) == 4 and set(ref) <= set(RANDOM_REFERENCE_ALPHABET)
        assert not set(ref) & {"I", "L", "O"}


def test_is_web_customer_key_and_new_web_customer_key() -> None:
    minted = {new_web_customer_key() for _ in range(20)}
    assert all(is_web_customer_key(k) and len(k) == 12 for k in minted)
    assert len(minted) == 20
    assert is_web_customer_key("W7K2M9QX4TPA")
    for not_w_id in ("447400000000", "w7k2m9qx4tpa", "W7K2M9QX4TP", "W7K2M9QX4TPA1", "X7K2M9QX4TPA", "", None):
        assert not is_web_customer_key(not_w_id)
