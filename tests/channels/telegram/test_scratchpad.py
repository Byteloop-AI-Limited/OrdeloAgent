"""Exercise the removable playground through real aiogram dispatchers, without network."""

import asyncio

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    AnswerCallbackQuery, DeleteMessage, EditMessageText, GetMe, SendContact,
    SendDice, SendDocument, SendLocation, SendMessage, SendMessageDraft,
    SendRichMessage, SendVenue,
)
from aiogram.types import ReplyKeyboardRemove, Update, User

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.rest_admin.router import build_router as build_rest_admin_router
from channels.telegram.rest_admin.scratchpad import DEMOS, Demo, build_scratchpad_router
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, message_update


async def feed(dp, bot, payload):
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def dispatcher():
    dp = Dispatcher()
    dp.include_router(build_scratchpad_router())
    return dp


async def tap(dp, bot, action, value=0, **kwargs):
    await feed(dp, bot, callback_update(Demo(action=action, value=value).pack(), **kwargs))


async def test_command_routes_before_restaurant_text_fallback(recording_bot, inbox_db):
    bot, session = recording_bot
    settings = TgramBotSettings.for_bot("rest_admin", {
        "tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc",
    })
    dp = build_rest_admin_dispatcher(settings)
    await feed(dp, bot, message_update("/eg"))
    assert "Telegram scratchpad" in session.sent_texts[-1]
    keyboard = session.last_keyboard.inline_keyboard
    assert {Demo.unpack(b.callback_data).action for row in keyboard for b in row} == {a for _, a in DEMOS}
    assert all(len(b.callback_data.encode()) <= 64 for row in keyboard for b in row)
    session.calls.clear()
    await feed(dp, bot, message_update("hello", update_id=2))
    assert session.sent_texts == ["I don't understand that yet. Try /help."]


@pytest.mark.parametrize("command", ["/eg", "/scratchpad"])
async def test_menu_opens_with_short_command_and_old_alias(recording_bot, command):
    bot, session = recording_bot
    await feed(dispatcher(), bot, message_update(command))
    assert "Telegram scratchpad" in session.sent_texts[-1] and "Send /eg anytime" in session.sent_texts[-1]
    assert len(keyboard_labels(session.last_keyboard)) == len(DEMOS)


async def test_unmount_leaves_command_and_callbacks_unhandled(recording_bot):
    bot, session = recording_bot
    dp = Dispatcher()
    dp.include_router(build_rest_admin_router())
    await feed(dp, bot, message_update("/scratchpad"))
    assert session.sent_texts == ["I don't understand that yet. Try /help."]
    session.calls.clear()
    await tap(dp, bot, "rich")
    assert session.calls == []


@pytest.mark.parametrize("action,method", [
    ("mini_app", SendMessage),
    ("text", SendMessage), ("reply", SendMessage), ("edit", SendMessage),
    ("delete", SendMessage), ("tracker", SendMessage), ("card", SendMessage),
    ("keyboard", SendMessage), ("rich", SendRichMessage),
    ("ask_location", SendMessage), ("ask_contact", SendMessage), ("remove", SendMessage),
    ("location", SendLocation), ("venue", SendVenue), ("contact", SendContact),
    ("dice", SendDice), ("file", SendDocument), ("effect", SendMessage), ("error", SendMessage),
    ("receipt", SendRichMessage), ("colours", SendRichMessage), ("progress", SendRichMessage),
    ("pickup_slots", SendRichMessage), ("pickup_eta", SendRichMessage), ("pickup_ready", SendRichMessage),
    ("seen_log", SendMessage), ("seen_badge", SendRichMessage), ("seen_nudge", SendMessage),
    ("seen_bump", SendMessage),
])
async def test_menu_actions_use_correct_api_and_private_destination(recording_bot, action, method):
    bot, session = recording_bot
    await tap(dispatcher(), bot, action)
    outgoing = [c for c in session.calls if not isinstance(c, AnswerCallbackQuery)]
    assert len(outgoing) == 1 and isinstance(outgoing[0], method)
    assert outgoing[0].chat_id == 111
    assert len(session.answers) == 1
    if action == "mini_app":
        button = outgoing[0].reply_markup.inline_keyboard[0][0]
        assert button.web_app.url == "https://restaurant.ordelo.app/town/salisbury"
        assert button.url is None and button.callback_data is None
    elif action == "reply":
        assert outgoing[0].reply_parameters.message_id == 10
    elif action == "rich":
        button = outgoing[0].rich_message.blocks[0].text[1].button
        assert button.text == "👨‍🍳 Preparing" and Demo.unpack(button.callback_data).value == 1
    elif action == "file":
        assert outgoing[0].document.data == b"id,name\n1,demo\n"
    elif action == "error":
        assert "simulated" in outgoing[0].text


