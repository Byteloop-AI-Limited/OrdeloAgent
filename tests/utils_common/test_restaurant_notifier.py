"""restaurant_notifier: one call reaches WhatsApp (the unchanged wa_senders call) and Telegram (Receipts.send), each alone."""

from __future__ import annotations

import pytest

from channels.telegram.rest_admin.order_cards.model import OrderRef
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from utils_common.notify import restaurant_notifier
from datetime import datetime, timezone

from utils_common.notify.restaurant_notifier import (
    AutoAccepted, DeliveryCompleted, Feedback, KitchenReceipt, RiderAlert, TakeawayReceipt, notify, use_adapters,
)
from utils_common.waba_utils import wa_senders

DELIVERY_ROW = {
    "order_number": "ELAS-ABCD-1", "rest_id": "REST001", "rest_name": "Elai", "rest_address": "1 Test Street", "town": "London",
    "customer_id": "447400000000", "customer_name": "Test Customer", "status": "rider_assigned",
    "restaurant_confirmation_status": "restaurant_accept", "rest_confirmation_code": 11,
    "pickup_time": "2026-05-09T12:30:00+00:00", "rest_ref": "ELAS",
    "rest_lon": -0.1, "rest_lat": 51.5, "customer_lon": -0.2, "customer_lat": 51.4, "customer_address": "2 Test Road",
    "cust_confirmation_code": 22, "pickup_date": "2026-05-09", "dt": "2026-05-09", "dtts": "2026-05-09T10:00:00+00:00",
}


def kitchen():
    return KitchenReceipt(DeliverySummary(**DELIVERY_ROW), {"rider_id": "RIDER01", "rider_name": "Bas"}, 10)


def takeaway():
    return TakeawayReceipt("ELAS-TK-1", "2026-05-09T12:30:00+00:00", "Elai", ["ADMIN01", "ADMIN02"], "wamid.1", "ELAS")


class Recorder:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    async def send(self, notice):
        self.sent.append(notice)
        if self.fail:
            raise self.fail


async def test_both_channels_get_the_notice():
    wa, tg = Recorder(), Recorder()
    with use_adapters(whatsapp=wa, telegram=tg):
        await notify(kitchen())
    assert wa.sent == [kitchen()] and tg.sent == [kitchen()]


@pytest.mark.parametrize("broken", ["telegram", "whatsapp"])
async def test_one_channel_failing_does_not_stop_the_other_or_raise(broken):
    wa = Recorder(RuntimeError("boom") if broken == "whatsapp" else None)
    tg = Recorder(RuntimeError("boom") if broken == "telegram" else None)
    with use_adapters(whatsapp=wa, telegram=tg):
        await notify(takeaway())            # must not raise
    assert len(wa.sent) == 1 and len(tg.sent) == 1


async def test_whatsapp_adapter_makes_exactly_todays_kitchen_receipt_call(monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw)

    monkeypatch.setattr(wa_senders, "admin_order_reciept", fake)
    await restaurant_notifier._WhatsAppAdapter().send(kitchen())
    assert calls == [{"delivery_summary": DeliverySummary(**DELIVERY_ROW), "rider_master": {"rider_id": "RIDER01", "rider_name": "Bas"}}]


async def test_whatsapp_adapter_makes_exactly_todays_takeaway_receipt_call(monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw)

    monkeypatch.setattr(wa_senders, "takeaway_admin_order_receipt", fake)
    await restaurant_notifier._WhatsAppAdapter().send(takeaway())
    assert calls == [{"order_number": "ELAS-TK-1", "pickup_time": "2026-05-09T12:30:00+00:00", "rest_name": "Elai",
                      "admins": ["ADMIN01", "ADMIN02"], "restaurant_msg_id": "wamid.1", "rest_ref": "ELAS"}]


async def test_telegram_adapter_maps_notices_to_receipts_send():
    class Spy:
        def __init__(self):
            self.calls = []

        async def send(self, order, dispatch_id=None):
            self.calls.append((order, dispatch_id))

    adapter, spy = restaurant_notifier._TelegramAdapter(), Spy()
    adapter._receipts = spy
    await adapter.send(kitchen())
    await adapter.send(takeaway())
    assert spy.calls == [(OrderRef("ELAS-ABCD-1", "delivery"), 10), (OrderRef("ELAS-TK-1", "takeaway"), None)]


async def test_unknown_notice_is_logged_not_raised():
    with use_adapters(whatsapp=restaurant_notifier._WhatsAppAdapter(), telegram=Recorder()):
        await notify(object())  # type: ignore[arg-type]


def test_use_adapters_restores_the_real_ones():
    before = (restaurant_notifier._whatsapp, restaurant_notifier._telegram)
    with use_adapters(whatsapp=Recorder(), telegram=Recorder()):
        assert restaurant_notifier._whatsapp is not before[0]
    assert (restaurant_notifier._whatsapp, restaurant_notifier._telegram) == before


# ---- Step 8a: plain notices ----------------------------------------------------------------------------------------

