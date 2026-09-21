"""Tests for the sys-admin rider payout router.

Covers the payout report's sourcing and aggregation contract: the RPC is called with the
full date range plus the excluded test riders, every row returned is reported (no silent
drops), rows are grouped per payee, and riders with no bank details on file stay visible
instead of disappearing. Also covers the range defaulting / validation on the endpoint and
the idempotent mark-as-paid path.

Key Functions:
  - test_fetch_payouts_calls_rpc_with_range_and_exclusions
  - test_fetch_payouts_reports_every_location
  - test_fetch_payouts_keeps_riders_without_bank_details_separate
  - test_fetch_payouts_handles_empty_report
  - test_get_rider_payout_defaults_end_to_start_plus_six_days
  - test_get_rider_payout_rejects_bad_range
  - test_update_paid_status_reports_skipped_rows
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from watomation.routers import sys_admin_auth_session as sas


def _row(**overrides) -> dict:
    """A single `get_rider_payout_report` row; override just what a test cares about."""
    row = {
        "dispatch_id": 101,
        "order_number": "ELAS-ABCD-1",
        "rest_ref": "ELAS",
        "rider_id": "447700900001",
        "rider_name": "Rishi",
        "town": "Salisbury",
        "vehicle_type": "car",
        "bank_account_name": "Rishi R",
        "sort_code": "12-34-56",
        "bank_account": "12345678",
        "rider_payout": 5.0,
        "distance": 1.2,
        "dtts": "2026-09-18T12:00:00",
        "paid_status": "unpaid",
        "paid_dtts": None,
    }
    row.update(overrides)
    return row


def test_fetch_payouts_calls_rpc_with_range_and_exclusions(patch_supabase_client) -> None:
    patch_supabase_client.register_rpc(
        sas.PAYOUT_REPORT_RPC, FakeSupabaseResponse(data=[_row()])
    )

    sas.fetch_payouts("2026-09-12", "2026-09-18")

    call = patch_supabase_client.rpc_calls[-1]
    assert call.payload["name"] == sas.PAYOUT_REPORT_RPC
    assert call.payload["args"] == {
        "p_start": "2026-09-12",
        "p_end": "2026-09-18",
        "p_exclude_riders": sas.EXCLUDE_RIDER_IDS,
    }


def test_fetch_payouts_reports_every_location(patch_supabase_client) -> None:
    """Orpington (BNAT) and Salisbury (ELAS/SFCS) rows must all survive.

    The previous implementation joined delivery_option by order_number alone and compared
    the collapsed row's vehicle_type to the rider's, which silently dropped most rows.
    """
    rows = [
        _row(dispatch_id=1, order_number="BNAT-AAAA-1", rest_ref="BNAT",
             rider_id="447700900010", rider_name="Rehan", town="Orpington",
             vehicle_type="scooter", bank_account_name="Rehan A",
             sort_code="11-11-11", bank_account="11111111", rider_payout=5.56),
        _row(dispatch_id=2, order_number="BNAT-BBBB-2", rest_ref="BNAT",
             rider_id="447700900010", rider_name="Rehan", town="Orpington",
             vehicle_type="scooter", bank_account_name="Rehan A",
             sort_code="11-11-11", bank_account="11111111", rider_payout=5.32),
        _row(dispatch_id=3, order_number="ELAS-CCCC-3", rest_ref="ELAS", rider_payout=7.86),
        _row(dispatch_id=4, order_number="SFCS-DDDD-4", rest_ref="SFCS", rider_payout=6.87),
    ]
    patch_supabase_client.register_rpc(sas.PAYOUT_REPORT_RPC, FakeSupabaseResponse(data=rows))

    report = sas.fetch_payouts("2026-09-12", "2026-09-18")

    assert report["total_orders"] == 4
    assert {r["town"] for r in report["detailed"]} == {"Orpington", "Salisbury"}
    assert {r["rest_ref"] for r in report["detailed"]} == {"BNAT", "ELAS", "SFCS"}

    # Two payees: Rehan (2 Orpington orders) and Rishi (2 Salisbury orders).
    assert len(report["aggregated"]) == 2
    by_name = {a["bank_account_name"]: a for a in report["aggregated"]}
    assert by_name["Rehan A"]["order_count"] == 2
    assert by_name["Rehan A"]["rider_payout"] == pytest.approx(10.88)
    assert by_name["Rehan A"]["towns"] == ["Orpington"]
    assert by_name["Rishi R"]["rider_payout"] == pytest.approx(14.73)

    # Aggregated rows are ordered by value owed, descending.
    assert [a["rider_payout"] for a in report["aggregated"]] == sorted(
        [a["rider_payout"] for a in report["aggregated"]], reverse=True
    )

    # Every detail row is reachable from its aggregated card.
    keys = {a["payee_key"] for a in report["aggregated"]}
    assert all(r["payee_key"] in keys for r in report["detailed"])


def test_fetch_payouts_keeps_riders_without_bank_details_separate(
    patch_supabase_client,
) -> None:
    rows = [
        _row(dispatch_id=1, rider_id="447700900020", rider_name="Majid", town="Orpington",
             bank_account_name=None, sort_code=None, bank_account=None, rider_payout=5.25),
        _row(dispatch_id=2, rider_id="447700900021", rider_name="Amar", town="Orpington",
             bank_account_name=None, sort_code=None, bank_account=None, rider_payout=4.75),
        _row(dispatch_id=3, rider_payout=6.0),
    ]
    patch_supabase_client.register_rpc(sas.PAYOUT_REPORT_RPC, FakeSupabaseResponse(data=rows))

    report = sas.fetch_payouts("2026-09-12", "2026-09-18")

    assert report["total_orders"] == 3
    unbanked = [a for a in report["aggregated"] if a["missing_bank_details"]]
    # Two distinct riders, not merged into a single "unknown" card.
    assert len(unbanked) == 2
    assert {n for a in unbanked for n in a["rider_names"]} == {"Majid", "Amar"}
    assert all(a["payee_key"].startswith("rider:") for a in unbanked)


def test_fetch_payouts_handles_empty_report(patch_supabase_client) -> None:
    patch_supabase_client.register_rpc(sas.PAYOUT_REPORT_RPC, FakeSupabaseResponse(data=None))

    report = sas.fetch_payouts("2026-09-12", "2026-09-18")

    assert report == {
        "start": "2026-09-12",
        "end": "2026-09-18",
        "total_orders": 0,
        "detailed": [],
        "aggregated": [],
    }


async def test_get_rider_payout_defaults_end_to_start_plus_six_days(
    patch_supabase_client,
) -> None:
    patch_supabase_client.register_rpc(sas.PAYOUT_REPORT_RPC, FakeSupabaseResponse(data=[]))

    report = await sas.get_rider_payout(start="2026-09-12", end=None)

    assert (report["start"], report["end"]) == ("2026-09-12", "2026-09-18")


@pytest.mark.parametrize(
    "start,end",
    [("not-a-date", None), ("2026-09-12", "nope"), ("2026-09-12", "2026-09-11")],
)
async def test_get_rider_payout_rejects_bad_range(start, end) -> None:
    with pytest.raises(HTTPException) as exc:
        await sas.get_rider_payout(start=start, end=end)
    assert exc.value.status_code == 400


async def test_update_paid_status_reports_skipped_rows(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="delivery_dispatch",
        verb="update",
        response=FakeSupabaseResponse(data=[{"dispatch_id": 101}]),
    )

    result = await sas.update_paid_status(sas.UpdatePaidRequest(dispatch_ids=[101, 102]))

    assert result.updated_count == 1
    assert result.dispatch_ids_updated == [101]
    assert result.dispatch_ids_skipped == [102]