async def test_info_and_draft(recording_bot, monkeypatch):
    bot, session = recording_bot
    original = session.make_request

    async def request(b, method, timeout=None):
        if isinstance(method, GetMe):
            session.calls.append(method)
            return User(id=123456, is_bot=True, first_name="Demo", username="demo_bot")
        return await original(b, method, timeout)

    session.make_request = request
    await tap(dispatcher(), bot, "info")
    assert "@demo_bot" in session.sent_texts[-1]

    async def no_sleep(_):
        pass

    monkeypatch.setattr("channels.telegram.rest_admin.scratchpad.asyncio.sleep", no_sleep)
    session.calls.clear()
    await tap(dispatcher(), bot, "draft")
    drafts = [c for c in session.calls if isinstance(c, SendMessageDraft)]
    assert len(drafts) == 3 and len({c.draft_id for c in drafts}) == 1
    assert session.sent_texts == [drafts[-1].text]


@pytest.mark.parametrize("value,label", [(1, "✅ Ready"), (0, "👨‍🍳 Preparing")])
async def test_rich_button_changes_label_colour_and_callback_in_same_message(recording_bot, value, label):
    bot, session = recording_bot
    await tap(dispatcher(), bot, "rich_toggle", value)
    assert len(session.edits) == 1 and not session.sends
    edit = session.edits[0]
    assert (edit.chat_id, edit.message_id) == (111, 10)
    button = edit.rich_message.blocks[0].text[1].button
    assert button.text == label
    assert button.style == ("success" if value else "primary")
    assert Demo.unpack(button.callback_data).value == 1 - value
    assert len(session.answers) == 1


@pytest.mark.parametrize("action,values", [("tracker_step", range(5)), ("card_step", range(6)), ("card_time", (10, 20))])
async def test_progress_and_order_card_states_edit_only_demo_message(recording_bot, action, values):
    bot, session = recording_bot
    dp = dispatcher()
    for value in values:
        session.calls.clear()
        await tap(dp, bot, action, value)
        assert len(session.edits) == 1 and not session.sends
        assert "Demo" in session.edits[0].text
        assert session.edits[0].message_id == 10


@pytest.mark.parametrize("action,method", [("edit_now", EditMessageText), ("delete_now", DeleteMessage), ("ping", EditMessageText)])
async def test_message_controls(recording_bot, action, method):
    bot, session = recording_bot
    await tap(dispatcher(), bot, action)
    calls = [c for c in session.calls if not isinstance(c, AnswerCallbackQuery)]
    assert len(calls) == 1 and isinstance(calls[0], method) and calls[0].message_id == 10


@pytest.mark.parametrize("kind", ["group", "wrong_actor", "inaccessible"])
async def test_callback_rejects_non_private_or_wrong_actor(recording_bot, kind):
    bot, session = recording_bot
    payload = callback_update(Demo(action="rich_toggle", value=1).pack())
    if kind == "group":
        payload["callback_query"]["message"]["chat"] = {"id": -100, "type": "supergroup"}
    elif kind == "wrong_actor":
        payload["callback_query"]["message"]["chat"]["id"] = 222
    else:
        del payload["callback_query"]["message"]
        payload["callback_query"]["inline_message_id"] = "inline"
    await feed(dispatcher(), bot, payload)
    assert len(session.calls) == 1 and len(session.answers) == 1