AUTO = AutoAccepted("ELAS-ABCD-1", "delivery", ["A1", "A2"], "11:30 AM", 30, "ELAS")
ALERT = RiderAlert("awaiting_pickup", "ELAS-ABCD-1", "2026-05-09T12:30:00+00:00", "RIDER01", "Ada", "ELAS", ["A1"])
DONE = DeliveryCompleted("ELAS-ABCD-1", "ELAS")
FEEDBACK = Feedback(["A1", "A2"], "FDB-1", "Elai", "ELAS", "4474", "Bas", None, "Great <b>food</b> & service",
                    datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize("notice", [AUTO, ALERT, DONE, FEEDBACK])
async def test_plain_notices_reach_both_channels(notice):
    wa, tg = Recorder(), Recorder()
    with use_adapters(whatsapp=wa, telegram=tg):
        await notify(notice)
    assert wa.sent == [notice] and tg.sent == [notice]


async def test_whatsapp_adapter_auto_accepted_is_todays_text(monkeypatch):
    calls = []

    async def fake(*a):
        calls.append(a)

    monkeypatch.setattr(wa_senders, "admin_auto_accept_notice", fake)
    await restaurant_notifier._WhatsAppAdapter().send(AUTO)
    assert calls == [(["A1", "A2"], "ELAS-ABCD-1", "11:30 AM", 30)]


async def test_whatsapp_adapter_rider_alert_makes_exactly_todays_call(monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw)

    monkeypatch.setattr(wa_senders, "notify_rest_admins_rider_alert", fake)
    await restaurant_notifier._WhatsAppAdapter().send(ALERT)
    assert calls == [{"phase": "awaiting_pickup", "order_number": "ELAS-ABCD-1", "pickup_time": "2026-05-09T12:30:00+00:00",
                      "rider_id": "RIDER01", "rider_name": "Ada", "rest_ref": "ELAS", "rest_admins": ["A1"]}]


async def test_whatsapp_adapter_delivery_completed_and_feedback(monkeypatch):
    done, fb = [], []

    async def fake_done(*a):
        done.append(a)

    async def fake_fb(**kw):
        fb.append(kw)
        if kw["admin"] == "A1":
            raise RuntimeError("bad contact")

    monkeypatch.setattr(wa_senders, "admin_delivery_completed", fake_done)
    monkeypatch.setattr(wa_senders, "send_restaurant_feedback_notification", fake_fb)
    adapter = restaurant_notifier._WhatsAppAdapter()
    await adapter.send(DONE)
    await adapter.send(FEEDBACK)        # A1 fails, A2 still gets it, nothing raised
    assert done == [("ELAS-ABCD-1", "ELAS")]
    assert [k["admin"] for k in fb] == ["A1", "A2"]
    assert fb[1] == {"admin": "A2", "feedback_id": "FDB-1", "restaurant_name": "Elai", "cust_id": "4474", "cust_name": "Bas",
                     "order_reference": None, "description": "Great <b>food</b> & service", "received_at": FEEDBACK.received_at}


class SpyNotices:
    def __init__(self):
        self.calls = []

    async def send(self, rest_ref, text, **kw):
        self.calls.append((rest_ref, text, kw))


async def test_telegram_adapter_maps_plain_notices():
    adapter, spy, receipts = restaurant_notifier._TelegramAdapter(), SpyNotices(), []

    class SpyReceipts:
        async def refresh(self, order):
            receipts.append(order)

    adapter._notices, adapter._receipts = spy, SpyReceipts()
    await adapter.send(AUTO)
    await adapter.send(DONE)
    await adapter.send(FEEDBACK)
    card, receipt = OrderRef("ELAS-ABCD-1", "delivery"), OrderRef("ELAS-ABCD-1", "delivery")
    assert spy.calls[0] == ("ELAS", "⏱ <b>ELAS-ABCD-1</b> auto-accepted (no answer in time). Pickup 11:30 AM (30 min after order).",
                            {"notice": "auto_accepted", "order": card, "reply_to": "card"})
    assert spy.calls[1] == ("ELAS", "✅ Delivered — <b>ELAS-ABCD-1</b>", {"notice": "delivered", "order": receipt, "reply_to": "receipt"})
    assert receipts == [receipt]            # the receipt copies are redrawn as done
    rest_ref, text, kw = spy.calls[2]
    assert (rest_ref, kw) == ("ELAS", {"notice": "feedback"})
    assert "Great &lt;b&gt;food&lt;/b&gt; &amp; service" in text and "Order reference: Not provided" in text
    assert text.splitlines()[0] == "💬 <b>Customer feedback</b> FDB-1"


async def test_telegram_takeaway_auto_accept_replies_to_the_takeaway_card():
    adapter, spy = restaurant_notifier._TelegramAdapter(), SpyNotices()
    adapter._notices = spy
    await adapter.send(AutoAccepted("ELAS-TK-1", "takeaway", ["A1"], "1:00 PM", 20, "ELAS"))
    assert spy.calls[0][2]["order"] == OrderRef("ELAS-TK-1", "takeaway")


def test_rider_alert_html_is_the_whatsapp_wording_with_html_bold():
    now = datetime(2026, 5, 9, 12, 37, tzinfo=timezone.utc)      # 7 minutes after the 12:30 UTC (1:30 PM BST) pickup
    html = restaurant_notifier.rider_alert_html(ALERT, now)
    assert html == "⏰ Order <b>ELAS-ABCD-1</b>: rider Ada has not yet collected — 7 min past the 1:30 PM pickup time."
    early = restaurant_notifier.rider_alert_html(ALERT, datetime(2026, 5, 9, 12, 20, tzinfo=timezone.utc))
    assert early == "🛵 Order <b>ELAS-ABCD-1</b>: rider Ada is due to collect at 1:30 PM (in ~10 min). Please have it ready."


async def test_rider_alert_without_rest_ref_is_logged_not_raised():
    adapter = restaurant_notifier._TelegramAdapter()
    adapter._notices = SpyNotices()
    with use_adapters(whatsapp=Recorder(), telegram=adapter):
        await notify(RiderAlert("awaiting_pickup", "ELAS-1", "2026-05-09T12:30:00+00:00", "R1", None, None, []))
    assert adapter._notices.calls == []
