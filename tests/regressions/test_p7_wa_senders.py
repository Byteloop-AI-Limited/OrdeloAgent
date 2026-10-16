"""P7 wa_senders uncovered path coverage."""
from __future__ import annotations
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


async def test_admin_auto_accept_notice_sends_the_unchanged_text_to_each_admin(patch_async_wa_client: FakeAsyncWhatsApp):
    await wa_senders.admin_auto_accept_notice(["A1", "A2"], "ELAS-ABCD-1", "11:30 AM", 30)
    assert [(s.kwargs["to"], s.kwargs["text"]) for s in patch_async_wa_client.sent] == [
        ("A1", "Order ELAS-ABCD-1 auto-accepted due to confirmation timeout. Pickup time set to 11:30 AM (30 mins from order time)."),
        ("A2", "Order ELAS-ABCD-1 auto-accepted due to confirmation timeout. Pickup time set to 11:30 AM (30 mins from order time)."),
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
