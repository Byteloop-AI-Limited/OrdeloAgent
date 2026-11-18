"""P7 wa_senders uncovered path coverage."""
from __future__ import annotations
from types import SimpleNamespace

import pytest

from tests.fixtures.fake_wa import FakeAsyncWhatsApp
from utils_common.waba_utils import wa_senders


async def test_send_postcode_search_flow(patch_async_wa_client: FakeAsyncWhatsApp):
    await wa_senders.send_postcode_search_flow("4474", customer_name="Bas", postcode_init="BR6")
    s = patch_async_wa_client.sent[-1]
    assert s.kwargs["to"] == "4474"
    assert s.kwargs["buttons"].flow_name == "PostcodeSearchElai"


async def test_send_reservation_link(fake_async_wa: FakeAsyncWhatsApp):
    await wa_senders.send_reservation_link("4474", "Bas", "RES-1", _async_wa_client=fake_async_wa)
    s = fake_async_wa.sent[-1]
    assert s.method == "send_template"
    assert s.kwargs["name"] == "send_reservation_link"


async def test_send_delayed_text(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    import asyncio
    orig = asyncio.sleep
    async def _s(d): return None
    monkeypatch.setattr(asyncio, "sleep", _s)
    await wa_senders.send_delayed_text("4474", "hello", wait_time=0)
    s = patch_async_wa_client.sent[-1]
    assert s.kwargs["to"] == "4474"


async def test_send_product_sections(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    monkeypatch.setattr(
        wa_senders, "waba_cat_settings", type("C", (), {"cat_id": "cat1"})(), raising=False
    )
    await wa_senders.send_product_sections("4474", "burger", [], _async_wa_client=patch_async_wa_client)
    s = patch_async_wa_client.sent[-1]
    assert s.method == "send_products"


async def test_enquire_shift_availability_non_template(patch_async_wa_client: FakeAsyncWhatsApp):
    from tests.fixtures.fake_wa import FakeMessage
    msg = FakeMessage(sender="4474", text="hello")
    await wa_senders.enquire_shift_availability_non_template(patch_async_wa_client, msg)
    s = patch_async_wa_client.sent[-1]
    assert s.kwargs["header"] == "🌟 Shift Availability 🌟"


async def test_admin_auto_accept_notice_sends_delivery_hold_to_each_admin(patch_async_wa_client: FakeAsyncWhatsApp):
    await wa_senders.admin_auto_accept_notice(["A1", "A2"], "ELAS-ABCD-1", "11:30 AM", 30)
    assert [(s.kwargs["to"], s.kwargs["text"]) for s in patch_async_wa_client.sent] == [
        ("A1", "Order ELAS-ABCD-1 auto-accepted due to confirmation timeout. Pickup time set to 11:30 AM (30 mins from order time).\n*⏳ Don't start cooking yet — we're finding a rider.*\nStart when the kitchen receipt arrives."),
        ("A2", "Order ELAS-ABCD-1 auto-accepted due to confirmation timeout. Pickup time set to 11:30 AM (30 mins from order time).\n*⏳ Don't start cooking yet — we're finding a rider.*\nStart when the kitchen receipt arrives."),
    ]


async def test_admin_auto_accept_notice_one_bad_contact_does_not_cost_the_others(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    sent = []

    async def send(**kw):
        if kw["to"] == "BAD":
            raise RuntimeError("no such number")
        sent.append(kw["to"])

    monkeypatch.setattr(patch_async_wa_client, "send_message", send)
    await wa_senders.admin_auto_accept_notice(["BAD", "A2"], "ELAS-ABCD-1", "11:30 AM", 30)
    assert sent == ["A2"]


async def test_takeaway_auto_accept_never_holds(patch_async_wa_client):
    await wa_senders.admin_auto_accept_notice(["A1"], "ELAS-TK-1", "11:30 AM", 30, order_type="takeaway")
    assert patch_async_wa_client.sent[-1].kwargs["text"] == (
        "Order ELAS-TK-1 auto-accepted due to confirmation timeout. Pickup time set to 11:30 AM (30 mins from order time).")


async def test_no_rider_notice_is_a_reply_and_survives_a_bad_contact(patch_async_wa_client, monkeypatch):
    sent = []

    async def send(**kw):
        if kw["to"] == "BAD":
            raise RuntimeError("no such number")
        sent.append(kw)

    monkeypatch.setattr(patch_async_wa_client, "send_message", send)
    await wa_senders.admin_no_rider_notice(["BAD", "A2"], "ELAS-ABCD-1", restaurant_msg_id="wamid.card")
    assert sent == [{"to": "A2", "text": "*❌ No rider found for ELAS-ABCD-1.*\n"
                    "The order is cancelled — please don't prepare it.", "reply_to_message_id": "wamid.card"}]


@pytest.mark.parametrize("order_type", ["delivery", "takeaway"])
async def test_kitchen_receipt_starts_with_instruction_then_order_number(order_type, patch_async_wa_client, monkeypatch):
    from utils_common.order_management.food_order_pymodel import FoodOrder
    from utils_common.order_management import food_order_reciept

    food = FoodOrder.model_construct(order_id="ABCD-1", order_number="ELAS-ABCD-1", recipient="4474",
                                     total_price=60, small_order_fee=0, notes=None)
    monkeypatch.setattr(wa_senders.FoodOrder, "from_order_id", lambda _: food)
    # Eight items exercise a substantial receipt using the real food receipt formatter.
    monkeypatch.setattr(food_order_reciept, "_fetch_order_items", lambda _: [
        {"quantity": 1, "product_name": f"Chicken Shawarma {i}", "price": 7.5, "modifications": []} for i in range(8)])
    monkeypatch.setattr(wa_senders.RestaurantMaster, "from_rest_ref", lambda _: SimpleNamespace(
        rest_name="Elai", get_admins=lambda: ["A1"]))

    async def base_url(**kw):
        return "https://rider.example.com"

    monkeypatch.setattr(wa_senders, "get_restaurant_base_url_async", base_url)
    pickup = "2026-11-17T23:14:00Z"
    if order_type == "delivery":
        await wa_senders.admin_order_reciept(SimpleNamespace(
            order_number=food.order_number, rest_ref="ELAS", pickup_time=pickup, rest_confirmation_code=47,
            customer_address="1 Test Street", customer_id="4474", restaurant_msg_id="wamid.card"),
            {"rider_name": "Sam", "rider_id": "RIDER01"})
        detail = "Rider found · ready for pickup at 11:14 PM"
    else:
        await wa_senders.takeaway_admin_order_receipt(food.order_number, pickup, "Elai", ["A1"], "wamid.card", "ELAS")
        detail = "Ready for collection at 11:14 PM"
    sent = patch_async_wa_client.sent[-1].kwargs
    assert sent["header"] == "🍳 Please start preparing now" and len(sent["header"]) <= 60
    assert sent["text"].startswith(f"*{detail}*\nOrder #ELAS-ABCD-1 (Kitchen)\n")
    assert sent["reply_to_message_id"] == "wamid.card"
    assert len(sent["text"]) <= 1024, len(sent["text"])
    assert sent["text"].count("Chicken Shawarma") == 8


async def test_admin_delivery_completed_messages_the_restaurants_admins(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    monkeypatch.setattr(wa_senders.RestaurantMaster, "get_admins_for", classmethod(lambda cls, rest_ref: ["A1", "A2"] if rest_ref == "ELAS" else []))
    await wa_senders.admin_delivery_completed("ELAS-ABCD-1", "ELAS")
    assert [(s.kwargs["to"], s.kwargs["text"]) for s in patch_async_wa_client.sent] == [
        ("A1", "✅ Delivery completed for ELAS-ABCD-1."),
        ("A2", "✅ Delivery completed for ELAS-ABCD-1."),
    ]


def test_rider_alert_text_wording_for_each_case():
    assert wa_senders.rider_alert_text("awaiting_pickup", "ELAS-1", 7, "1:00 PM", "Ada") == (
        "⏰ Order *ELAS-1*: rider Ada has not yet collected — 7 min past the 1:00 PM pickup time.")
    assert wa_senders.rider_alert_text("awaiting_pickup", "ELAS-1", -10, "1:00 PM", "Ada") == (
        "🛵 Order *ELAS-1*: rider Ada is due to collect at 1:00 PM (in ~10 min). Please have it ready.")
    assert wa_senders.rider_alert_text("picked_up", "ELAS-1", 30, "1:00 PM", "Ada") == (
        "🛵 Order *ELAS-1*: rider Ada collected but has not delivered — 30 min past the 1:00 PM pickup time.")