async def test_group_command_does_not_open_demo_menu(recording_bot):
    bot, session = recording_bot
    payload = message_update("/scratchpad")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup"}
    await feed(dispatcher(), bot, payload)
    assert "private chat" in session.sent_texts[0] and session.last_keyboard is None


@pytest.mark.parametrize("kind", ["location", "contact"])
async def test_requested_input_is_scoped_to_scratchpad_state_and_cleared(recording_bot, kind):
    bot, session = recording_bot
    dp = dispatcher()
    payload = message_update("")
    del payload["message"]["text"]
    payload["message"][kind] = ({"latitude": 51.5, "longitude": -0.1} if kind == "location"
                                else {"phone_number": "+447700900123", "first_name": "Demo"})
    await feed(dp, bot, payload)
    assert not session.calls  # unsolicited data passes through
    await tap(dp, bot, f"ask_{kind}")
    session.calls.clear()
    await feed(dp, bot, payload)
    assert "received your location/contact" in session.sent_texts[0]
    assert isinstance(session.sends[0].reply_markup, ReplyKeyboardRemove)
    session.calls.clear()
    await feed(dp, bot, payload)
    assert not session.calls  # one request only


@pytest.mark.parametrize("error,expected_sends", [("message is not modified", 0), ("unsupported example", 1)])
async def test_duplicate_edits_and_unsupported_features(recording_bot, error, expected_sends):
    bot, session = recording_bot
    session.fail = lambda method: TelegramBadRequest(method=method, message=error) if isinstance(method, EditMessageText) else None
    await tap(dispatcher(), bot, "rich_toggle", 1)
    assert len(session.answers) == 1 and len(session.sends) == expected_sends


@pytest.mark.parametrize("action,value", [("tracker_step", 99), ("card_step", -1), ("rich_toggle", 2), ("missing", 0)])
async def test_stale_or_invalid_demo_action_gets_recovery_message(recording_bot, action, value):
    bot, session = recording_bot
    await tap(dispatcher(), bot, action, value)
    assert "Send /eg" in session.sent_texts[0] and len(session.answers) == 1


async def test_failed_callback_answer_does_not_prevent_demo(recording_bot):
    bot, session = recording_bot
    session.fail = lambda method: TelegramBadRequest(method=method, message="query too old") if isinstance(method, AnswerCallbackQuery) else None
    await asyncio.wait_for(tap(dispatcher(), bot, "rich_toggle", 1), timeout=2)
    assert len(session.edits) == 1


