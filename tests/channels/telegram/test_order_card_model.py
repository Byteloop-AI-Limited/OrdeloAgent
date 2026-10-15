"""Pure tests for the order card model (no fakes, no I/O)."""

from datetime import datetime, timedelta, timezone

import pytest

from channels.telegram.callbacks import OrderAction, fits_callback_limit
from channels.telegram.rest_admin.order_cards.model import (
    TERMINAL,
    Accepted,
    Actor,
    AutoAccepted,
    Card,
    Declined,
    Facts,
    PickupChosen,
    Reminded,
    Snapshot,
    TapOutcome,
    Vanished,
    Viewer,
    toast,
)

T0 = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)  # winter: UK == UTC
ADA = Actor("Ada", "447700900001")
BOB = Actor("Bob", "447700900002")
FACTS = Facts("ELAS-CEKT-22", "delivery", "Elas", "£23.50", ("2x Biryani", "1x Naan"), T0)
ADA_V, BOB_V = Viewer("447700900001"), Viewer("447700900002")


def buttons(view):
    return [(b.text, b.callback_data) for row in (view.keyboard.inline_keyboard if view.keyboard else []) for b in row]


def card(status="awaiting", **kw):
    return Card(FACTS, status=status, **kw)


@pytest.mark.parametrize(
    "start,event,expected",
    [
        ("awaiting", Reminded(2, 4), "awaiting"),
        ("awaiting", Accepted(ADA), "accepted"),
        ("awaiting", Declined(ADA), "declined"),
        ("awaiting", AutoAccepted(T0), "auto_accepted"),
        ("accepted", AutoAccepted(T0), "auto_accepted"),
        ("accepted", PickupChosen(T0, ADA), "pickup_set"),
        ("awaiting", Vanished(), "gone"),
        ("accepted", Vanished(), "gone"),
        ("declined", Vanished(), "gone"),
    ],
)
def test_legal_transitions(start, event, expected):
    assert card(start, decided_by=ADA).apply(event).status == expected


@pytest.mark.parametrize(
    "start,event",
    [
        ("declined", Accepted(ADA)),
        ("declined", AutoAccepted(T0)),
        ("accepted", Declined(ADA)),
        ("accepted", Accepted(BOB)),
        ("awaiting", PickupChosen(T0, ADA)),
        ("pickup_set", Accepted(ADA)),
        ("pickup_set", AutoAccepted(T0)),
        ("auto_accepted", Declined(ADA)),
        ("accepted", Reminded(2, 4)),
        ("gone", Accepted(ADA)),
    ],
)
def test_illegal_transitions_are_noops(start, event):
    c = card(start, decided_by=ADA)
    assert c.apply(event) == c


def test_apply_does_not_mutate():
    c = card()
    c.apply(Accepted(ADA))
    assert c.status == "awaiting" and c.decided_by is None


@pytest.mark.parametrize(
    "snap,status",
    [
        (Snapshot("awaiting", FACTS), "awaiting"),
        (Snapshot("accepted", FACTS, ADA), "accepted"),
        (Snapshot("pickup_set", FACTS, ADA, T0 + timedelta(minutes=15)), "pickup_set"),
        (Snapshot("declined", FACTS, ADA), "declined"),
        (Snapshot("auto_accepted", FACTS, None, T0 + timedelta(minutes=30)), "auto_accepted"),
    ],
)
def test_from_snapshot(snap, status):
    c = Card.from_snapshot(snap)
    assert c.status == status and c.facts == FACTS


def test_from_snapshot_incomplete_degrades_to_awaiting():
    assert Card.from_snapshot(Snapshot("accepted", FACTS, None)).status == "awaiting"


def test_snapshot_from_json():
    s = Snapshot.from_json(
        {
            "status": "pickup_set",
            "facts": {
                "order_number": "ELAS-CEKT-22",
                "order_type": "takeaway",
                "rest_name": "Elas",
                "total": "£5.00",
                "items": ["1x Naan"],
                "ordered_at": "2026-01-15T12:00:00+00:00",
            },
            "decided_by": {"label": "Ada", "phone": "447700900001"},
            "pickup_at": "2026-01-15T12:15:00Z",
            "destinations": [{"tcid": 7, "tuid": 7, "phone": "447700900001"}, {"tcid": -100, "tuid": None}],
        }
    )
    assert s.facts.order_type == "takeaway" and s.pickup_at.minute == 15
    assert [d.tcid for d in s.destinations] == [7, -100] and s.destinations[1].tuid is None
    assert Snapshot.from_json(None) is None


def test_awaiting_view():
    v = card().view(ADA_V)
    assert v.text == (
        "🔔 New order — accept or decline\n"
        "<b>ELAS-CEKT-22</b> · £23.50 · 🚚 Delivery\n2x Biryani\n1x Naan\nOrdered 12:00 PM"
    )
    assert buttons(v) == [("✅ Accept", "ord:ELAS-CEKT-22:d:acc:0"), ("❌ Decline", "ord:ELAS-CEKT-22:d:dec:0")]
    assert not v.terminal


