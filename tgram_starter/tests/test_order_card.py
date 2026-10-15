"""Order card: rendering per status, transitions, and the edit loop against a fake bot (no network)."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import EditMessageText

from tgram_starter.order_card import service
from tgram_starter.order_card.render import CardAction, render_buttons, render_text
from tgram_starter.order_card.state import ORDERS, apply_action, apply_event, demo_order


@pytest.fixture(autouse=True)
def clean():
    ORDERS.clear()
    service.CARD_MESSAGES.clear()


def labels(markup):
    return [[b.text for b in row] for row in markup.inline_keyboard] if markup else None


def test_buttons_per_status():
    s = demo_order()
    assert labels(render_buttons(s)) == [["✅ Accept", "❌ Decline"]]
    s = apply_action(s, "acc", "Ann")
    assert labels(render_buttons(s)) == [["🔔 Ready - Notify Rider"], ["+10 min", "+20 min"], ["❌ Cancel order"]]
    s = apply_event(apply_action(s, "rdy", "Ann"), "picked_up", live_url="https://example.com/live")
    assert labels(render_buttons(s)) == [["⚠️ Report a problem", "📍 Track rider"]]
    assert render_buttons(apply_event(s, "delivered")) is None


def test_text_follows_state():
    s = demo_order()
    text = render_text(s)
    assert "🆕 <b>New order</b>" in text and "finding a rider" in text and "Live location" not in text
    assert "<blockquote expandable><b>Items (6)</b>" in text and "£36.06" in text
    s = apply_event(apply_action(s, "acc", "Ann"), "rider_assigned", rider_name="Raj", rider_phone="+447700900123")
    text = render_text(s)
    assert "👨‍🍳 <b>Preparing</b>" in text and "<b>Raj</b> +447700900123" in text
    s = apply_event(apply_action(s, "rdy", "Ann"), "picked_up", live_url="https://example.com/live")
    assert '<a href="https://example.com/live">Live location</a>' in render_text(s)
    assert "<s>• 1 × Vegetable Biryani" in render_text(apply_event(demo_order(), "cancelled"))


def test_db_values_are_html_escaped():
    s = replace(demo_order(), customer_address="Flat 2 <rear> & Co", items=())
    text = render_text(s)
    assert "Flat 2 &lt;rear&gt; &amp; Co" in text and "<rear>" not in text


def test_stale_and_invalid_transitions():
    s = demo_order()
    assert apply_action(s, "rdy", "Ann") is None  # can't be ready before accepting
    accepted = apply_action(s, "acc", "Ann")
    assert apply_action(accepted, "acc", "Bob") is None  # second admin taps an old Accept
    assert apply_action(accepted, "d10", "Ann").pickup_time - accepted.pickup_time == timedelta(minutes=10)
    assert apply_event(s, "delivered") is None
    assert apply_event(apply_event(s, "cancelled"), "cancelled") is None


def test_callback_data_fits_64_bytes():
    for act in ("acc", "dec", "rdy", "d10", "d20", "can", "iss"):
        assert len(CardAction(ref="ELAS-EJAR-21", act=act).pack().encode()) <= 64


class FakeBot:
    """Records calls; edit_message_text raises the queued errors per chat first."""
    def __init__(self, errors=None):
        self.edits, self.sends, self.errors, self.next_id = [], [], errors or {}, 100

    async def send_message(self, chat_id, text, **kw):
        self.next_id += 1
        self.sends.append((chat_id, text, kw))
        return SimpleNamespace(message_id=self.next_id)

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        queue = self.errors.get(chat_id) or []
        if queue:
            raise queue.pop(0)
        self.edits.append((chat_id, message_id, text))


def _bad(msg):
    return TelegramBadRequest(method=EditMessageText(text="x"), message=f"Bad Request: {msg}")


def test_refresh_edits_every_copy_and_handles_errors(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(service.asyncio, "sleep", no_sleep)

    async def run():
        ORDERS["DEMO-ORDR-21"] = demo_order()
        bot = FakeBot()
        await service.send_order_card(bot, "DEMO-ORDR-21", [1, 2, 3, 4])
        ORDERS["DEMO-ORDR-21"] = apply_action(ORDERS["DEMO-ORDR-21"], "acc", "Ann")
        bot.errors = {
            1: [_bad("message is not modified: specified new message content ...")],  # kept, no-op
            2: [_bad("message to edit not found")],                                  # forgotten
            3: [TelegramForbiddenError(method=EditMessageText(text="x"), message="Forbidden: bot was blocked")],
            4: [TelegramRetryAfter(method=EditMessageText(text="x"), message="Flood", retry_after=3)],  # retried
        }
        await service.refresh_order_card(bot, "DEMO-ORDR-21", notify="ping")
        return bot

    bot = asyncio.run(run())
    assert [c.chat_id for c in service.CARD_MESSAGES["DEMO-ORDR-21"]] == [1, 4]
    assert [e[0] for e in bot.edits] == [4] and "Accepted by Ann" in bot.edits[0][2]
    assert [(chat, text) for chat, text, _ in bot.sends[4:]] == [(1, "ping"), (4, "ping")]  # notify replies


def test_demo_hook_endpoints_drive_the_card():
    from fastapi.testclient import TestClient

    from tgram_starter.app import app
    with TestClient(app) as c:
        real_bot, app.state.bot = app.state.bot, FakeBot()
        bot = app.state.bot
        try:
            key = {"X-Admin-Key": "adm"}
            assert c.post("/demo/order-card?chat_id=7", headers=key).json()["cards"] == [{"chat_id": 7, "message_id": 101}]
            assert c.post("/demo/order-card/DEMO-ORDR-21/event?event=delivered", headers=key).status_code == 409
            r = c.post("/demo/order-card/DEMO-ORDR-21/event?event=rider_assigned&rider_name=Raj", headers=key)
            assert r.status_code == 200 and r.json()["status"] == "new"
            assert "<b>Raj</b>" in bot.edits[-1][2]  # background refresh ran
            assert bot.sends[-1][1] == "🛵 Rider assigned: Raj" and bot.sends[-1][2]["reply_to_message_id"] == 101
            assert c.post("/demo/order-card/DEMO-ORDR-21/event?event=picked_up").status_code == 401
        finally:
            app.state.bot = real_bot  # lifespan shutdown closes the real bot's session