def rich_buttons(message):
    """Traverse the actual serialized rich-message tree, including embedded controls."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            if "text" in value and ("callback_data" in value or "disabled" in value):
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(message.model_dump(mode="json", exclude_none=True))
    return found


async def open_rich_demo(recording_bot, kind):
    bot, session = recording_bot
    dp = dispatcher()
    await tap(dp, bot, kind)
    sent = next(c for c in session.calls if isinstance(c, SendRichMessage))
    return dp, session.next_message_id, sent.rich_message


async def test_receipt_uses_native_collapsible_details_and_item_table(recording_bot):
    _, _, message = await open_rich_demo(recording_bot, "receipt")
    payload = message.model_dump(mode="json", exclude_none=True)
    details = [b for b in payload["blocks"] if b["type"] == "details"]
    assert len(details) == 2 and all(d["is_open"] is False for d in details)
    table = details[0]["blocks"][0]
    assert table["type"] == "table" and len(table["cells"]) == 7
    assert table["cells"][3][2]["text"] == "£6.40"  # quantity two; line total
    assert "£36.06" in payload["blocks"][1]["text"]


@pytest.mark.parametrize("decision", [1, 2])
async def test_coloured_decision_disables_actions_and_cannot_be_reversed(recording_bot, decision):
    bot, session = recording_bot
    dp, message_id, initial = await open_rich_demo(recording_bot, "colours")
    assert [b["style"] for b in rich_buttons(initial)] == ["success", "danger", "primary"]
    await tap(dp, bot, "rx_decide", decision, message_id=message_id)
    first = session.edits[-1].rich_message
    actions = rich_buttons(first)
    assert all(b["disabled"] == {} and "callback_data" not in b for b in actions[:2])
    await tap(dp, bot, "rx_decide", 3 - decision, message_id=message_id)
    assert session.edits[-1].rich_message == first


async def test_show_progress_expands_and_gates_the_four_requested_steps(recording_bot):
    bot, session = recording_bot
    dp, message_id, collapsed = await open_rich_demo(recording_bot, "progress")
    assert [b["text"] for b in rich_buttons(collapsed)] == ["Show progress"]
    await tap(dp, bot, "rx_expand", 1, message_id=message_id)
    steps = rich_buttons(session.edits[-1].rich_message)[1:5]
    assert [b["text"] for b in steps] == [
        "✅ Order Accepted", "✅ Rider Assigned", "🟠 Food pickup · next", "🔒 Delivery complete · pending",
    ]
    assert all(b["style"] == "success" and b["disabled"] == {} and "callback_data" not in b for b in steps[:2])
    assert steps[2]["style"] == "primary" and "callback_data" in steps[2]
    assert steps[3]["disabled"] == {} and "callback_data" not in steps[3]

    # A forged future-step callback cannot skip food pickup.
    edits = len(session.edits)
    await tap(dp, bot, "rx_next", 4, message_id=message_id)
    assert len(session.edits) == edits
    for completed in (3, 4):
        await tap(dp, bot, "rx_next", completed, message_id=message_id)
        steps = rich_buttons(session.edits[-1].rich_message)[1:5]
        assert all("disabled" in b and b["style"] == "success" for b in steps[:completed])
        if completed == 3:
            assert "callback_data" in steps[3]
    await tap(dp, bot, "rx_next", 3, message_id=message_id)  # stale food-pickup tap
    assert all("disabled" in b for b in rich_buttons(session.edits[-1].rich_message)[1:5])
    await tap(dp, bot, "rx_expand", 0, message_id=message_id)
    assert [b["text"] for b in rich_buttons(session.edits[-1].rich_message)] == ["Show progress"]
    await tap(dp, bot, "rx_expand", 1, message_id=message_id)
    assert all("disabled" in b for b in rich_buttons(session.edits[-1].rich_message)[1:5])


def pickup_time(message):
    payload = message.model_dump(mode="json", exclude_none=True)
    for block in payload["blocks"]:
        for part in block.get("text", []) if isinstance(block.get("text"), list) else []:
            if isinstance(part, dict) and part.get("type") == "date_time":
                return part["unix_time"]
    raise AssertionError("pickup timestamp missing")


@pytest.mark.parametrize("kind,action,value", [("pickup_slots", "rx_slot", 30), ("pickup_eta", "rx_delay", 10)])
async def test_embedded_pickup_time_updates_then_locks_until_edited(recording_bot, kind, action, value):
    bot, session = recording_bot
    dp, message_id, initial = await open_rich_demo(recording_bot, kind)
    await tap(dp, bot, action, value, message_id=message_id)
    changed = session.edits[-1].rich_message
    assert pickup_time(changed) - pickup_time(initial) == 10 * 60
    await tap(dp, bot, "rx_confirm", message_id=message_id)
    locked = session.edits[-1].rich_message
    controls = rich_buttons(locked)
    assert all("disabled" in b for b in controls[:-1])
    assert controls[-1]["text"] == "Edit time"
    await tap(dp, bot, action, value, message_id=message_id)
    assert session.edits[-1].rich_message == locked  # stale adjustment cannot alter a confirmed time
    await tap(dp, bot, "rx_edit", message_id=message_id)
    assert pickup_time(session.edits[-1].rich_message) == pickup_time(locked)
    assert all("callback_data" in b for b in rich_buttons(session.edits[-1].rich_message))


async def test_ready_hold_keeps_time_and_disables_completed_controls(recording_bot):
    bot, session = recording_bot
    dp, message_id, initial = await open_rich_demo(recording_bot, "pickup_ready")
    await tap(dp, bot, "rx_delay", 20, message_id=message_id)
    assert pickup_time(session.edits[-1].rich_message) - pickup_time(initial) == 20 * 60
    await tap(dp, bot, "rx_ready", message_id=message_id)
    ready = session.edits[-1].rich_message
    controls = rich_buttons(ready)
    assert controls[0]["text"] == "✅ Food ready" and controls[0]["style"] == "success"
    assert all("disabled" in b and "callback_data" not in b for b in controls[:-1])
    await tap(dp, bot, "rx_delay", 10, message_id=message_id)
    assert session.edits[-1].rich_message == ready


async def test_demo_state_is_per_message_and_cleared_by_menu(recording_bot):
    bot, session = recording_bot
    dp, first_id, _ = await open_rich_demo(recording_bot, "progress")
    await tap(dp, bot, "progress")
    second_id = session.next_message_id
    await tap(dp, bot, "rx_next", 3, message_id=first_id)
    await tap(dp, bot, "rx_expand", 1, message_id=second_id)
    assert "Food pickup · next" in rich_buttons(session.edits[-1].rich_message)[3]["text"]
    await feed(dp, bot, message_update("/scratchpad"))
    edits = len(session.edits)
    await tap(dp, bot, "rx_next", 4, message_id=first_id)
    assert len(session.edits) == edits and "expired" in session.sent_texts[-1]


@pytest.mark.parametrize("kind", ["receipt", "colours", "progress", "pickup_slots", "pickup_eta", "pickup_ready",
                                  "seen_badge"])
async def test_rich_demo_payload_has_one_button_action_and_legal_styles(recording_bot, kind):
    bot, _ = recording_bot
    _, _, message = await open_rich_demo(recording_bot, kind)
    payload = bot.session.prepare_value(SendRichMessage(chat_id=111, rich_message=message).model_dump(warnings=False),
                                        bot=bot, files={}, _dumps_json=False)
    assert payload["rich_message"]["blocks"]
    for button in rich_buttons(message):
        assert ("disabled" in button) != ("callback_data" in button)
        assert button.get("style") in (None, "success", "danger", "primary", "link")
        if "callback_data" in button:
            assert len(button["callback_data"].encode()) <= 64


# ---- "latest status since you last looked" examples -------------------------------------------

def keyboard_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


async def open_seen(recording_bot, kind):
    bot, session = recording_bot
    dp = dispatcher()
    await tap(dp, bot, kind)
    return dp, session.next_message_id


def preview(html_text):
    """What a lock-screen notification shows: the message's first line, without formatting."""
    import re

    return re.sub(r"<[^>]+>", "", html_text).splitlines()[0]


