"""Tests for the payment events inbox (plan M2).

Key Functions:
  - test_parse_stripe_checkout_session_completed
  - test_parse_body_without_event_id_uses_order_key
  - test_parse_ignores_other_event_types_and_rejects_missing_order
  - test_record_payment_authorised_calls_rpc_and_maps_outcome
"""

from __future__ import annotations

import pytest

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from utils_common.payment_ms import payment_events


def _stripe_body() -> dict:
    return {
        "id": "evt_123",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_1",
            "payment_intent": "pi_1",
            "amount_total": 1948,
            "metadata": {"orderID": "QKZD-31", "threadID": "WEB-1"},
            "customer_details": {"email": "a@example.com"},
        }},
    }


def test_parse_stripe_checkout_session_completed() -> None:
    evt = payment_events.parse_payment_complete(_stripe_body())

    assert evt.provider_event_id == "evt_123"
    assert evt.order_id == "QKZD-31"
    assert evt.payment_intent_id == "pi_1"
    assert evt.amount_pence == 1948
    assert evt.payload == {"type": "checkout.session.completed", "session_id": "cs_test_1", "source": "stripe"}
    assert "a@example.com" not in str(evt.payload)


def test_parse_body_without_event_id_uses_order_key() -> None:
    evt = payment_events.parse_payment_complete({"data": {"object": {"metadata": {"orderID": "ABCD-1"}}}})

    assert evt.provider_event_id == "authorised:ABCD-1"
    assert evt.payment_intent_id is None
    assert evt.payload["source"] == "ordelo_or_test"


def test_parse_ignores_other_event_types_and_rejects_missing_order() -> None:
    other = _stripe_body() | {"type": "payment_intent.created"}
    assert payment_events.parse_payment_complete(other) is None

    with pytest.raises(ValueError):
        payment_events.parse_payment_complete({"data": {"object": {"metadata": {}}}})


async def test_record_payment_authorised_calls_rpc_and_maps_outcome(patch_supabase_client) -> None:
    patch_supabase_client.register_rpc(
        "record_payment_authorised",
        FakeSupabaseResponse(data={"outcome": "applied", "order": {"order_id": "QKZD-31"}}),
    )
    evt = payment_events.parse_payment_complete(_stripe_body())

    outcome = await payment_events.record_payment_authorised(evt)

    assert outcome.applied and outcome.order == {"order_id": "QKZD-31"}
    call = patch_supabase_client.rpc_calls[-1]
    assert call.payload["args"] == {
        "p_provider_event_id": "evt_123",
        "p_order_id": "QKZD-31",
        "p_payment_intent_id": "pi_1",
        "p_amount_pence": 1948,
        "p_payload": evt.payload,
    }

    patch_supabase_client.register_rpc(
        "record_payment_authorised",
        FakeSupabaseResponse(data={"outcome": "rejected_state", "payment_status": "requires_capture"}),
    )
    outcome = await payment_events.record_payment_authorised(evt)
    assert not outcome.applied
    assert outcome.payment_status == "requires_capture"
