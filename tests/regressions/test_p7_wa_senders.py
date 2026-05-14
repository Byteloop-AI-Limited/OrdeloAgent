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


async def test_admin_delivery_driver_nearby(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    monkeypatch.setattr(wa_senders, "REST_MASTER", type("R", (), {"get_admins": lambda self: ["A1"]})())
    await wa_senders.admin_delivery_driver_nearby("ELAS-ABCD-1", "11")
    s = patch_async_wa_client.sent[-1]
    assert "Delivery driver is nearby" in s.kwargs["text"]


async def test_admin_delivery_complete_notification(patch_async_wa_client: FakeAsyncWhatsApp, monkeypatch):
    monkeypatch.setattr(wa_senders, "REST_MASTER", type("R", (), {"get_admins": lambda self: ["A1"]})())
    await wa_senders.admin_delivery_complete_notification("ELAS-ABCD-1")
    s = patch_async_wa_client.sent[-1]
    assert "Delivery completed" in s.kwargs["text"]