def test_reminder_suffix_only_after_first():
    assert "reminder" not in card(reminder=(1, 4)).view(ADA_V).text
    assert "· reminder 2 of 4" in card(reminder=(2, 4)).view(ADA_V).text


def test_accepted_decider_vs_other():
    c = card("accepted", decided_by=ADA)
    mine, theirs = c.view(ADA_V), c.view(BOB_V)
    assert mine.text.startswith("✅ You accepted — choose a pickup time")
    assert buttons(mine) == [
        ("12:05 PM", "ord:ELAS-CEKT-22:d:pk:5"),
        ("12:15 PM", "ord:ELAS-CEKT-22:d:pk:15"),
        ("12:25 PM", "ord:ELAS-CEKT-22:d:pk:25"),
    ]
    assert theirs.text.startswith("✅ Accepted by Ada — waiting for pickup time")
    assert theirs.keyboard is None and not mine.terminal


def test_pickup_set_and_declined_and_auto():
    p = card("pickup_set", decided_by=ADA, pickup_at=T0 + timedelta(minutes=15))
    assert p.view(ADA_V).text.startswith("✅ You accepted · pickup 12:15 PM")
    assert p.view(BOB_V).text.startswith("✅ Accepted by Ada · pickup 12:15 PM")
    d = card("declined", decided_by=ADA)
    assert d.view(ADA_V).text.startswith("❌ You declined this order")
    assert d.view(BOB_V).text.startswith("❌ Declined by Ada")
    a = card("auto_accepted", pickup_at=T0 + timedelta(minutes=30))
    assert a.view(BOB_V).text.startswith("⏱ Auto-accepted (no answer in time) · pickup 12:30 PM")
    for c in (p, d, a):
        assert c.view(ADA_V).terminal and c.view(ADA_V).keyboard is None


def test_gone_and_unauthorised():
    g = Card.vanished(FACTS).view(ADA_V)
    assert g.text == "This order is no longer available." and g.terminal and g.keyboard is None
    u = card().view(Viewer("447700900001", authorised=False))
    assert u.text.startswith("🔒") and u.keyboard is None and u.terminal


def test_shared_view_is_third_person_with_pickup_buttons():
    shared = Viewer(None, shared=True)
    c = card("accepted", decided_by=ADA)
    v = c.view(shared)
    assert v.text.startswith("✅ Accepted by Ada") and len(buttons(v)) == 3
    # a group never says "You", even if the phone would match
    assert "You" not in card("declined", decided_by=ADA).view(Viewer(ADA.phone, shared=True)).text


def test_html_escaped():
    f = Facts("A<B>-1", "takeaway", "R&D", "£1", ("1x <script>", "2x Fish & Chips"), T0)
    t = Card(f).view(ADA_V).text
    assert "<script>" not in t and "&lt;script&gt;" in t and "Fish &amp; Chips" in t and "A&lt;B&gt;-1" in t
    c = Card(f, status="declined", decided_by=Actor("<i>x</i>", "1"))
    assert "&lt;i&gt;x&lt;/i&gt;" in c.view(BOB_V).text


def test_takeaway_line_and_callback_type():
    f = Facts("TK-1", "takeaway", "Elas", "£1", (), T0)
    v = Card(f).view(ADA_V)
    assert "🥡 Takeaway" in v.text and buttons(v)[0][1] == "ord:TK-1:t:acc:0"


def test_callback_fits_for_long_order_number():
    long = "X" * 40
    assert fits_callback_limit(OrderAction(o=long, t="d", a="pk", m=25))
    # 60-char number does not fit -> buttons dropped, no raise
    f = Facts("Y" * 60, "delivery", "Elas", "£1", (), T0)
    v = Card(f).view(ADA_V)
    assert v.keyboard is None and "Y" * 60 in v.text


def test_terminal_set_matches_views():
    assert TERMINAL == {"pickup_set", "declined", "auto_accepted", "gone"}


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (TapOutcome("ok", "acc"), ("Accepted — pick a time", False)),
        (TapOutcome("ok", "dec"), ("Declined", False)),
        (TapOutcome("ok", "pk", pickup_at=T0 + timedelta(minutes=15)), ("Pickup 12:15 PM", False)),
        (TapOutcome("already_decided", "acc", "accepted", ADA), ("Already accepted by Ada", False)),
        (TapOutcome("already_decided", "acc", "declined", ADA), ("Already declined by Ada", False)),
        (TapOutcome("already_decided", "acc", "auto_accepted"), ("Already auto-accepted", False)),
        (TapOutcome("already_set", "pk", pickup_at=T0 + timedelta(minutes=5)), ("Pickup already set to 12:05 PM", False)),
        (TapOutcome("not_accepted", "pk"), ("This order is not accepted yet.", False)),
        (TapOutcome("not_authorised", "acc"), ("You're not an admin for this restaurant any more.", True)),
        (TapOutcome("not_found", "acc"), ("This order is no longer available.", False)),
    ],
)
def test_toasts(outcome, expected):
    assert toast(outcome) == expected
