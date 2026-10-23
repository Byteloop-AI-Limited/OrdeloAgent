"""ordelo/pause_notices.py: the "ends soon" / "back on" messages job_pause_sweep() asks for (ADR 0013), phase R5-R6.

Riders: through their channel's RiderMessenger (faked with use_messenger); the /off hint only on Telegram. Restaurant
admins: on the restaurant bot, only in that admin's chats for that restaurant (t_admin_pause_chats, faked). Never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ordelo import pause_notices
from ordelo.pauses import ends_text
from ordelo.rider_messaging import use_messenger
from ordelo.rider_messaging.fake import RecordingRiderMessenger
from tests.channels.telegram.conftest import RecordingSession

ENDS = datetime(2026, 10, 23, 17, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("channel, hint", [("telegram", True), ("whatsapp", False)])
async def test_rider_ending_soon_on_their_channel(channel, hint):
    fake = RecordingRiderMessenger(channel=channel)
    with use_messenger(fake):
        assert await pause_notices.tell_rider("447700900531", pause_notices.ENDING_SOON, ENDS) is True
    (text,) = fake.texts
    assert text.startswith(f"⏰ Your break ends at *{ends_text(ENDS)}*.") and ("/off" in text) is hint


async def test_rider_back_on():
    fake = RecordingRiderMessenger(channel="telegram")
    with use_messenger(fake):
        await pause_notices.tell_rider("447700900531", pause_notices.ENDED, ENDS)
    assert fake.texts == ["✅ Your break is over. You're back on and will get job offers again."]


async def test_rider_send_failure_is_logged_not_raised():
    class Broken(RecordingRiderMessenger):
        async def say(self, *a, **k):
            raise RuntimeError("telegram down")

    with use_messenger(Broken()):
        assert await pause_notices.tell_rider("447700900531", pause_notices.ENDED, ENDS) is False


async def test_admin_messages_go_to_that_admins_chats_for_that_restaurant(monkeypatch):
    from aiogram import Bot

    session = RecordingSession()
    bot = Bot(token="123456:TEST-token", session=session)
    seen = []

    async def chats(bot_key, phone, rest_ref):
        seen.append((bot_key, phone, rest_ref))
        return [(111, "Elas <Kitchen>"), (112, "Elas <Kitchen>")]

    monkeypatch.setattr("channels.telegram.admin_pauses.chats", chats)
    sent = await pause_notices.tell_admin(bot, "rest_admin", "447700900811", "ELAS", pause_notices.ENDING_SOON, ENDS)
    assert sent == 2 and seen == [("rest_admin", "447700900811", "ELAS")]
    assert [c.chat_id for c in session.sends] == [111, 112]
    assert session.sent_texts[0] == (f"⏰ Order alerts for <b>Elas &lt;Kitchen&gt;</b> start again at {ends_text(ENDS)}.\n"
                                     "Send /off to pause for longer, or /on to turn them on now.")
    await pause_notices.tell_admin(bot, "rest_admin", "447700900811", "ELAS", pause_notices.ENDED, ENDS)
    assert session.sent_texts[-1] == "🔔 Order alerts for <b>Elas &lt;Kitchen&gt;</b> are back on."


async def test_admin_without_a_bot_or_with_a_failing_lookup_gets_nothing(monkeypatch):
    assert await pause_notices.tell_admin(None, "rest_admin", "447700900811", "ELAS", pause_notices.ENDED, ENDS) == 0

    async def broken(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr("channels.telegram.admin_pauses.chats", broken)
    assert await pause_notices.tell_admin(object(), "rest_admin", "447700900811", "ELAS", pause_notices.ENDED, ENDS) == 0