def assert_balanced_html(text):
    """Telegram rejects unbalanced tags; the recording session would not notice."""
    from html.parser import HTMLParser

    stack = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            stack.append(tag)

        def handle_endtag(self, tag):
            assert stack and stack.pop() == tag, f"unbalanced </{tag}> in {text!r}"

    Parser().feed(text)
    assert not stack, f"unclosed {stack} in {text!r}"


async def test_since_last_seen_marks_unseen_changes_and_clears_on_mark_seen(recording_bot):
    bot, session = recording_bot
    dp, card = await open_seen(recording_bot, "seen_log")
    opened = session.sends[-1]
    assert "You're up to date" in opened.text and "🆕" not in opened.text
    assert "👁 Mark seen" not in keyboard_labels(opened.reply_markup)

    for _ in range(3):
        await tap(dp, bot, "sn_next", message_id=card)
    away = session.edits[-1]
    assert away.message_id == card and len(session.sends) == 1  # same message, edited in place
    assert "3 updates since you last looked" in away.text
    assert "🆕 <b>⏰ Pickup time set by Ada</b>" in away.text  # the latest status leads
    assert "<i>🔔 New order — accept or decline</i>" in away.text  # already-seen history is quiet
    assert away.text.count("🆕") == 4  # banner, latest and the two unseen earlier lines
    assert "<blockquote expandable>" in away.text
    assert "👁 Mark seen" in keyboard_labels(away.reply_markup)
    assert_balanced_html(away.text)

    await tap(dp, bot, "sn_seen", message_id=card)
    caught_up = session.edits[-1]
    assert "You're up to date" in caught_up.text and "🆕" not in caught_up.text
    assert "👁 Mark seen" not in keyboard_labels(caught_up.reply_markup)
    assert "<i>🔔 Reminder 2 of 4 — nobody has answered</i>" in caught_up.text
    assert_balanced_html(caught_up.text)


