"""Notices (plain Telegram restaurant notices): destinations and reply targets come from the store (SQL in production),
each send is isolated and audited, and nothing ever raises. The SQL itself is proven in tests/sql/."""

from __future__ import annotations

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from channels.telegram.rest_admin.notices import NoticeStore, NoticeTarget, Notices
from channels.telegram.rest_admin.order_cards.model import OrderRef

ORDER = OrderRef("ELAS-CEKT-22", "delivery")
ADA = NoticeTarget(111, 111, "447700900001", reply_to=501)
BOB = NoticeTarget(222, 222, "447700900002", reply_to=None)


class FakeNoticeStore:
    def __init__(self, targets=(ADA, BOB)):
        self.found, self.asked, self.audit = list(targets), [], []
        self.fail_targets = self.fail_audit = False

    async def targets(self, rest_ref, order_number, reply_kind):
        self.asked.append((rest_ref, order_number, reply_kind))
        if self.fail_targets:
            raise RuntimeError("db down")
        return self.found

    async def notice_sent(self, target, message_id, rest_ref, order_number, notice):
        if self.fail_audit:
            raise RuntimeError("db down")
        self.audit.append((target.tcid, message_id, rest_ref, order_number, notice))


def sends(session):
    return [c for c in session.calls if isinstance(c, SendMessage)]


async def test_sends_to_every_destination_as_a_reply_and_records_each(recording_bot):
    bot, session = recording_bot
    store = FakeNoticeStore()
    n = await Notices(bot, "rest_admin", store=store).send("ELAS", "⏱ hi", notice="auto_accepted", order=ORDER, reply_to="card")
    assert n == 2
    assert store.asked == [("ELAS", "ELAS-CEKT-22", "card")]
    first, second = sends(session)
    assert (first.chat_id, first.text, first.parse_mode, first.reply_markup) == (111, "⏱ hi", "HTML", None)
    assert first.reply_parameters.message_id == 501 and first.reply_parameters.allow_sending_without_reply is True
    assert second.reply_parameters is None                      # nothing to reply to in Bob's chat
    assert sorted(a[0] for a in store.audit) == [111, 222]
    assert all(a[2:] == ("ELAS", "ELAS-CEKT-22", "auto_accepted") for a in store.audit)


async def test_a_notice_without_an_order_replies_to_nothing(recording_bot):
    bot, session = recording_bot
    store = FakeNoticeStore([BOB])
    await Notices(bot, "rest_admin", store=store).send("ELAS", "feedback", notice="feedback", reply_to="receipt")
    assert store.asked == [("ELAS", None, "none")]              # reply kind is ignored without an order
    assert store.audit[0][3] is None


async def test_a_blocked_chat_costs_nobody_else_their_message(recording_bot):
    bot, session = recording_bot
    session.fail = lambda m: TelegramForbiddenError(method=m, message="Forbidden: bot was blocked by the user") if m.chat_id == 111 else None
    store = FakeNoticeStore()
    n = await Notices(bot, "rest_admin", store=store).send("ELAS", "x", notice="delivered", order=ORDER, reply_to="receipt")
    assert n == 1
    assert [a[0] for a in store.audit] == [222]


async def test_store_trouble_never_raises(recording_bot):
    bot, session = recording_bot
    store = FakeNoticeStore()
    store.fail_targets = True
    assert await Notices(bot, "rest_admin", store=store).send("ELAS", "x", notice="feedback") == 0
    assert sends(session) == []
    store.fail_targets, store.fail_audit = False, True           # delivered but not audited: still counts as sent
    assert await Notices(bot, "rest_admin", store=store).send("ELAS", "x", notice="feedback") == 2


async def test_no_destinations_sends_nothing(recording_bot):
    bot, session = recording_bot
    assert await Notices(bot, "rest_admin", store=FakeNoticeStore([])).send("ELAS", "x", notice="feedback") == 0
    assert sends(session) == []


async def test_store_calls_the_documented_rpcs(monkeypatch):
    calls = []

    async def fake_rpc(name, args):
        calls.append((name, args))
        return [{"tcid": 111, "tuid": 111, "phone": "447700900001", "reply_to": 7}] if name == "t_notice_targets" else None

    monkeypatch.setattr("channels.telegram.rest_admin.notices._rpc", fake_rpc)
    store = NoticeStore("rest_admin")
    targets = await store.targets("ELAS", "ELAS-CEKT-22", "receipt")
    await store.notice_sent(targets[0], 900, "ELAS", "ELAS-CEKT-22", "delivered")
    assert targets == [NoticeTarget(111, 111, "447700900001", 7)]
    assert calls == [
        ("t_notice_targets", {"p_bot_key": "rest_admin", "p_rest_ref": "ELAS", "p_order_number": "ELAS-CEKT-22", "p_reply_kind": "receipt"}),
        ("t_notice_sent", {"p_bot_key": "rest_admin", "p_tcid": 111, "p_message_id": 900, "p_tuid": 111, "p_rest_ref": "ELAS",
                           "p_order_number": "ELAS-CEKT-22", "p_notice": "delivered"}),
    ]
