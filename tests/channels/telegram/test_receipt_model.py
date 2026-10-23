"""Pure receipt views: every status key x viewer, buttons and callback sizes, escaping, the 4096 cut, toasts."""

from __future__ import annotations

from html import escape

import pytest

from channels.telegram.callbacks import CALLBACK_DATA_MAX_BYTES
from channels.telegram.rest_admin.order_cards.model import Viewer
from channels.telegram.rest_admin.receipts.model import (
    FLOW_ROWS_IN_DETAILS,
    TEXT_LIMIT,
    Receipt,
    ReceiptSnapshot,
    receipt_toast,
    status_kind,
)
from utils_common.order_management.restaurant_actions import ActionOutcome

from .rich_view import rich_buttons_of, rich_text


def snap(status="open@13:00", order_type="delivery", **facts):
    base = {
        "order_number": "ELAS-CEKT-22", "order_type": order_type, "rest_name": "Elai", "rest_code": 47,
        "pickup_at": "2026-10-15T12:00:00+00:00", "pickup_initial": None, "pickup_adjusted_by": None,
        "ready_at": None, "ready_by": None,
        "rider": {"id": "RIDER01", "name": "Sam"} if order_type == "delivery" else None,
        "customer": {"address": "1 Test Street", "phone": "4474"} if order_type == "delivery" else None,
        "items": [{"qty": 2, "name": "Chicken Shawarma", "line_total": 17.0, "mods": ["extra garlic sauce"]},
                  {"qty": 1, "name": "Fries", "line_total": 3.5, "mods": []}],
        "small_order_fee": 1.0, "total": 21.5, "notes": "Please ring the bell twice",
        "pay_at_restaurant": False, "completed_at": None,
    }
    base.update(facts)
    return ReceiptSnapshot.from_json({"status": status, "rest_ref": "ELAS", "dispatch_id": 10, "facts": base, "destinations": []})


def view(status="open@13:00", viewer=None, order_type="delivery", **facts):
    return Receipt.from_snapshot(snap(status, order_type, **facts)).view(viewer or Viewer("447700900001"))


def buttons(v):
    return [] if v.keyboard is None else [b for row in v.keyboard.inline_keyboard for b in row]


ADA = {"label": "Ada", "phone": "447700900001"}


def test_open_delivery_has_everything_the_kitchen_needs():
    t = view().text
    assert t.splitlines()[0] == "🧾 KITCHEN RECEIPT · 🚚 Delivery"
    for part in ("<b>ELAS-CEKT-22</b>", "🔑 Restaurant code: <b>47</b>", "⏰ Pickup: <b>1:00 PM</b>", "🛵 Rider: Sam — RIDER01",
                 "<b>Items</b>", "• 2 × Chicken Shawarma — £17.00", "   ↳ extra garlic sauce", "• 1 × Fries — £3.50",
                 "Small order fee: £1.00", "<b>Total: £21.50</b>", "📝 <b>Notes</b>", "<i>Please ring the bell twice</i>",
                 "🏠 Customer: 1 Test Street — 4474"):
        assert part in t, part
    assert t.splitlines()[2].startswith("🔑")  # no status line in the head until something happened


def test_open_delivery_buttons_are_ready_then_plus_ten_and_twenty():
    bs = buttons(view())
    assert [b.callback_data for b in bs] == ["ord:ELAS-CEKT-22:d:rdy:0", "ord:ELAS-CEKT-22:d:adj:10", "ord:ELAS-CEKT-22:d:adj:20"]
    assert [b.text for b in bs] == ["🍳 Ready – notify rider", "1:10 PM (+10)", "1:20 PM (+20)"]
    assert all(len(b.callback_data.encode()) <= CALLBACK_DATA_MAX_BYTES for b in bs)


def test_adjust_buttons_are_relative_to_the_original_pickup_never_cumulative():
    v = view("open@13:10", pickup_at="2026-10-15T12:10:00+00:00", pickup_initial="2026-10-15T12:00:00+00:00",
             pickup_adjusted_by=ADA)
    assert [b.text for b in buttons(v)][1:] == ["1:10 PM (+10)", "1:20 PM (+20)"]
    assert "(moved +10 by You)" in v.text
    other = view("open@13:10", Viewer("447700900002"), pickup_at="2026-10-15T12:10:00+00:00",
                 pickup_initial="2026-10-15T12:00:00+00:00", pickup_adjusted_by=ADA)
    assert "(moved +10 by Ada)" in other.text


