"""Frozen HTTP contracts for all ten restaurant-app notification hooks.

The snapshots were recorded against the legacy hooks before R1b. Since R3.1
(D35) every hook goes through the customer notifier for every restaurant, with
no ordelo_config rows; the bytes sent to the restaurant app are unchanged.
All HTTP and persistence is local.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from ordelo import agent_app_handlers
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from tests.watomation.routers.test_takeaway_hooks import (
    _restaurant_master_row,
    _takeaway_summary_row,
)
from watomation import on_callback_wa_handler
from watomation.routers import (
    customer_hooks,
    delivery_hooks,
    location_hooks,
    order_hooks,
    payment_hooks,
    takeaway_hooks,
)

SNAPSHOTS = Path(__file__).with_name("customer_notification_contracts.json")
ORDER = "ELAS-ABCD-1"
PHONE = "447400000000"


@pytest.mark.parametrize("origin", ["whatsapp", "web"])
@pytest.mark.parametrize(
    "hook",
    [
        "payment",
        "capture_address",
        "update_address",
        "pickup_time",
        "nearby",
        "inflight",
        "timedout",
        "customer_cc",
        "restaurant_cc",
        "takeaway_ready",
    ],
)
@respx.mock
async def test_legacy_notification_contract(
    hook,
    origin,
    monkeypatch,
    patch_supabase_client,
    delivery_summary,
    feature_flags,
    actions_db,
):
    PHONE = "W7K2M9QX4TPA" if origin == "web" else "447400000000"
    async def webhook(rest_ref, event):
        return f"https://restaurant.example/{rest_ref}/{event}"

    from utils_common.notify import customer_notifier as notifier

    monkeypatch.setattr(notifier, "get_restaurant_webhook_url_async", webhook)
    state = {}

    async def record(order_number, event):
        state["data"] = event.data()
        return [1]

    async def claim(outbox_id):
        return {
            "order_number": ORDER,
            "data": state["data"],
            "channel": "whatsapp_restaurant",
            "active": True,
            "origin_channel": origin,
            "recipient": PHONE,
            "destination": PHONE,
            "detail_level": "full",
        }

    monkeypatch.setattr(notifier, "_record", record)
    monkeypatch.setattr(notifier, "_claim", claim)
    monkeypatch.setattr(notifier, "_finish", AsyncMock())
    route = respx.route().mock(return_value=httpx.Response(200, json={"ok": True}))
    summary = delivery_summary(
        order_number=ORDER,
        rest_ref="ELAS",
        customer_id=PHONE,
        town="London",
        rest_confirmation_code=11,
        cust_confirmation_code=22,
        pickup_date="2026-01-15",
        dt="2026-01-15",
    )
    address = dict(
        house_number="1",
        building_name=None,
        street_name="High Street",
        city="London",
        postcode="BR6 6DN",
        lat=51.5,
        lon=-0.1,
    )
    if hook == "payment":
        await payment_hooks.handle_payment_complete(
            payment_hooks.FoodOrder(
                order_id="ABCD-1",
                order_number=ORDER,
                recipient=PHONE,
                thread_id="ELAS-thread",
                action="delivery",
                total_price=20,
                payment_status="requires_capture",
                origin_channel=origin,
            )
        )
    elif hook == "capture_address":
        monkeypatch.setattr(order_hooks.CustRestMap, "upsert", lambda **kw: None)
        await order_hooks.capture_address(
            order_hooks.CaptureAddressRequest(
                recipient=PHONE,
                rest_ref="ELAS",
                latitude=51.5,
                longitude=-0.1,
                **{k: v for k, v in address.items() if k not in ("lat", "lon")},
            )
        )
    elif hook == "update_address":
        patch_supabase_client.register(
            table="customer_master",
            verb="update",
            response=FakeSupabaseResponse(data=[{"cust_id": PHONE}]),
        )
        await customer_hooks.update_address(
            customer_hooks.UpdateAddressRequest(
                cust_id=PHONE, rest_ref="ELAS", **address
            )
        )
    elif hook == "pickup_time":
        await takeaway_hooks._post_pickup_time_event(
            takeaway_hooks.TakeawaySummaryData(
                **_takeaway_summary_row(
                    pickup_time="2026-05-09T12:30:00+00:00", customer_id=PHONE
                )
            ),
            takeaway_hooks.RestaurantMasterData(**_restaurant_master_row()),
        )
    elif hook == "nearby":
        patch_supabase_client.register(
            table="delivery_summary",
            verb="select",
            response=FakeSupabaseResponse(data=[summary.model_dump(mode="json")]),
        )
        req = SimpleNamespace(
            json=AsyncMock(
                return_value={
                    "event": "enter",
                    "rid": "cust",
                    "order_number": ORDER,
                    "customer_id": PHONE,
                }
            )
        )
        await location_hooks.notify_rider_location_event(
            req, SimpleNamespace(add_task=lambda *a, **kw: None)
        )
    elif hook == "inflight":
        await delivery_hooks.post_rider_event_inflight(summary)
    elif hook == "timedout":
        await delivery_hooks.post_delivery_timedout(
            summary.model_dump(mode="json"), payment_cancelled=True
        )
    elif hook == "customer_cc":
        await agent_app_handlers.post_rider_event_customer_cc(ORDER, PHONE)
    elif hook == "restaurant_cc":
        await agent_app_handlers.post_rider_event_restaurant_cc(ORDER, PHONE)
    else:

        class Clock:
            @staticmethod
            def now(tz):
                return datetime(2026, 10, 2, 12, tzinfo=timezone.utc)

        from utils_common.order_management import restaurant_actions

        monkeypatch.setattr(restaurant_actions, "datetime", Clock)   # the event time is now stamped by restaurant_actions
        actions_db.add(ORDER, "takeaway", rider=None, recipient=PHONE)   # Ready is decided in SQL (restaurant_actions)
        cb = SimpleNamespace(sender="admin-1", reply=AsyncMock())
        data = SimpleNamespace(order_number=ORDER, recipient=PHONE, rest_ref="ELAS")
        cb.data = json.dumps(vars(data) | {"action": "/AdminTakeawayReady"})
        await on_callback_wa_handler.admin_takeaway_ready(None, cb)
    if hook not in ("capture_address", "update_address"):
        # Order events are recorded by the notifier (no flag, any restaurant).
        assert "data" in state
    if origin == "web":
        assert route.call_count == 0
        return
    assert route.call_count == 1
    request = route.calls[0].request
    actual = {"url": str(request.url), "body": json.loads(request.content)}
    expected = json.loads(SNAPSHOTS.read_text())[hook]
    assert actual == {k: v for k, v in expected.items() if k != "body_json"}
    assert request.content.decode("utf-8") == expected["body_json"]