async def test_status_badge_and_flow_show_what_is_new_before_any_tap(recording_bot):
    bot, session = recording_bot
    dp, card = await open_seen(recording_bot, "seen_badge")
    opened = next(c for c in session.calls if isinstance(c, SendRichMessage)).rich_message
    # Buttons in message order: badge, flow toggle, five flow stages, Next update.
    badge, toggle, *stages, _next = rich_buttons(opened)
    assert badge["text"] == "🆕 ✅ Accepted by Ada — waiting for pickup time" and badge["style"] == "success"
    assert Demo.unpack(badge["callback_data"]) == Demo(action="sn_seen", value=0)
    assert toggle["text"] == "Hide steps" and Demo.unpack(toggle["callback_data"]) == Demo(action="sn_toggle", value=0)
    assert [s["text"] for s in stages] == [
        "✓ 🔔 New order — accept or decline",  # already seen: quiet
        "🆕 🔔 Reminder 2 of 4 — nobody has answered",  # passed while away: new to you
        "🆕 ✅ Accepted by Ada — waiting for pickup time",  # current
        "🔒 ⏰ Pickup time set by Ada · pending",
        "🔒 🍽 Food ready for the rider · pending",
    ]
    assert "disabled" in stages[0] and "style" not in stages[0]
    assert "disabled" in stages[1] and stages[1]["style"] == "success"
    assert Demo.unpack(stages[2]["callback_data"]).action == "sn_seen" and stages[2]["style"] == "success"
    assert all("disabled" in s and "callback_data" not in s for s in stages[3:])

    await tap(dp, bot, "sn_seen", message_id=card)  # tapping the badge acknowledges everything
    badge, _, *stages, _ = rich_buttons(session.edits[-1].rich_message)
    assert badge["text"] == "✓ ✅ Accepted by Ada — waiting for pickup time"
    assert "disabled" in badge and "callback_data" not in badge and "style" not in badge
    assert [s["text"][:1] for s in stages[:3]] == ["✓", "✓", "●"]
    assert all("disabled" in s and "style" not in s for s in stages[:3])

    await tap(dp, bot, "sn_toggle", 0, message_id=card)  # collapse: only badge, toggle and Next update remain
    collapsed = rich_buttons(session.edits[-1].rich_message)
    assert [b["text"] for b in collapsed][1] == "Show steps" and len(collapsed) == 3
    await tap(dp, bot, "sn_toggle", 1, message_id=card)
    assert len(rich_buttons(session.edits[-1].rich_message)) == 8

    await tap(dp, bot, "sn_next", message_id=card)  # a new stage is unread again, and the colour returns
    badge, _, *stages, _ = rich_buttons(session.edits[-1].rich_message)
    assert badge["text"] == "🆕 ⏰ Pickup time set by Ada" and "callback_data" in badge
    assert stages[3]["text"] == "🆕 ⏰ Pickup time set by Ada" and "callback_data" in stages[3]
    assert stages[2]["text"] == "✓ ✅ Accepted by Ada — waiting for pickup time"  # seen before, stays quiet

    edits = len(session.edits)
    await tap(dp, bot, "sn_toggle", 2, message_id=card)  # forged toggle value
    assert len(session.edits) == edits and "expired" in session.sent_texts[-1]


