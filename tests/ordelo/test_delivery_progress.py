"""Tests for the delivery-progress gate (ordelo.delivery_progress).

Covers every DeliveryProgress outcome check_delivery_progress() can produce,
both keying modes (order_number vs rider_id), the stale cross-order button
case, and fail-closed behaviour on read errors -- without a real DB.

Key Functions:
  - test_no_inflight_row_is_not_in_progress
  - test_inflight_with_assigned_dispatch_is_awaiting_pickup
  - test_inflight_with_pickedup_dispatch_is_picked_up
  - test_inflight_with_completed_dispatch_is_picked_up
  - test_rider_keyed_mismatched_order_number_is_stale_not_in_progress
  - test_rider_keyed_matching_order_number_is_awaiting_pickup
  - test_rider_keyed_no_order_number_skips_cross_order_check
  - test_inflight_read_failure_is_unknown
  - test_dispatch_read_failure_is_unknown
  - test_missing_dispatch_row_is_unknown
  - test_neither_identifier_is_unknown_and_does_not_query
  - test_order_number_keyed_query_filters_on_order_number
  - test_rider_keyed_query_filters_on_rider_id
"""

from __future__ import annotations

from ordelo.delivery_progress import DeliveryProgress, check_delivery_progress
from tests.fixtures.fake_supabase import FakeSupabaseResponse


def _inflight_row(**overrides):
    row = {"dispatch_id": 101, "order_number": "ELAS-ABCD-1", "rider_id": "RIDER01"}
    row.update(overrides)
    return row


async def test_no_inflight_row_is_not_in_progress(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[])
    )

    progress, row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.NOT_IN_PROGRESS
    assert row is None


async def test_inflight_with_assigned_dispatch_is_awaiting_pickup(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "assigned"}]),
    )

    progress, row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.AWAITING_PICKUP
    assert row["rider_id"] == "RIDER01"


async def test_inflight_with_pickedup_dispatch_is_picked_up(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "pickedup"}]),
    )

    progress, row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.PICKED_UP
    assert row is not None


async def test_inflight_with_completed_dispatch_is_picked_up(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "completed"}]),
    )

    progress, _row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.PICKED_UP


async def test_rider_keyed_mismatched_order_number_is_stale_not_in_progress(
    patch_supabase_client,
) -> None:
    # Rider is inflight, but on a different (newer) job than the stale button names.
    patch_supabase_client.register(
        table="delivery_inflight",
        verb="select",
        response=FakeSupabaseResponse(data=[_inflight_row(order_number="ELAS-NEWJ-9")]),
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "assigned"}]),
    )

    progress, _row = await check_delivery_progress(
        rider_id="RIDER01", order_number="ELAS-ABCD-1"
    )

    assert progress is DeliveryProgress.NOT_IN_PROGRESS


async def test_rider_keyed_matching_order_number_is_awaiting_pickup(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "assigned"}]),
    )

    progress, _row = await check_delivery_progress(
        rider_id="RIDER01", order_number="ELAS-ABCD-1"
    )

    assert progress is DeliveryProgress.AWAITING_PICKUP


async def test_rider_keyed_no_order_number_skips_cross_order_check(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight",
        verb="select",
        response=FakeSupabaseResponse(data=[_inflight_row(order_number="ELAS-WHATEVER-3")]),
    )
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="select",
        response=FakeSupabaseResponse(data=[{"status": "assigned"}]),
    )

    progress, _row = await check_delivery_progress(rider_id="RIDER01")

    assert progress is DeliveryProgress.AWAITING_PICKUP


async def test_inflight_read_failure_is_unknown(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=RuntimeError("db down")
    )

    progress, row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.UNKNOWN
    assert row is None


async def test_dispatch_read_failure_is_unknown(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch", verb="select", response=RuntimeError("db down")
    )

    progress, row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.UNKNOWN
    # The inflight row is still returned -- callers may want the rider_id even
    # when the pickup status itself couldn't be resolved.
    assert row is not None


async def test_missing_dispatch_row_is_unknown(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[_inflight_row()])
    )
    patch_supabase_client.register(
        table="delivery_dispatch", verb="select", response=FakeSupabaseResponse(data=[])
    )

    progress, _row = await check_delivery_progress(order_number="ELAS-ABCD-1")

    assert progress is DeliveryProgress.UNKNOWN


async def test_neither_identifier_is_unknown_and_does_not_query(patch_supabase_client) -> None:
    # A caller bug (e.g. a callback missing an expected field) must surface as
    # UNKNOWN, not silently query on NULL and read back NOT_IN_PROGRESS -- which
    # would be indistinguishable from a genuinely finished order.
    progress, row = await check_delivery_progress()

    assert progress is DeliveryProgress.UNKNOWN
    assert row is None
    assert patch_supabase_client.calls == []


async def test_order_number_keyed_query_filters_on_order_number(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[])
    )

    await check_delivery_progress(order_number="ELAS-ABCD-1")

    inflight_call = next(c for c in patch_supabase_client.calls if c.table == "delivery_inflight")
    assert inflight_call.filters == {"eq:order_number": "ELAS-ABCD-1"}


async def test_rider_keyed_query_filters_on_rider_id(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_inflight", verb="select", response=FakeSupabaseResponse(data=[])
    )

    await check_delivery_progress(rider_id="RIDER01")

    inflight_call = next(c for c in patch_supabase_client.calls if c.table == "delivery_inflight")
    assert inflight_call.filters == {"eq:rider_id": "RIDER01"}