def test_ready_delivery_drops_the_ready_button_and_says_who():
    v = view("ready@13:00", ready_at="2026-10-15T12:01:00+00:00", ready_by=ADA)
    assert "✅ Marked ready by You" in v.text
    assert [b.callback_data.split(":")[3] for b in buttons(v)] == ["adj", "adj"] and not v.terminal
    assert "Marked ready by Ada" in view("ready@13:00", Viewer("447700900002"), ready_by=ADA).text
    assert "Marked ready by Ada" in view("ready@13:00", Viewer(None, shared=True), ready_by=ADA).text  # group: third person


@pytest.mark.parametrize("key,line,terminal", [
    ("picked_up", "🛵 Picked up by the rider", False),
    ("done", "✅ Delivered", True),
    ("rider_cancelled", "⚠️ This rider is no longer on the job", True),
])
def test_closed_states_have_no_buttons(key, line, terminal):
    v = view(key)
    assert line in v.text and buttons(v) == [] and v.terminal is terminal


def test_gone_and_unauthorised_views():
    assert view("gone").text == "This order is no longer available." and view("gone").terminal
    locked = Receipt.from_snapshot(snap()).view(Viewer("447700900001", authorised=False))
    assert locked.text.startswith("🔒") and locked.keyboard is None and locked.terminal


def test_takeaway_open_has_only_ready_and_the_pay_line():
    v = view("open@13:00", order_type="takeaway", pay_at_restaurant=True)
    assert [b.callback_data for b in buttons(v)] == ["ord:ELAS-CEKT-22:t:rdy:0"]
    assert "🥡 Takeaway" in v.text and "💷 <b>Pay at restaurant — collect £21.50</b>" in v.text
    assert "Rider" not in v.text and "Customer" not in v.text
    ready = view("ready@13:00", order_type="takeaway", ready_by=ADA)
    assert "✅ Marked ready by You" in ready.text and buttons(ready) == []
    assert "✅ Collected" in view("done", order_type="takeaway").text


def test_everything_user_supplied_is_escaped():
    v = view(items=[{"qty": 1, "name": "<b>Bomb</b> & chips", "line_total": 1, "mods": ["no <onion>"]}],
             notes="a < b & <script>", rider={"id": "R<1>", "name": "S&m"},
             customer={"address": "<home>", "phone": "1"})
    assert "<script>" not in v.text and "&lt;script&gt;" in v.text
    assert "&lt;b&gt;Bomb&lt;/b&gt; &amp; chips" in v.text and "no &lt;onion&gt;" in v.text
    assert "S&amp;m — R&lt;1&gt;" in v.text and "&lt;home&gt;" in v.text


def test_huge_order_is_cut_with_a_marker_and_always_fits():
    items = [{"qty": 1, "name": f"Dish number {i} " + "x" * 60, "line_total": 1.5, "mods": ["m" * 40, "n" * 40]} for i in range(120)]
    v = view(items=items, notes="n" * 5000)
    assert len(v.text) <= TEXT_LIMIT <= 4096
    assert "more items (see WhatsApp/printer)" in v.text
    assert "<b>Total: £21.50</b>" in v.text and "📝 <b>Notes</b>" in v.text   # money and notes always survive the cut
    assert "…" in v.text.split("Notes")[1]                                      # notes are capped too


def test_a_small_order_is_never_cut():
    assert "more items" not in view().text


def test_missing_values_show_a_dash_not_a_crash():
    v = view(rest_code=None, pickup_at=None, total=None, small_order_fee=None, notes=None, rider=None, customer=None)
    assert "Restaurant code: <b>—</b>" in v.text and "⏰ Pickup: —" in v.text and "Total: —" in v.text
    assert buttons(v)[0].callback_data.endswith("rdy:0") and len(buttons(v)) == 1  # no base time: no +N buttons


def test_status_kind():
    assert status_kind("ready@12:50") == "ready" and status_kind("done") == "done"