@pytest.mark.parametrize("acknowledge", ["card", "nudge"])
async def test_rolling_nudge_edits_silently_and_keeps_one_live_notification(recording_bot, acknowledge):
    bot, session = recording_bot
    dp, card = await open_seen(recording_bot, "seen_nudge")
    session.calls.clear()

    await tap(dp, bot, "sn_next", message_id=card)
    first_nudge = session.next_message_id
    assert [(e.message_id, "Reminder 2 of 4" in e.text) for e in session.edits] == [(card, True)]
    nudge = session.sends[-1]
    assert nudge.reply_parameters.message_id == card and not nudge.disable_notification
    assert preview(nudge.text).startswith("🔔 Reminder 2 of 4 — nobody has answered")  # lock-screen preview
    assert Demo.unpack(nudge.reply_markup.inline_keyboard[0][0].callback_data) == Demo(action="sn_nudge_seen", value=card)

    await tap(dp, bot, "sn_next", message_id=card)
    second_nudge = session.next_message_id
    assert (111, first_nudge) in session.deleted  # the older nudge is replaced, never stacked
    assert preview(session.sends[-1].text).startswith("✅ Accepted by Ada — waiting for pickup time")
    assert "Was: <i>🔔 New order — accept or decline</i>" in session.edits[-1].text
    assert_balanced_html(session.edits[-1].text)

    if acknowledge == "card":
        await tap(dp, bot, "sn_seen", message_id=card)
    else:
        await tap(dp, bot, "sn_nudge_seen", card, message_id=second_nudge)
    assert (111, second_nudge) in session.deleted
    assert session.edits[-1].message_id == card and "You're up to date" in session.edits[-1].text
    assert "Was:" not in session.edits[-1].text


async def test_repost_sends_a_new_card_deletes_the_old_one_and_moves_the_state(recording_bot):
    bot, session = recording_bot
    dp, card = await open_seen(recording_bot, "seen_bump")
    session.calls.clear()

    await tap(dp, bot, "sn_next", message_id=card)
    reposted = session.next_message_id
    assert reposted != card and not session.edits
    assert "Was: <i>🔔 New order — accept or decline</i>" in session.sends[-1].text
    assert "1 update since you last looked" in session.sends[-1].text
    assert preview(session.sends[-1].text).startswith("🆕 🔔 Reminder 2 of 4 — nobody has answered")
    assert (111, card) in session.deleted
    assert_balanced_html(session.sends[-1].text)

    session.calls.clear()
    await tap(dp, bot, "sn_seen", message_id=card)  # a tap that raced the delete
    assert "expired" in session.sent_texts[-1] and not session.edits
    await tap(dp, bot, "sn_seen", message_id=reposted)
    assert session.edits[-1].message_id == reposted and "You're up to date" in session.edits[-1].text


async def test_seen_demo_ends_restarts_and_expires_with_the_menu(recording_bot):
    bot, session = recording_bot
    dp, card = await open_seen(recording_bot, "seen_log")
    for _ in range(4):
        await tap(dp, bot, "sn_next", message_id=card)
    labels = keyboard_labels(session.edits[-1].reply_markup)
    assert "Restart" in labels and "Next update →" not in labels

    edits = len(session.edits)
    await tap(dp, bot, "sn_next", message_id=card)  # a queued tap for a button that is gone
    assert len(session.edits) == edits and "expired" in session.sent_texts[-1]

    await tap(dp, bot, "sn_reset", message_id=card)
    assert "Reminder" not in session.edits[-1].text and "You're up to date" in session.edits[-1].text

    await feed(dp, bot, message_update("/scratchpad"))
    edits = len(session.edits)
    await tap(dp, bot, "sn_next", message_id=card)
    assert len(session.edits) == edits and "expired" in session.sent_texts[-1]
