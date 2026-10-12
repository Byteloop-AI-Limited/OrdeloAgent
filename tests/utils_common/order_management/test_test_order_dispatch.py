"""Audience checks are independent of payment mode and ordering customer."""
import pytest

from utils_common.order_management import test_order_dispatch as dispatch
from tests.fixtures.fake_supabase import FakeSupabaseResponse


@pytest.mark.parametrize("marker,rider,expected", [(False,"NORMAL",True), (True,"OPS2",True), (True,"NORMAL",False)])
async def test_order_scoped_marker_and_trimmed_current_membership(monkeypatch, fake_supabase, marker, rider, expected):
    monkeypatch.setattr(dispatch, "client_ordelo", fake_supabase)
    fake_supabase.register_rpc("order_has_test_item", FakeSupabaseResponse(data=marker))
    fake_supabase.register(table="ordelo_config", verb="select", response=FakeSupabaseResponse(data=[{"config_value":" OPS1, OPS2, "}]))
    assert await dispatch.rider_dispatch_allowed("ELAS-A-1", rider) is expected
    assert fake_supabase.rpc_calls[0].payload["args"] == {"p_order_number":"ELAS-A-1"}
    assert any(call.table == "ordelo_config" for call in fake_supabase.calls) is marker


@pytest.mark.parametrize("response", [None, "false", [], RuntimeError("database failed")])
async def test_missing_or_failed_order_classification_never_fans_out(monkeypatch, fake_supabase, response):
    monkeypatch.setattr(dispatch, "client_ordelo", fake_supabase)
    fake_supabase.register_rpc("order_has_test_item", response if isinstance(response, Exception) else FakeSupabaseResponse(data=response))
    assert not await dispatch.rider_dispatch_allowed("UNKNOWN", "NORMAL")


async def test_membership_is_rechecked_at_send_time(monkeypatch, fake_supabase):
    monkeypatch.setattr(dispatch, "client_ordelo", fake_supabase)
    fake_supabase.register_rpc("order_has_test_item", FakeSupabaseResponse(data=True))
    fake_supabase.register(table="ordelo_config", response=FakeSupabaseResponse(data=[{"config_value":"OPS"}]))
    assert await dispatch.rider_dispatch_allowed("ELAS-A-1", "OPS")
    fake_supabase.register(table="ordelo_config", response=FakeSupabaseResponse(data=[]))
    assert not await dispatch.rider_dispatch_allowed("ELAS-A-1", "OPS")
    fake_supabase.register(table="ordelo_config", response=RuntimeError("database failed"))
    assert not await dispatch.rider_dispatch_allowed("ELAS-A-1", "OPS")
