"""P7 takeaway hook branch coverage."""
from __future__ import annotations
from types import SimpleNamespace

import httpx
import respx

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.fixtures.fake_wa import FakeAsyncWhatsApp
from watomation.routers import takeaway_hooks


class _Bg:
    def __init__(self): self.tasks = []
    def add_task(self, f, *a, **kw): self.tasks.append({"func": f, "args": a, "kwargs": kw})


def _ts(**o):
    r = {"order_number": "ELAS-ABCD-1", "rest_id": "R1", "rest_name": "Elai", "rest_address": "1 St", "town": "London", "customer_id": "4474", "customer_name": "Cust", "status": "restaurant_confirming", "restaurant_confirmation_status": "restaurant_timedout", "rest_confirmation_code": 11, "pickup_time": None, "pickup_date": "2026-05-09", "rest_ref": "ELAS", "dt": "2026-05-09", "dtts": "2026-05-09T10:00:00+00:00"}
    r.update(o); return r


def _rm(**o):
    r = {"rest_id": "R1", "rest_ref": "ELAS", "rest_name": "Elai", "admins": ["A1"], "lon": -0.1, "lat": 51.5}
    r.update(o); return r


def _fo(**o):
    r = {"order_id": "ABCD-1", "order_number": "ELAS-ABCD-1", "recipient": "4474", "thread_id": "t1", "total_price": 20.0, "payment_status": "requires_payment", "action": "takeaway"}
    r.update(o); return r


async def test_unconfirmed_sends_to_admins(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp):
    monkeypatch.setattr(takeaway_hooks, "_async_wa_client", patch_async_wa_client)
    s = takeaway_hooks.TakeawaySummaryData(**_ts())
    rm = takeaway_hooks.RestaurantMasterData(**_rm(admins=["A1", "A2"]))
    fo = takeaway_hooks.FoodOrder(**_fo())
    r = await takeaway_hooks._handle_restaurant_unconfirmed(s, rm, fo, [])
    assert r["action"] == "confirmation_sent"
    assert len(patch_async_wa_client.sent) == 2


async def test_accept_sends_pickup_time(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp):
    monkeypatch.setattr(takeaway_hooks, "_async_wa_client", patch_async_wa_client)
    s = takeaway_hooks.TakeawaySummaryData(**_ts())
    rm = takeaway_hooks.RestaurantMasterData(**_rm())
    fo = takeaway_hooks.FoodOrder(**_fo())
    r = await takeaway_hooks._handle_restaurant_accept(s, rm, fo, [])
    assert r["action"] == "pickup_time_sent"
    assert len(patch_async_wa_client.sent) == 1


async def test_decline_cancels_payment(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp, patch_supabase_client):
    monkeypatch.setattr(takeaway_hooks, "_async_wa_client", patch_async_wa_client)
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(table="takeaway_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    cc = []
    async def _c(**kw): cc.append(kw)
    monkeypatch.setattr(takeaway_hooks, "cancel_payment", _c)
    r = await takeaway_hooks._handle_restaurant_decline(takeaway_hooks.TakeawaySummaryData(**_ts()), takeaway_hooks.FoodOrder(**_fo()))
    assert cc == [{"order_number": "ELAS-ABCD-1"}]
    assert "cancelled" in patch_async_wa_client.sent[-1].kwargs["text"]


async def test_decline_pay_at_rest_skips_cancel(monkeypatch, patch_async_wa_client: FakeAsyncWhatsApp, patch_supabase_client):
    monkeypatch.setattr(takeaway_hooks, "_async_wa_client", patch_async_wa_client)
    monkeypatch.setattr(takeaway_hooks, "client_ordelo", patch_supabase_client)
    patch_supabase_client.register(table="takeaway_summary", verb="update", response=FakeSupabaseResponse(data=[{"ok": True}]))
    r = await takeaway_hooks._handle_restaurant_decline(takeaway_hooks.TakeawaySummaryData(**_ts()), takeaway_hooks.FoodOrder(**_fo(payment_status="pay_at_rest")))
    assert "cancelled" not in patch_async_wa_client.sent[-1].kwargs["text"]


async def test_confirmation_flow_routes_unconfirmed():
    bg = _Bg()
    p = {"trigger_reason": "restaurant_unconfirmed", "takeaway_summary": _ts(restaurant_confirmation_status="restaurant_unconfirmed"), "restaurant_master": _rm(), "food_order": _fo(), "order_items": []}
    r = await takeaway_hooks.restaurant_confirmation_flow(bg, payload=p)
    assert r["status"] == "accepted"
    assert bg.tasks[0]["func"] == takeaway_hooks._handle_restaurant_unconfirmed


async def test_confirmation_flow_unknown_trigger():
    p = {"trigger_reason": "bad", "takeaway_summary": _ts(), "restaurant_master": _rm(), "food_order": _fo(), "order_items": []}
    r = await takeaway_hooks.restaurant_confirmation_flow(_Bg(), payload=p)
    assert r["status"] == "error"


async def test_confirmation_flow_no_admins():
    p = {"trigger_reason": "restaurant_unconfirmed", "takeaway_summary": _ts(), "restaurant_master": _rm(admins=[]), "food_order": _fo(), "order_items": []}
    r = await takeaway_hooks.restaurant_confirmation_flow(_Bg(), payload=p)
    assert r == {"status": "error", "message": "No restaurant contacts", "order_number": "ELAS-ABCD-1"}


@respx.mock
async def test_pickup_time_set_posts_webhook(monkeypatch):
    async def _wh(*a, **kw): return "https://r.example.com/pt"
    monkeypatch.setattr(takeaway_hooks, "get_restaurant_webhook_url_async", _wh)
    route = respx.post("https://r.example.com/pt").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    s = takeaway_hooks.TakeawaySummaryData(**_ts(pickup_time="2026-05-09T12:30:00+00:00"))
    rm = takeaway_hooks.RestaurantMasterData(**_rm())
    assert await takeaway_hooks._post_pickup_time_event(s, rm) is None
    assert route.called


async def test_pay_at_rest_pickup_time_generates_print_only_job(monkeypatch):
    calls = []

    async def _pu(*args, **kwargs):
        calls.append((args, kwargs))
        return "https://p.example.com/print"

    monkeypatch.setattr(takeaway_hooks, "generate_automatic_payment_url", _pu)
    monkeypatch.setattr(
        takeaway_hooks.FoodOrder,
        "from_order_number",
        staticmethod(
            lambda **_: SimpleNamespace(
                order_id="ABCD-1",
                payment_uri="https://payment.example.com/print",
                payment_status="pay_at_rest",
            )
        ),
    )

    assert await takeaway_hooks.capture_takeaway_payment("ELAS-ABCD-1") is None
    assert len(calls) == 1
    assert calls[0][1] == {"is_print_only": True}


async def test_init_takeaway_order_requires_customer_id():
    r = await takeaway_hooks.init_takeaway_order(_Bg(), payload={"order_number": "ELAS-ABCD-1"})
    assert r["status"] == "error"


async def test_init_takeaway_order_schedules_summary():
    bg = _Bg()
    r = await takeaway_hooks.init_takeaway_order(bg, payload={"order_number": "ELAS-ABCD-1", "customer_id": "4474"})
    assert r["status"] == "accepted"
    assert bg.tasks[0]["func"] == takeaway_hooks.init_takeaway_summary


def test_format_pickup_time_display():
    assert takeaway_hooks._format_pickup_time_display("2026-05-09T12:30:00+01:00") is not None