@pytest.mark.parametrize("action,order_type,out,expect", [
    ("rdy", "delivery", ActionOutcome("ok"), ("Marked ready — rider told", False)),
    ("rdy", "takeaway", ActionOutcome("ok"), ("Marked ready — customer told", False)),
    ("rdy", "delivery", ActionOutcome("ok", follow_up_failed=True),
     ("Marked ready, but the rider could not be messaged. Please contact them.", True)),
    ("adj", "delivery", ActionOutcome("ok", pickup_time="2026-10-15T11:50:00+00:00"), ("Pickup 12:50 PM", False)),
    ("adj", "delivery", ActionOutcome("unchanged", pickup_time="2026-10-15T11:50:00+00:00"), ("Pickup already 12:50 PM", False)),
    ("rdy", "delivery", ActionOutcome("already_ready", by_label="Ada"), ("Already marked ready by Ada", False)),
    ("rdy", "delivery", ActionOutcome("not_ready_state", progress="picked_up"), ("Food already picked up", False)),
    ("adj", "delivery", ActionOutcome("not_ready_state", progress="not_in_progress"), ("This order is no longer in progress", False)),
    ("rdy", "delivery", ActionOutcome("not_authorised"), ("You're not an admin for this restaurant any more.", True)),
    ("rdy", "delivery", ActionOutcome("not_found"), ("This order is no longer available.", False)),
])
def test_toasts(action, order_type, out, expect):
    assert receipt_toast(action, order_type, out) == expect


# ---- the rich form: status badge, collapsible flow, embedded buttons ------------------------------------------------------

READY = dict(ready_by=ADA, ready_at="2026-10-15T12:30:00+00:00")


def rich_blocks(v):
    return v.rich.model_dump(mode="json", exclude_none=True)["blocks"]


@pytest.mark.parametrize("status,extra,text,style,tappable", [
    ("open@13:00", {}, "📋 Preparing · pickup 1:00 PM", "primary", True),
    ("ready@13:30", READY, "✅ Marked ready by You", "success", True),
    ("picked_up", {}, "🛵 Picked up by the rider", "success", True),
    ("done", {}, "✅ Delivered", "success", False),
    ("rider_cancelled", {}, "⚠️ This rider is no longer on the job", "danger", False),
])
def test_badge_text_colour_and_whether_it_can_be_tapped(status, extra, text, style, tappable):
    badge = rich_buttons_of(view(status, **extra).rich)[0]
    assert (badge["text"], badge["style"]) == (text, style)
    assert ("callback_data" in badge) is tappable and ("disabled" in badge) is not tappable
    if tappable:  # a refresh, never an action on the order
        assert badge["callback_data"] == "ord:ELAS-CEKT-22:d:st:0"


def test_takeaway_badge_says_collected_and_a_group_never_says_you():
    assert rich_buttons_of(view("done", order_type="takeaway").rich)[0]["text"] == "✅ Collected"
    shared = view("ready@13:30", viewer=Viewer(None, shared=True), **READY)
    assert rich_buttons_of(shared.rich)[0]["text"] == "✅ Marked ready by Ada"


# snap() times are UTC; the receipt shows UK time (BST in October): 10:40Z -> 11:40 AM, 12:00Z pickup -> 1:00 PM
ACCEPTED = {"accepted_by": ADA, "accepted_at": "2026-10-15T10:40:00+00:00"}
READY_AT = {"ready_at": "2026-10-15T10:55:00+00:00", "ready_by": ADA}
DONE_AT = {"completed_at": "2026-10-15T11:25:00+00:00"}


def steps_of(status="open@13:00", order_type="delivery", viewer=None, **facts):
    r = Receipt.from_snapshot(snap(status, order_type, **facts))
    return [(s.text(), s.state) for s in r.timeline(viewer or Viewer("447700900002"))]


@pytest.mark.parametrize("status,order_type,phase", [
    ("open@13:00", "delivery", "kitchen"), ("ready@13:00", "delivery", "kitchen"), ("rider_cancelled", "delivery", "kitchen"),
    ("picked_up", "delivery", "handed_over"), ("done", "delivery", "handed_over"),
    ("open@13:00", "takeaway", "kitchen"), ("done", "takeaway", "handed_over"),
])
def test_phase_follows_the_status_key(status, order_type, phase):
    assert Receipt.from_snapshot(snap(status, order_type)).phase == phase


def test_timeline_open_delivery():
    assert steps_of(**ACCEPTED) == [
        ("✓ ✅ Accepted by Ada · 11:40 AM", "done"),  # viewer ...002 is not Ada, so never "You"
        ("● ⏰ Pickup 1:00 PM", "latest"),
        ("🔒 🍳 Food ready · pending", "todo"),
        ("🔒 🛵 Rider picks up · pending", "todo"),
        ("🔒 🏁 Delivered · pending", "todo"),
    ]


def test_timeline_done_delivery_marks_everything_and_delivered_is_latest():
    s = steps_of("done", **DONE_AT, **ACCEPTED, **READY_AT)
    assert [st for _, st in s] == ["done", "done", "done", "done", "latest"]
    assert s[2][0] == "✓ 🍳 Ready by Ada · 11:55 AM" and s[3][0] == "✓ 🛵 Picked up by Sam" and s[4][0] == "● 🏁 Delivered · 12:25 PM"


def test_timeline_rider_cancelled_ends_in_red_with_nothing_to_come():
    s = steps_of("rider_cancelled", **READY_AT)
    assert s[-1] == ("⚠️ This rider is no longer on the job", "failed")
    assert [st for _, st in s] == ["done", "done", "done", "failed"]


def test_timeline_takeaway_has_four_steps_ending_collected():
    s = steps_of("done", "takeaway", **READY_AT)
    assert len(s) == 4 and s[-1] == ("● 🏁 Collected", "latest")


def test_timeline_accepted_variants():
    assert steps_of(accepted_auto=True)[0][0] == "✓ ✅ Accepted automatically"
    assert steps_of()[0][0] == "✓ ✅ Accepted"  # snapshot from the old SQL: no accepted keys
    assert steps_of(viewer=Viewer("447700900001"), **ACCEPTED)[0][0].startswith("✓ ✅ Accepted by You")
    assert steps_of(viewer=Viewer(None, shared=True), **ACCEPTED)[0][0].startswith("✓ ✅ Accepted by Ada")


def test_timeline_ready_not_marked_when_the_order_moved_past_it():
    assert steps_of("picked_up")[2] == ("✓ 🍳 Ready (not marked)", "done")


def test_handed_over_rich_layout_folds_the_order_away():
    v = view("done", **DONE_AT, **ACCEPTED, **READY_AT)
    top = rich_blocks(v)
    assert [b["type"] for b in top] == ["heading", "paragraph", "buttons", *["buttons"] * 5, "paragraph", "details"]
    assert top[-1]["summary"] == "🔵 Order details · tap to expand" and top[-1]["is_open"] is False
    above, folded = rich_text(v.rich).split("🔵 Order details", 1)
    for part in ("⏰ Pickup:", "🔑 Restaurant code", "Items", "Total: £21.50", "📝 Notes", "🏠 Customer"):
        assert part in folded and part not in above, part
    assert "🛵 Rider: Sam — RIDER01" in above and "[● 🏁 Delivered · 12:25 PM]" in above
    assert not [b for b in rich_buttons_of(v.rich) if "callback_data" in b]  # nothing to tap once delivered


def test_flow_rows_are_disabled_and_coloured_by_state():
    rows = rich_buttons_of(view("picked_up", **ACCEPTED, **READY_AT).rich)[1:]  # [0] is the badge
    assert all("disabled" in b and "callback_data" not in b for b in rows)
    assert [b.get("style") for b in rows] == [None, None, None, "success", None]
    assert any(b.get("style") == "danger" for b in rich_buttons_of(view("rider_cancelled", **READY_AT).rich))


def test_kitchen_flow_is_inside_the_closed_progress_block():
    flow = next(b for b in rich_blocks(view("ready@13:00", **ACCEPTED, **READY_AT)) if b["type"] == "details")
    assert flow["summary"] == "Progress · step 3 of 5" and flow["is_open"] is False
    assert all(b["type"] == ("buttons" if FLOW_ROWS_IN_DETAILS else "paragraph") for b in flow["blocks"])
    takeaway = next(b for b in rich_blocks(view(order_type="takeaway")) if b["type"] == "details")
    assert takeaway["summary"] == "Progress · step 2 of 4"
    cancelled = next(b for b in rich_blocks(view("rider_cancelled")) if b["type"] == "details")
    assert cancelled["summary"] == "Progress · rider no longer on the job"


def test_handed_over_html_folds_the_order_into_an_expandable_quote():
    t = view("done", **DONE_AT, **ACCEPTED).text
    cut = t.index("<blockquote expandable><b>🔵 Order details · tap to expand</b>")
    above, folded = t[:cut], t[cut:]
    assert "<b>● 🏁 Delivered · 12:25 PM</b>" in above and "🛵 Rider: Sam" in above
    for part in ("🔑 Restaurant code", "⏰ Pickup:", "<b>Items</b>", "Total: £21.50", "📝 <b>Notes</b>", "🏠 Customer"):
        assert part in folded and part not in above, part
    assert t.endswith("</blockquote>")


def test_kitchen_html_has_the_progress_quote_and_everything_else_as_before():
    t = view(**ACCEPTED).text
    assert "<blockquote expandable><b>Progress · step 2 of 5</b>" in t and "🔒 🏁 Delivered · pending" in t
    assert "🔑 Restaurant code: <b>47</b>" in t.split("<blockquote")[0]


def test_rich_and_html_show_the_same_steps():
    for status in ("open@13:00", "ready@13:00", "picked_up", "done", "rider_cancelled"):
        r = Receipt.from_snapshot(snap(status, **ACCEPTED, **READY_AT))
        v = r.view(Viewer("447700900001"))
        for st in r.timeline(Viewer("447700900001")):
            assert st.text() in rich_text(v.rich) and escape(st.text()) in v.text, (status, st)


def test_no_relative_time_anywhere():
    for status in ("open@13:00", "ready@13:00", "done"):
        assert "date_time" not in view(status, **READY_AT).rich.model_dump_json()


def test_flow_text_is_escaped_in_html_only():
    v = view("picked_up", rider={"id": "R1", "name": "<b>Sam</b> & co"})
    assert "Picked up by &lt;b&gt;Sam&lt;/b&gt; &amp; co" in v.text and "Picked up by <b>Sam</b> & co" in rich_text(v.rich)


def test_huge_handed_over_order_still_fits_and_matches():
    items = [{"qty": 1, "name": f"Dish {i} " + "x" * 60, "line_total": 1.5, "mods": ["m" * 40]} for i in range(120)]
    v = view("done", items=items, notes="n" * 5000)
    assert len(v.text) <= TEXT_LIMIT and v.text.count("• ") == rich_text(v.rich).count("• ") < 120


def test_snapshot_reads_the_accepted_keys_and_defaults_without_them():
    f = snap(**ACCEPTED, accepted_auto=False).facts
    assert f.accepted_by.label == "Ada" and f.accepted_at is not None and f.accepted_auto is False
    old = snap().facts
    assert old.accepted_by is None and old.accepted_at is None and old.accepted_auto is False


@pytest.mark.parametrize("status,extra,order_type", [
    ("open@13:00", {}, "delivery"), ("ready@13:30", READY, "delivery"), ("picked_up", {}, "delivery"),
    ("done", {}, "delivery"), ("open@13:00", {}, "takeaway"), ("ready@13:30", READY, "takeaway"),
])
def test_rich_buttons_are_the_html_buttons_plus_the_badge(status, extra, order_type):
    v = view(status, order_type=order_type, **extra)
    rich = [b["callback_data"] for b in rich_buttons_of(v.rich) if "callback_data" in b]
    html = [b.callback_data for b in buttons(v)]
    badge = [d for d in rich if d.split(":")[3] == "st"]
    assert [d for d in rich if d not in badge] == html
    assert len(badge) == (0 if status == "done" else 1)
    assert all(len(d.encode()) <= CALLBACK_DATA_MAX_BYTES for d in rich)


def test_the_rich_form_shows_the_same_items_and_the_same_cut_as_the_html():
    items = [{"qty": 1, "name": f"Dish number {i} " + "x" * 60, "line_total": 1.5, "mods": ["m" * 40, "n" * 40]} for i in range(120)]
    v = view(items=items, notes="n" * 5000)
    html_items, rich_items = v.text.count("• "), rich_text(v.rich).count("• ")
    assert 0 < rich_items == html_items < 120
    assert "more items (see WhatsApp/printer)" in rich_text(v.rich)
    assert "Total: £21.50" in rich_text(v.rich) and "📝 Notes" in rich_text(v.rich)


def test_rich_text_is_not_html_escaped_but_html_still_is():
    v = view(items=[{"qty": 1, "name": "Fish & <b>Chips</b>", "line_total": 5.0, "mods": []}])
    assert "Fish & <b>Chips</b>" in rich_text(v.rich)
    assert "Fish &amp; &lt;b&gt;Chips&lt;/b&gt;" in v.text


def test_gone_and_locked_copies_stay_rich_so_a_rich_message_is_never_edited_to_plain_text():
    locked = Receipt.from_snapshot(snap()).view(Viewer("447700900001", authorised=False))
    assert rich_text(locked.rich).startswith("🔒") and rich_buttons_of(locked.rich) == []
    assert rich_text(view("gone").rich) == "This order is no longer available."
    from channels.telegram.rest_admin.receipts.model import gone_view

    assert rich_text(gone_view().rich) == "This order is no longer available."


def test_a_failure_building_the_rich_form_leaves_the_html_form_working(monkeypatch):
    def boom(self, viewer, shown):
        raise RuntimeError("rich form broke")

    monkeypatch.setattr(Receipt, "_rich", boom)
    v = view()
    assert v.rich is None and v.text.startswith("🧾 KITCHEN RECEIPT") and buttons(v)
