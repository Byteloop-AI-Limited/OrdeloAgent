# Telegram kitchen receipt: phase layout and progress flow

**Repository:** `OrdeloAgent`. **Written:** 23 October 2026, after a grilling session with the owner (the decisions below are the record).
**Status:** ✅ built and verified offline (23 Oct 2026, see "As built" at the end); ⏳ live check and SQL apply wait for the owner. **Builds on:** the uncommitted "rich receipt" change of 23 Oct 2026 (badge + closed Progress block +
HTML fallback; `docs/telegram-layer.md` change log 2026-10-23). That change must be committed (or at least present) before this one starts.
**Related:** [`telegram-phase-7-8-kitchen-actions-and-notices.md`](telegram-phase-7-8-kitchen-actions-and-notices.md) (receipt origin, D28–D38),
[`telegram-rest-admin-scaffold-plan.md`](telegram-rest-admin-scaffold-plan.md) (rules, D11–D27), project doc `claude/telegram-group-chats-status.md`.
Decision numbers continue after D54 (`telegram-rider-bot-plan.md`).

---

## 1. What the owner asked for

From a live screenshot of a delivered order (`STRK-TEST-083619`):

> If the pickup is complete then the items, notes, total and the restaurant code can all go in a collapsible element as they are not of
> interest anymore. So is the pickup time. With this, you can then have the [progress] flow as rich text like in the image [the
> `/eg → 🚦 Status badge + flow` demo: one coloured button row per step]. This flow should show completed steps and the steps to be
> completed as well. After the pickup, the receipt will have a new button to 'request_rider_location'. [If not already built], leave it for now.

What the screenshot showed (all facts, verified 23 Oct 2026 on the owner's phone):
- Badge `✅ Delivered 9:40 AM` (green, disabled) renders correctly.
- The line under the badge rendered as just **`Delivered`**. The `RichTextDateTime(date_time_format="r")` relative time rendered as
  **nothing** on the owner's client. → remove it (D61).
- `Progress · step 4 of 4` closed block, then code, rider, items, total, notes, customer: everything still on top after delivery.
- The receipt is a reply to the order card (`✅ Accepted by lohith · pickup 9:41 AM …` quote header). Unchanged by this plan.

## 2. Decisions (grilling record, 23 Oct 2026)

| # | Decision | Owner's answer |
|---|---|---|
| D55 | **Phase rule.** Compact ("handed over") layout for delivery `picked_up` / `done` and takeaway `done` (collected). `open`, `ready` and `rider_cancelled` keep the full ("kitchen") layout; after a rider cancels, the food may need handing over again. | Handed over (recommended) |
| D56 | **Flow look = image 2.** One **disabled** button row per step. Done: grey, `✓`, who, time. Latest: green (`success`). Failed (rider cancelled): red (`danger`). To come: grey, `🔒 … · pending`. Normal size: Telegram has no smaller font for buttons. | Button rows (recommended) |
| D57 | **Flow placement.** Kitchen phase: inside the closed `Progress` block (as now), so grey rows never sit next to the real Ready/+10/+20 buttons. Handed-over phase: shown open, directly under the badge. If Telegram refuses buttons inside a details block, the closed block falls back to text lines (switch `FLOW_ROWS_IN_DETAILS`, decided by the step-0 spike). | Closed until handover (recommended) |
| D58 | **SQL scope: read-only.** `t_receipt_snapshot` gains `accepted_by`, `accepted_at` and `accepted_auto` from existing columns. No new columns, no new writes. `Picked up` has no time: `delivery_dispatch.status_update_dtts` is overwritten when the dispatch completes. | Read-only snapshot change (recommended) |
| D59 | **Visible after handover:** badge, flow, rider line. Hidden in a closed `🔵 Order details · tap to expand` block: pickup time, restaurant code, items, fee/total, pay-at-restaurant, notes, customer. | Rider visible, customer hidden (recommended) |
| D60 | **HTML fallback follows the same layout.** It is drawn from the same `phase` and `timeline()`: flow as text lines, `Order details` and `Progress` as `<blockquote expandable>`. | Same layout (recommended) |
| D61 | **No relative time.** Delete `_when_line()` (the line under the badge); times are clock times inside the flow. | Confirmed in the summary |
| D62 | **Rider-location button: not built, no placeholder.** A button that does nothing would confuse staff. Design notes in §9 for when it is built. | "Leave it for now" |

Unchanged: no seen-state; same card for shared (group) viewers (`Viewer.shared`, never "You"); rich-first with HTML fallback only on
`TelegramBadRequest` (`order_cards/io.py`); the badge stays and stays tappable (`st` = redraw from the database) while not terminal.

## 3. Facts the implementer needs (all verified in the code on 23 Oct 2026)

### Files
| File | Role in this change |
|---|---|
| `channels/telegram/rest_admin/receipts/model.py` | **The only Python file whose behaviour changes.** Pure `Receipt` (485 lines). `Receipt.view(viewer) -> View` is the only interface; nothing outside calls the private methods. |
| `channels/telegram/rest_admin/receipts/__init__.py` | `Receipts.send/refresh/tap`. **No change.** Calls `Receipt.from_snapshot(snap).view(Viewer(...))` in `_send_one` and `_refresh_one`. |
| `channels/telegram/rest_admin/order_cards/io.py` | `TelegramIO.send/edit`, rich first, then HTML on `TelegramBadRequest`. **No change.** |
| `channels/telegram/rest_admin/order_cards/model.py` | `View(text, keyboard, terminal, rich)`, `Viewer(phone, authorised=True, shared=False)`, `Actor(label, phone)`. **No change.** |
| `ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql` | `t_receipt_snapshot()` (≈ lines 485–640) and `t_receipt_status()` (line 423). Snapshot gains 3 fact keys. |
| `channels/telegram/rest_admin/scratchpad.py` | `/eg` demos. Gains one demo for the live spike and visual check (step 0). |
| `tests/channels/telegram/test_receipt_model.py` | Pure model tests. Helpers `snap()`, `view()`, `buttons()`, `rich_blocks()`, `ADA`, `READY`. |
| `tests/channels/telegram/test_receipts.py` | Dispatcher-level tests (`RecordingSession`, `FakeReceiptStore`, `FakeCardStore`). |
| `tests/channels/telegram/rich_view.py` | `rich_text`, `rich_buttons_of`, `text_of`, `button_data_of`, `all_sends`. `_walk` already flattens `details` and `buttons`. |
| `tests/sql/test_restaurant_ready_adjust_notices_sql.py` | Isolated-DB tests (skipped without `ORDELO_TEST_DB_URI`). Helpers `delivery(db, **cols)`, `takeaway()`, `rider()`, `ready()`, `adjust()`, `cancel_rider()`. Snapshot tests at ≈ line 405. |
| `docs/telegram-layer.md` + `docs/telegram-layer.html` | Receipt section and change log. |

### Status keys (from SQL `t_receipt_status`, read by `status_kind()`)
`gone | done | rider_cancelled | picked_up | ready@HH:MI | open@HH:MI` (delivery); takeaway has no `picked_up` or `rider_cancelled`.
`TERMINAL_KINDS = {"gone", "done", "rider_cancelled"}`. Copies are refreshed only when the **status key** changes
(`t_receipts_stale()`); the new facts never change after the receipt is sent, so there is no staleness gap.

### Where "accepted" lives (D58)
- `delivery_summary.restaurant_admin` (varchar 12, admin phone) and `restaurant_update_dtts`. Same columns on `takeaway_summary`.
- `restaurant_confirmation_status` is `'auto_accept'` for auto-accepted orders (then `restaurant_admin` is NULL).
- **Gotchas:**
  - `restaurant_order_adjust_pickup` (+10/+20, `restaurant_ready_adjust_notices.sql` ≈ line 304) sets `restaurant_update_dtts = now()` and
    `restaurant_confirmation_status = 'restaurant_pickuptime_adjusted'`. After a move, the accept time and the auto flag are lost. The
    snapshot therefore returns `accepted_at = NULL` whenever `pickup_adjusted_at IS NOT NULL`, and the step shows no time.
  - `restaurant_order_set_pickup` (`restaurant_order_decision.sql` ≈ line 250) sets `restaurant_admin` and `restaurant_update_dtts`
    again. "Accepted by" therefore names whoever **set the pickup time** (normally the same person), at that time.
  - The timeout job (`process_restaurant_confirmation.sql`) also writes `restaurant_update_dtts`, but timed-out orders never get a receipt.
- `restaurant_admin_label(phone)` gives the display label (invite first name, else last 4 digits). It is already used for `ready_by`.

### Telegram rich-message facts (aiogram 3.31.0, `/tmp/venv313/lib/python3.13/site-packages/aiogram/types/`)
- `RichMessageButton(text, style, callback_data | disabled=DisabledButton(), …)`. `style` is one of `danger|success|primary|link`, or
  omitted (app default = grey). The button text may only be plain text, custom emoji and `RichTextDateTime`.
- `InputRichBlockButtons(buttons=[1..8], align=None)` is one row.
- `InputRichBlockDetails(summary, blocks: list[InputRichBlockUnion], is_open)`. A Buttons block is an `InputRichBlockUnion` member, so the
  types allow nesting. **Whether Telegram accepts it is unverified** → step 0.
- **Brightness:** in the `/eg` demo, a disabled `success` button rendered **dim** green (image 2, row 2) and a tappable one **bright**
  green (row 3). Disabled flow rows will therefore be dim green. Bright needs callback data (see §10).
- Other blocks seen but not used here: `InputRichBlockFooter` (small text), `InputRichBlockList` with `has_checkbox` / `is_checked`,
  `InputRichBlockMap` (useful for §9), `InputRichBlockTable`, `InputRichBlockDivider`.
- HTML `<blockquote expandable>` shows a ~3-line preview when collapsed, not a fully hidden block. That is acceptable for the fallback.

## 4. Design

`Receipt` is already a deep module: one interface (`view(viewer) -> View`), and every caller and test crosses it. This change keeps that
interface and adds **two internal decisions** that both renderers read. That gives two adapters of one decision, which is a real seam,
not a hypothetical one:

```
                 ReceiptFacts + status key
                          │
            ┌─────────────┴─────────────┐
            │  phase   (kitchen | handed_over)       ← D55, one property
            │  timeline(viewer) -> tuple[Step, ...]  ← D56/D58, one pure function
            └─────────────┬─────────────┘
          ┌───────────────┴───────────────┐
   _rich(viewer, shown)            _fit(viewer) -> (html, shown)
   (rich renderer)                 (HTML renderer, owns the 4000-char cut)
          └───────────────┬───────────────┘
                    view(viewer) -> View(text, keyboard, terminal, rich)
```

- `phase` and `timeline()` are public on `Receipt`. They are pure and cheap, and a few direct tests pin the step states. Everything else
  is tested through `view()`.
- `_fit` stays the single owner of "how many items fit". `_rich` receives `shown` from it, as today, so the two forms always show the same items.
- The badge (`_badge`, `_badge_text`, `BADGE_STYLES`) is unchanged.

## 5. Implementation steps

Each step names the files and gives code. Line numbers are approximate (≈) and refer to the working tree of 23 Oct 2026.

### Step 0. Live spike via `/eg` (before any model change)

Goal: answer the two unknowns on a real client before writing the renderers:
1. Does Telegram accept `InputRichBlockButtons` **inside** `InputRichBlockDetails`?
2. How do disabled `None` / `success` / `danger` rows look?

Add a throw-away demo to `channels/telegram/rest_admin/scratchpad.py`. Later (step 6) the same demo renders the real `Receipt` so the
owner can step through every phase without a real order.

```python
# scratchpad.py — add to DEMOS (≈ line 46) and RICH-style dispatch in run_demo (≈ line 551)
DEMOS = (
    ...,
    ("🧾 Receipt phases", "rcpt_phases"),
)

def nested_rows_probe() -> InputRichMessage:
    """Spike: button rows inside a closed details block, plus the three disabled styles side by side."""
    row = lambda text, style=None: InputRichBlockButtons(buttons=[rich_action(text, style=style)])  # rich_action(no action) = disabled
    return InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="Spike · rows inside details", size=3),
        InputRichBlockDetails(summary="Progress · step 3 of 5", is_open=False, blocks=[
            row("✓ ✅ Accepted by Ada · 9:02 AM"), row("✓ ⏰ Pickup 9:41 AM"), row("● 🍳 Ready by Ada · 9:35 AM", "success"),
            row("🔒 🛵 Rider picks up · pending"), row("🔒 🏁 Delivered · pending"),
        ]),
        row("disabled · default style"), row("disabled · success", "success"), row("disabled · danger", "danger"),
        InputRichBlockParagraph(text=DEMO_NOTE),
    ])

# in run_demo:
    elif action == "rcpt_phases":
        await bot.send_rich_message(chat_id, rich_message=nested_rows_probe())
```

The scratchpad router already turns a `TelegramBadRequest` into "Telegram couldn't display this example here…", so a rejection is visible
in the chat. **Record the result in this file** and set `FLOW_ROWS_IN_DETAILS` (step 3) to match:

| Probe | Result (fill in) |
|---|---|
| Rows inside closed details accepted? | ☐ yes ☐ no (error text: …) |
| Disabled default / success / danger look | ☐ grey / dim green / dim red ☐ other: … |
| Same on iOS / Android / Desktop / Web | … |

### Step 1. SQL: three new fact keys in `t_receipt_snapshot`

File `ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql`, function `t_receipt_snapshot`. The change is additive and
`CREATE OR REPLACE`, with the same signature and grants.

```sql
DECLARE
    ...
    v_acc_by text;          -- restaurant_admin: who accepted (or set the pickup time); NULL for auto-accept
    v_acc_at timestamptz;   -- restaurant_update_dtts: overwritten by +10/+20, so only trusted while pickup_adjusted_at IS NULL
    v_adj_at timestamptz;   -- delivery only
    v_rcs text;             -- restaurant_confirmation_status ('auto_accept' -> accepted_auto)
BEGIN
    IF p_order_type = 'delivery' THEN
        SELECT
            s.rest_ref, s.rest_name, s.rest_confirmation_code, s.pickup_time, s.pickup_time_initial, s.pickup_adjusted_by,
            s.ready_at, s.ready_by, s.customer_address, s.customer_id,
            s.restaurant_admin, s.restaurant_update_dtts, s.pickup_adjusted_at, s.restaurant_confirmation_status   -- NEW
        INTO
            v_rest_ref, v_rest_name, v_code, v_pickup, v_initial, v_adj_by,
            v_ready_at, v_ready_by, v_cust_addr, v_cust_phone,
            v_acc_by, v_acc_at, v_adj_at, v_rcs                                                                       -- NEW
        FROM public.delivery_summary s
        WHERE s.order_number = p_order_number;
        ...
    ELSIF p_order_type = 'takeaway' THEN
        SELECT
            s.rest_ref, s.rest_name, s.rest_confirmation_code, s.pickup_time, s.ready_at, s.ready_by,
            s.restaurant_admin, s.restaurant_update_dtts, s.restaurant_confirmation_status                            -- NEW
        INTO
            v_rest_ref, v_rest_name, v_code, v_pickup, v_ready_at, v_ready_by,
            v_acc_by, v_acc_at, v_rcs                                                                                 -- NEW
        FROM public.takeaway_summary s
        WHERE s.order_number = p_order_number;
        ...

    -- in the 'facts' jsonb_build_object, after 'completed_at', v_completed:
            'accepted_by', CASE WHEN v_acc_by IS NULL THEN NULL
                           ELSE jsonb_build_object('label', public.restaurant_admin_label (v_acc_by), 'phone', v_acc_by) END,
            'accepted_at', CASE WHEN v_adj_at IS NULL THEN v_acc_at END,   -- +10/+20 overwrite restaurant_update_dtts (D58)
            'accepted_auto', COALESCE(v_rcs = 'auto_accept', false)
```

Also update the file header:
- `OBJECTS`: one line about the new keys.
- `HOW IT FITS`: a sentence on D58.
- `LIVE CHECK`: write "pending" until the owner applies it.

**Python never requires the keys** (step 2 defaults), so Python can deploy before the SQL. The SQL is also safe to apply first:
`from_json` ignores unknown keys.

SQL tests (append near ≈ line 450 of `tests/sql/test_restaurant_ready_adjust_notices_sql.py`):

```python
def test_receipt_snapshot_accepted_by_and_time(db):
    delivery(db)                         # helper inserts restaurant_admin = ADA, restaurant_confirmation_status 'restaurant_accept'
    db.execute("UPDATE public.delivery_summary SET restaurant_update_dtts = now() - interval '5 minutes' WHERE order_number = %s", (ORDER,))
    link(db)                             # Ada's invite gives the label 'Ada'
    did = rider(db)
    f = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', %s)", (BOT, ORDER, did))["facts"]
    assert f["accepted_by"] == {"label": "Ada", "phone": ADA}
    assert f["accepted_at"] is not None and f["accepted_auto"] is False


def test_receipt_snapshot_accepted_at_is_null_once_the_pickup_was_moved(db):
    delivery(db)
    did = rider(db)
    adjust(db, "(SELECT pickup_time + interval '10 minutes' FROM public.delivery_summary)", phone=BOB)
    f = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', %s)", (BOT, ORDER, did))["facts"]
    assert f["accepted_at"] is None                       # restaurant_update_dtts now holds the adjust time
    assert f["accepted_by"]["phone"] == ADA               # adjust keeps restaurant_admin (test_adjust_keeps_restaurant_admin_…)


def test_receipt_snapshot_auto_accept_and_takeaway(db):
    delivery(db, restaurant_confirmation_status="auto_accept", restaurant_admin=None)
    f = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'delivery', NULL)", (BOT, ORDER))["facts"]
    assert f["accepted_auto"] is True and f["accepted_by"] is None
    takeaway(db)
    t = fetch_one(db, "SELECT public.t_receipt_snapshot(%s, %s, 'takeaway', NULL)", (BOT, TAKE))["facts"]
    assert t["accepted_by"]["phone"] == ADA and t["accepted_auto"] is False
```

Also extend the existing `test_receipt_snapshot_fields_and_reply_to` with `assert "accepted_by" in f`.

### Step 2. Python facts (`receipts/model.py`)

```python
@dataclass(frozen=True)
class ReceiptFacts:
    ...                                   # existing fields unchanged, in the same order
    completed_at: datetime | None
    # D58: who accepted, and when. Defaults keep older snapshots (SQL not yet applied) working.
    accepted_by: Actor | None = None
    accepted_at: datetime | None = None
    accepted_auto: bool = False
```

In `ReceiptSnapshot.from_json` (≈ line 112), after `completed_at=...`:

```python
            accepted_by=_actor(f.get("accepted_by")),
            accepted_at=_when(f.get("accepted_at")),
            accepted_auto=bool(f.get("accepted_auto")),
```

### Step 3. Phase and timeline (`receipts/model.py`)

New module-level names (near the constants, ≈ line 41). Add `"Step"` and `"Phase"` to the docstring's Classes list.

```python
Phase = Literal["kitchen", "handed_over"]
StepState = Literal["done", "latest", "todo", "failed"]
HANDED_OVER_KINDS: frozenset[str] = frozenset({"picked_up", "done"})   # D55
STEP_STYLES: dict[str, str | None] = {"done": None, "latest": "success", "todo": None, "failed": "danger"}  # D56
STEP_MARKS = {"done": "✓ ", "latest": "● ", "todo": "🔒 ", "failed": ""}
ORDER_DETAILS = "🔵 Order details · tap to expand"
FLOW_ROWS_IN_DETAILS = True   # D57: set from the step-0 spike; False = text lines inside the closed Progress block


@dataclass(frozen=True)
class Step:
    """One row of the progress flow. `label` is plain text; the HTML renderer escapes it."""

    label: str
    state: StepState
    at: datetime | None = None

    def text(self) -> str:
        """'✓ ✅ Accepted by Ada · 9:02 AM' | '● 🍳 Ready by You · 9:35 AM' | '🔒 🛵 Rider picks up · pending'."""
        tail = " · pending" if self.state == "todo" else (f" · {fmt_uk_time(self.at)}" if self.at else "")
        return f"{STEP_MARKS[self.state]}{self.label}{tail}"
```

Methods on `Receipt` (new section after `_keyboard`, replacing `_stages` / `_stage_index` / `_flow` / `_when_line`):

```python
    # ---- the two decisions every renderer reads ----------------------------------------------------------------------
    @property
    def phase(self) -> Phase:
        """'handed_over' once the food has left the kitchen (D55); the full kitchen layout otherwise."""
        return "handed_over" if self.kind in HANDED_OVER_KINDS else "kitchen"

    def _accepted_label(self, viewer: Viewer) -> str:
        f = self.facts
        if f.accepted_auto:
            return "✅ Accepted automatically"
        if f.accepted_by is not None:
            return f"✅ Accepted by {self._who_plain(f.accepted_by, viewer)}"
        return "✅ Accepted"            # SQL not applied yet, or an auto-accepted order whose pickup was moved

    def _reached(self, total: int) -> int:
        """How many steps have happened, from the status key alone (the database decides the key)."""
        match self.kind:
            case "open":
                return 2                                    # accepted + pickup time set
            case "ready":
                return 3
            case "picked_up":
                return 4
            case "done":
                return total
            case "rider_cancelled":
                return 3 if self.facts.ready_at else 2
            case _:
                return 0                                    # 'gone' never reaches the renderers

    def timeline(self, viewer: Viewer) -> tuple[Step, ...]:
        """Every step, in order: done (✓ grey), latest (green), still to come (🔒 grey); a cancelled rider ends it in red."""
        f = self.facts
        rider = f.rider_name or f.rider_id
        ready_by = f" by {self._who_plain(f.ready_by, viewer)}" if f.ready_by else ""
        pickup = (f"⏰ Pickup {fmt_uk_time(f.pickup_at)}{self._moved(viewer, self._who_plain)}"
                  if f.pickup_at else "⏰ Pickup time")
        # (label once it has happened, label while still to come, when it happened)
        rows: list[tuple[str, str, datetime | None]] = [
            (self._accepted_label(viewer), "✅ Accepted", f.accepted_at),
            (pickup, pickup, None),
            (f"🍳 Ready{ready_by}" if f.ready_at else "🍳 Ready (not marked)", "🍳 Food ready", f.ready_at),
        ]
        if f.order_type == "delivery":
            rows.append((f"🛵 Picked up by {rider}" if rider else "🛵 Picked up", "🛵 Rider picks up", None))
            rows.append(("🏁 Delivered", "🏁 Delivered", f.completed_at))
        else:
            rows.append(("🏁 Collected", "🏁 Collected", f.completed_at))
        reached, cancelled = self._reached(len(rows)), self.kind == "rider_cancelled"
        steps: list[Step] = []
        for i, (done, todo, at) in enumerate(rows):
            if i < reached:
                steps.append(Step(done, "latest" if i == reached - 1 and not cancelled else "done", at))
            elif not cancelled:
                steps.append(Step(todo, "todo"))
        if cancelled:
            steps.append(Step("⚠️ This rider is no longer on the job", "failed"))
        return tuple(steps)

    def _progress_summary(self, steps: tuple[Step, ...]) -> str:
        if any(s.state == "failed" for s in steps):
            return "Progress · rider no longer on the job"
        happened = sum(s.state in ("done", "latest") for s in steps)
        return f"Progress · step {happened} of {len(steps)}"
```

Notes:
- "Ready (not marked)" appears only when the order moved past Ready without anyone tapping Ready (a WhatsApp-only kitchen, or the
  rider picked up first). It is honest about what the database recorded.
- A delivery has 5 steps and a takeaway 4. The old `Progress · step 4 of 4` for a delivered order becomes `step 5 of 5`.
- `rider_cancelled` now **has** a flow (previously `_flow()` returned None). The old test asserting "no flow once the rider is off"
  changes (step 6).

### Step 4. Rich renderer (`receipts/model.py`, replaces `_rich`, ≈ lines 380–440)

Split today's `_rich` into pieces without changing the kitchen order of blocks (heading, number, badge, pickup, Progress, code, rider,
items, money, pay, notes, customer, actions), then add the handed-over arrangement.

```python
    def _flow_rows(self, steps: tuple[Step, ...]) -> list[InputRichBlockButtons]:
        """One disabled button per step (D56). Disabled: the flow is a picture, never an action."""
        return [
            InputRichBlockButtons(buttons=[
                RichMessageButton(text=s.text(), style=STEP_STYLES[s.state], disabled=DisabledButton())
            ])
            for s in steps
        ]

    def _progress(self, viewer: Viewer) -> InputRichBlockDetails | None:
        """Kitchen phase: the flow inside a closed native block (D57)."""
        steps = self.timeline(viewer)
        if not steps:
            return None
        inner = (self._flow_rows(steps) if FLOW_ROWS_IN_DETAILS
                 else [InputRichBlockParagraph(text=s.text()) for s in steps])
        return InputRichBlockDetails(summary=self._progress_summary(steps), is_open=False, blocks=inner)

    def _rich_head(self, viewer: Viewer) -> list:
        f = self.facts
        kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
        return [
            InputRichBlockSectionHeading(text=f"🧾 Kitchen receipt · {kind}", size=3),
            InputRichBlockParagraph(text=RichTextBold(text=f.order_number)),
            InputRichBlockButtons(buttons=[self._badge(viewer)]),
        ]

    def _rich_pickup(self, viewer: Viewer) -> InputRichBlockParagraph:
        f = self.facts
        if f.pickup_at is None:
            return InputRichBlockParagraph(text="⏰ Pickup: —")
        return InputRichBlockParagraph(text=[
            "⏰ Pickup: ", RichTextBold(text=fmt_uk_time(f.pickup_at)), self._moved(viewer, self._who_plain),
        ])

    def _rich_code(self) -> InputRichBlockParagraph:
        code = self.facts.rest_code
        return InputRichBlockParagraph(text=f"🔑 Restaurant code: {code if code is not None else '—'}")

    def _rich_rider(self) -> InputRichBlockParagraph | None:
        f = self.facts
        if f.order_type != "delivery" or not (f.rider_name or f.rider_id):
            return None
        who = f.rider_name or f.rider_id or ""
        return InputRichBlockParagraph(text=f"🛵 Rider: {who}" + (f" — {f.rider_id}" if f.rider_name and f.rider_id else ""))

    def _rich_order(self, shown: int) -> list:
        """Items, money, pay line, notes, customer: today's code moved here unchanged (≈ lines 410–437)."""
        f = self.facts
        blocks: list = [InputRichBlockParagraph(text=RichTextBold(text="Items"))]
        for item in f.items[:shown]:
            lines = [f"• {_qty(item.qty)} × {item.name} — {_money(item.line_total)}"]
            lines += [f"   ↳ {m}" for m in item.mods]
            blocks.append(InputRichBlockParagraph(text="\n".join(lines)))
        if not f.items[:shown]:
            blocks.append(InputRichBlockParagraph(text="—"))
        if shown < len(f.items):
            blocks.append(InputRichBlockParagraph(text=f"… and {len(f.items) - shown} more items (see WhatsApp/printer)"))
        fee = f"Small order fee: {_money(f.small_order_fee)}\n" if f.small_order_fee else ""
        blocks.append(InputRichBlockParagraph(text=[fee, RichTextBold(text=f"Total: {_money(f.total)}")]))
        if f.pay_at_restaurant:
            blocks.append(InputRichBlockParagraph(text=RichTextBold(text=f"💷 Pay at restaurant — collect {_money(f.total)}")))
        if f.notes and f.notes.strip():
            note = f.notes.strip()
            note = note[:NOTES_LIMIT] + "…" if len(note) > NOTES_LIMIT else note
            blocks.append(InputRichBlockParagraph(text=[RichTextBold(text="📝 Notes"), "\n", RichTextItalic(text=note)]))
        if f.order_type == "delivery" and (f.customer_address or f.customer_phone):
            blocks.append(InputRichBlockParagraph(
                text="🏠 Customer: " + " — ".join(b for b in (f.customer_address, f.customer_phone) if b)
            ))
        return blocks

    def _rich(self, viewer: Viewer, shown: int) -> InputRichMessage:
        blocks = self._rich_head(viewer)
        rider = self._rich_rider()
        if self.phase == "handed_over":                        # D55/D59: what happened on top, the order folded away
            blocks += self._flow_rows(self.timeline(viewer))
            if rider is not None:
                blocks.append(rider)
            blocks.append(InputRichBlockDetails(summary=ORDER_DETAILS, is_open=False, blocks=[
                self._rich_pickup(viewer), self._rich_code(), *self._rich_order(shown),
            ]))
        else:                                                   # kitchen: today's layout, flow in the closed Progress block
            blocks.append(self._rich_pickup(viewer))
            if (progress := self._progress(viewer)) is not None:
                blocks.append(progress)
            blocks.append(self._rich_code())
            if rider is not None:
                blocks.append(rider)
            blocks += self._rich_order(shown)
        blocks += self._rich_actions()                          # empty after handover: _actions() offers nothing then
        return InputRichMessage(blocks=blocks)
```

Also:
- **Delete** `_when_line`, `_stages`, `_stage_index` and `_flow` (D61).
- **Remove** `RichTextDateTime` from the aiogram import (ruff F401).
- Update the module docstring: "Two forms … a status badge, a progress flow (closed while cooking, open after handover) …; after
  handover the order itself folds into a closed Order details block (plans/telegram-receipt-phases-plan.md)".

### Step 5. HTML renderer (`receipts/model.py`, `_head` / `_fit`, ≈ lines 224–275)

Keep `_head(viewer)` for the kitchen phase (title, number, status line, code, pickup, rider). Add small pieces for the handed-over phase
and branch inside `build(n)` so the 4000-character cut covers both layouts.

```python
    def _title_lines(self, viewer: Viewer) -> list[str]:
        f = self.facts
        kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
        lines = [f"🧾 KITCHEN RECEIPT · {kind}", f"<b>{escape(f.order_number)}</b>"]
        if status := self._status_line(viewer):
            lines.append(status)
        return lines

    def _code_line(self) -> str:
        code = self.facts.rest_code
        return f"🔑 Restaurant code: <b>{code if code is not None else '—'}</b>"

    def _rider_line(self) -> str | None:
        f = self.facts
        if f.order_type != "delivery" or not (f.rider_name or f.rider_id):
            return None
        who = escape(f.rider_name or f.rider_id or "")
        return f"🛵 Rider: {who}" + (f" — {escape(f.rider_id)}" if f.rider_name and f.rider_id else "")

    def _head(self, viewer: Viewer) -> str:             # kitchen phase, same text as today
        lines = self._title_lines(viewer) + [self._code_line(), self._pickup_line(viewer)]
        if rider := self._rider_line():
            lines.append(rider)
        return "\n".join(lines)

    @staticmethod
    def _flow_html(steps: tuple[Step, ...]) -> str:
        return "\n".join(f"<b>{escape(s.text())}</b>" if s.state in ("latest", "failed") else escape(s.text()) for s in steps)

    def _fit(self, viewer: Viewer) -> tuple[str, int]:
        """The HTML text, and how many items it shows. The rich form shows the same items."""
        tail = self._tail()
        blocks = [self._item_block(i) for i in self.facts.items]
        steps = self.timeline(viewer)
        handed_over = self.phase == "handed_over"
        if handed_over:
            rider = self._rider_line()
            top = "\n".join(self._title_lines(viewer)) + "\n\n" + self._flow_html(steps) + (f"\n{rider}" if rider else "")
            folded = f"{self._code_line()}\n{self._pickup_line(viewer)}"
        else:
            head = self._head(viewer)
            progress = (f"<blockquote expandable><b>{escape(self._progress_summary(steps))}</b>\n"
                        f"{self._flow_html(steps)}</blockquote>") if steps else ""

        def build(n: int) -> str:
            shown = blocks[:n]
            if n < len(blocks):
                shown.append(f"… and {len(blocks) - n} more items (see WhatsApp/printer)")
            items = "<b>Items</b>\n" + ("\n".join(shown) if shown else "—")
            if handed_over:     # D59/D60: Order details folded into an expandable quote
                return (f"{top}\n\n<blockquote expandable><b>{ORDER_DETAILS}</b>\n"
                        f"{folded}\n\n{items}\n\n{tail}</blockquote>")
            return "\n\n".join(p for p in (head, progress, items, tail) if p)

        for n in range(len(blocks), -1, -1):
            text = build(n)
            if len(text) <= TEXT_LIMIT:
                return text, n
        return text, 0
```

Check for the implementer: `_tail()` has no blockquote, so nothing nests. Telegram HTML does not allow a blockquote inside a blockquote.

### Step 6. `/eg` demo of the real receipt (`scratchpad.py`)

Replace the step-0 probe body with the real model so the owner can see every phase, rich and HTML, without placing orders:

```python
RECEIPT_PHASES = ("open@13:00", "ready@13:00", "picked_up", "done", "rider_cancelled")

def demo_receipt(index: int) -> InputRichMessage:
    """The real Receipt.view() for a fake order in one of five states, plus a 'Next state' control (Demo callbacks only)."""
    from datetime import datetime, timedelta, timezone
    from .receipts.model import Receipt, ReceiptSnapshot
    from .order_cards.model import Viewer

    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda m: (now + timedelta(minutes=m)).isoformat()
    ada = {"label": "Ada", "phone": "447700900001"}
    status = RECEIPT_PHASES[index % len(RECEIPT_PHASES)]
    facts = {
        "order_number": "DEMO-PHASE-1", "order_type": "delivery", "rest_name": "Demo", "rest_code": 47,
        "pickup_at": iso(10), "pickup_initial": iso(0), "pickup_adjusted_by": ada,
        "ready_at": iso(-2) if status != "open@13:00" else None, "ready_by": ada if status != "open@13:00" else None,
        "rider": {"id": "447700900123", "name": "Demo Rider"},
        "customer": {"address": "1 Demo Street, Salisbury SP1 3TA", "phone": "447700900999"},
        "items": [{"qty": 2, "name": "Chicken Shawarma", "line_total": 17.0, "mods": ["extra garlic sauce"]},
                  {"qty": 1, "name": "Fries", "line_total": 3.5, "mods": []}],
        "small_order_fee": 1.0, "total": 21.5, "notes": "Please ring the bell twice (demo)", "pay_at_restaurant": False,
        "completed_at": iso(25) if status == "done" else None,
        "accepted_by": ada, "accepted_at": iso(-20), "accepted_auto": False,
    }
    snap = ReceiptSnapshot.from_json({"status": status, "rest_ref": "DEMO", "dispatch_id": 1, "facts": facts})
    rich = Receipt.from_snapshot(snap).view(Viewer("447700900001")).rich
    nav = InputRichBlockButtons(buttons=[rich_action(f"Next state → ({status})", "rp_next", index + 1, "primary")])
    return InputRichMessage(blocks=[*rich.blocks, nav, InputRichBlockParagraph(text=DEMO_NOTE)])
```

- Dispatch in `run_demo`: `rcpt_phases` sends `demo_receipt(0)`; `rp_next` edits the message to `demo_receipt(demo.value)`, using
  `edit_demo(query, rich_message=…)`. It is stateless, because the index is in the callback.
- **Known limitation:** the real `Ready` / `+10` / `+20` / badge buttons inside the demo carry `OrderAction` data for `DEMO-PHASE-1`.
  Tapping them reaches the real orders router, which answers "This order is no longer available." and changes nothing. That's
  acceptable for a demo; say so in the demo note.
- Add `rp_` to the `run_demo` routing and a `tests/channels/telegram/test_scratchpad.py` case: every phase renders, and `rp_next` wraps around.

### Step 7. Tests (`tests/channels/telegram/test_receipt_model.py`, `test_receipts.py`)

**Existing tests that must change** (behaviour changed on purpose):

| Test | Change |
|---|---|
| `test_open_delivery_has_everything_the_kitchen_needs` | `assert "✅" not in t` no longer holds, because the Progress quote contains "✅ Accepted". Assert instead that no status line is in the head: `t.splitlines()[2].startswith("🔑")`. |
| `test_flow_is_a_closed_native_block_marking_done_now_and_to_come` | Rewrite for the 5/4 steps, button rows, the new summary and the rider-cancelled flow (below). |
| `test_relative_time_under_the_badge_only_once_something_has_happened` | Replace with `test_no_relative_time_anywhere` (below). |
| `test_rich_buttons_are_the_html_buttons_plus_the_badge` | Flow rows are disabled buttons, so `rich_buttons_of` now returns them too. The test filters on `"callback_data" in b` already. Check that it still passes, and do not loosen it. |
| `test_closed_states_have_no_buttons` / `test_the_rich_form_shows_the_same_items_and_the_same_cut_as_the_html` | Should still pass. Add a `picked_up` / `done` variant to the cut test (the cut must hold inside the blockquote). |
| `test_receipts.py` assertions on `picked_up` / `done` text | `text_of()` flattens details, so most still pass. Fix any that assert block order. |

**New tests** (pure, `test_receipt_model.py`). The `snap()` helper takes extra facts as kwargs, so `accepted_by=ADA` works unchanged.

```python
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
        ("✓ ✅ Accepted by Ada · 11:40 AM", "done"),          # Viewer 002 is not Ada, so never "You"
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
    assert steps_of()[0][0] == "✓ ✅ Accepted"                         # snapshot from the old SQL: no accepted keys
    assert steps_of(viewer=Viewer("447700900001"), **ACCEPTED)[0][0].startswith("✓ ✅ Accepted by You")
    assert steps_of(viewer=Viewer(None, shared=True), **ACCEPTED)[0][0].startswith("✓ ✅ Accepted by Ada")


def test_timeline_ready_not_marked_when_the_order_moved_past_it():
    assert steps_of("picked_up")[2] == ("✓ 🍳 Ready (not marked)", "done")


def test_handed_over_rich_layout_folds_the_order_away():
    v = view("done", **DONE_AT, **ACCEPTED, **READY_AT)
    top = rich_blocks(v)
    assert [b["type"] for b in top] == ["section_heading", "paragraph", "buttons", *["buttons"] * 5, "paragraph", "details"]
    assert top[-1]["summary"] == "🔵 Order details · tap to expand" and top[-1]["is_open"] is False
    text = rich_text(v.rich)                      # rich_view._walk flattens the details block after its summary line
    above, folded = text.split("🔵 Order details · tap to expand", 1)
    for part in ("⏰ Pickup:", "🔑 Restaurant code", "Items", "Total: £21.50", "📝 Notes", "🏠 Customer"):
        assert part in folded and part not in above, part
    assert "🛵 Rider: Sam — RIDER01" in above and "[● 🏁 Delivered · 12:25 PM]" in above


def test_flow_rows_are_disabled_and_coloured_by_state():
    rows = [b for b in rich_buttons_of(view("picked_up", **ACCEPTED, **READY_AT).rich)][1:]   # [0] is the badge
    assert all("disabled" in b and "callback_data" not in b for b in rows)
    assert [b.get("style") for b in rows] == [None, None, None, "success", None]
    cancelled = rich_buttons_of(view("rider_cancelled", **READY_AT).rich)
    assert any(b.get("style") == "danger" for b in cancelled)


def test_kitchen_flow_is_inside_the_closed_progress_block():
    flow = next(b for b in rich_blocks(view("ready@13:00", **ACCEPTED, **READY_AT)) if b["type"] == "details")
    assert flow["summary"] == "Progress · step 3 of 5" and flow["is_open"] is False
    assert all(b["type"] == ("buttons" if FLOW_ROWS_IN_DETAILS else "paragraph") for b in flow["blocks"])


def test_handed_over_html_folds_the_order_into_an_expandable_quote():
    t = view("done", **DONE_AT, **ACCEPTED).text
    cut = t.index("<blockquote expandable><b>🔵 Order details · tap to expand</b>")
    above, folded = t[:cut], t[cut:]
    assert "<b>● 🏁 Delivered · 12:25 PM</b>" in above and "🛵 Rider: Sam" in above
    for part in ("🔑 Restaurant code", "⏰ Pickup", "<b>Items</b>", "Total: £21.50", "📝 <b>Notes</b>", "🏠 Customer"):
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
        for s in r.timeline(Viewer("447700900001")):
            assert s.text() in rich_text(v.rich) and escape(s.text()) in v.text, (status, s)


def test_no_relative_time_anywhere():
    for status in ("open@13:00", "ready@13:00", "done"):
        assert '"date_time"' not in view(status, **READY_AT).rich.model_dump_json()


def test_flow_text_is_escaped_in_html_only():
    v = view("picked_up", rider={"id": "R1", "name": "<b>Sam</b> & co"})
    assert "Picked up by &lt;b&gt;Sam&lt;/b&gt; &amp; co" in v.text and "Picked up by <b>Sam</b> & co" in rich_text(v.rich)


def test_huge_handed_over_order_still_fits_and_matches():
    items = [{"qty": 1, "name": f"Dish {i} " + "x" * 60, "line_total": 1.5, "mods": ["m" * 40]} for i in range(120)]
    v = view("done", items=items, notes="n" * 5000)
    assert len(v.text) <= TEXT_LIMIT and v.text.count("• ") == rich_text(v.rich).count("• ") < 120
```

(Imports to add to the test file: `from html import escape` and `FLOW_ROWS_IN_DETAILS` from the model. `rich_view.rich_text` already
flattens a details block as its summary line followed by its contents, and buttons as `[text]`, so no helper change is needed.)

**Dispatcher level** (`test_receipts.py`): one test. A WhatsApp-side status change from `ready@…` to `picked_up` (via `FakeReceiptStore`
returning the new snapshot, then `Receipts.refresh`) edits the copy **as rich**. The edit contains the `Order details` details block,
and the `Ready` / `+10` / `+20` callbacks are gone (`button_data_of(edit) == [badge 'st' only]`).

### Step 8. Docs

- `docs/telegram-layer.md` (§3 file map line for `receipts/model.py`, §5/§6 receipt text) and `docs/telegram-layer.html`: describe the
  phase rule, the flow and Order details. Add a change-log line dated the day it ships.
- `restaurant_ready_adjust_notices.sql` header (step 1).
- This plan: fill in the step-0 table and an "As built" section, the same way as `telegram-phase-7-8-kitchen-actions-and-notices.md`.

## 6. Verification (per `.claude/skills/telegram-vertification-loop`)

Environment (Linux VM, the repo `.venv` is macOS-only):

```bash
# once per session (/tmp may be wiped)
UV_CACHE_DIR=/tmp/uvcache UV_PYTHON_INSTALL_DIR=/tmp/uvpy UV_PROJECT_ENVIRONMENT=/tmp/venv313 \
  uv sync --frozen --no-install-project --python 3.13 && /tmp/venv313/bin/python -m pip install ruff  # or: uv pip install ruff
cd ~/mnt/OrdeloAgent && export PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1
/tmp/venv313/bin/python -m pytest tests/channels/telegram -q -p no:cacheprovider          # baseline before: 410 passed
/tmp/venv313/bin/python -m ruff check channels/telegram tests/channels/telegram
/tmp/venv313/bin/python -m pytest -q -p no:cacheprovider                                   # full suite
```

Known pre-existing failure, not ours:
`tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`.
Repo-wide ruff has ~192 old errors. Only the changed files must be clean.

**Mutation checks** (break each on purpose, confirm the named test fails, restore byte-identical):
1. `phase` always returns `"kitchen"` → `test_phase_follows_the_status_key`, `test_handed_over_*` fail.
2. In `timeline`, swap `"latest"` and `"done"` → `test_timeline_*`, `test_flow_rows_are_disabled_and_coloured_by_state` fail.
3. In `_flow_rows`, give rows `callback_data=OrderAction(..., a="st").pack()` instead of `disabled` → the disabled-rows test fails.
4. In `_flow_html`, drop `escape` → `test_flow_text_is_escaped_in_html_only` fails.
5. In SQL, return `v_acc_at` unconditionally → `test_receipt_snapshot_accepted_at_is_null_once_the_pickup_was_moved` fails (isolated DB only).

**Evidence labels:** offline (pytest), isolated database (SQL tests with `ORDELO_TEST_DB_URI`), live Telegram (the step-0 spike, then
`/eg → 🧾 Receipt phases` through all five states on the owner's phone, then one real `STRK-TEST` order taken to delivered). Do not
claim live rendering from offline tests.

## 7. Deploy

- No new callbacks for real orders (flow rows are disabled). The only new callback is the scratchpad's `rp_next`. A rolling deploy is safe.
- SQL and Python are independent in both orders (step 1 note). The owner applies the SQL file in the Supabase SQL editor as usual (whole
  file, idempotent). The database-operations skill: preparing SQL does not authorise running it.
- Receipts already sent switch layout at their next status change, because `refresh` redraws from the snapshot. An HTML-only copy (sent
  before the rich change) stays HTML: `TelegramIO.edit` tries rich, and on rejection edits HTML.

## 8. Out of scope

Group chats (not implemented, see `claude/telegram-group-chats-status.md`), seen-state, takeaway `completed` being set (nothing sets it yet,
`takeaway_summary.sql` GOTCHAS), WhatsApp receipt layout.

## 9. Later: the rider-location button (D62, notes only)

What exists (verified 23 Oct 2026):
- **`ordelo/wa_location.py` → `WaLocation.request(demand: WaLocationDemand, *, schedule=None) -> WaLocationRequestOutcome`.**
  - It validates the requester and persists `wa_location_request`.
  - It returns a fresh (≤ `FRESHNESS` = 5 min) observation, or prompts the rider through their channel. WhatsApp uses
    `request_location`; Telegram uses `ordelo/rider_messaging/telegram.py::request_location` → `channels/telegram/keyboards.py::location_request_kb`.
  - The rider's reply arrives through `channels/telegram/rider/location.py` (Telegram) or `watomation/on_wa_location_handler.py` (WhatsApp).
- **`WaLocationDemand` (`ordelo_datamodels/wa_location_pymodels.py`):** `rest_ref`, `order_number`,
  `location_requested_by: Literal["customer", "restaurant_admin"]`, `requester_id` (an admin phone that must be in
  `restaurant_master.admins`), `callback_url` (**public HTTPS**, validated and DNS-checked) and `idempotency_key`.
- **Rules (`_validate_demand`):** a restaurant admin may ask while the dispatch is `assigned` or `pickedup`, so also **before** pickup.
- **The answer** is delivered only by `route_fulfilled_request()` as an HTTP POST of `WaLocationCallbackPayload` (lat/lon, source,
  observed_at) to `callback_url`. The public HTTP entry is `watomation/routers/wa_location_hooks.py` (`POST /wa-request-location`).

What is missing for Telegram:
- A `"loc"` `OrderAction` (add it to `callbacks.py`'s `Literal`, and route it in `rest_admin/orders.py` next to `rdy` / `adj` / `st`).
- `Receipts.tap` calling `WaLocation.request(...)`, with `requester_id` = the tapper's phone (`TelegramActor` → phone).
- A receiving endpoint such as `POST /telegram/rest-admin/rider-location`, given as `callback_url`, that posts the result into the
  requesting chat. Either a reply with `send_location`, or an `InputRichBlockMap(location=…, zoom=15)` shown in the receipt with
  "observed HH:MM". Mind `plans/ordelo-agg-plan-cc.md` F10: never expose the rider location via a readable order number.
- In the model: the button belongs under the rider line (D59), shown while `kind in {"ready", "picked_up"}` or per a new decision.

## 10. Open risks and follow-ups

- **Buttons inside details** may be rejected (step 0). Then `FLOW_ROWS_IN_DETAILS = False` and the kitchen phase shows text lines.
- **Dim green.** Disabled `success` rows render dim. If the owner wants bright green for the latest step, make **only that row** tappable
  with the existing `st` callback (redraw from the database). Bright green follows, and there is still no new action. Not planned; ask first.
- **Badge and latest row say the same thing** after handover. That's acceptable: the badge is the at-a-glance line, and the flow is the history.
  Revisit after the live look.
- **"Accepted by"** names whoever set the pickup time, and its time is lost after +10/+20 (§3). That's honest but imperfect. A real
  `accepted_at` / `accepted_by` column would need a schema change, which D58 declined.
- **Picked-up time** is not shown (D58). Adding it needs `picked_up_at` written in the rider pickup-code path.


---

## As built (23 October 2026)

Implemented as planned, with these differences and results:

- **Step 0 (live spike):** NOT answered. Telegram Web (logged in) showed no reply to `/eg`, so the owner's local backend was not running
  (or its webhook points elsewhere). `FLOW_ROWS_IN_DETAILS` stays `True` (rows inside the closed Progress block). If Telegram rejects
  it, TelegramIO falls back to the HTML form automatically (BadRequest). To answer: start the backend, send `/eg`, tap **🧪 Rows in
  details**, then **🧾 Receipt phases**, and record: rows-in-details accepted ☐, disabled default/success/danger look ☐.
  Note from the web screenshot: Telegram Web renders the old relative time ("Delivered 1 hour ago"); the phone did not.
- **`/eg`:** two entries (33 demos): **🧾 Receipt phases** (the real `Receipt.view()` for five states, `rp_next` steps through them,
  stateless) and **🧪 Rows in details** (the probe).
- **Tests:** Telegram suite 410 → 435. New: phase, timeline (open, done, rider cancelled, takeaway, accepted variants, ready-not-marked),
  handed-over rich and HTML layouts, flow rows disabled and coloured, rich/HTML same steps, no relative time, escaping, huge order,
  dispatcher-level pickup redraw, demo. Three SQL tests added to `tests/sql/test_restaurant_ready_adjust_notices_sql.py`
  (**written, NOT run**: no Postgres on the build VM; run with `ORDELO_TEST_DB_URI=... pytest tests/sql -q`).
- **Mutation checks:** phase always kitchen; swap latest/done; flow rows tappable; HTML flow unescaped. Each was caught by the intended tests.
- **Database guide:** the SQL header change made `ordelo_datamodels/catalog.json` and `ordelo-database-guide.html` stale; regenerated
  with `python scripts/datamodels/build_guide.py`.
- **Full suite:** 1631 passed; 1 failure not ours (`test_restaurant_master_get_admins_fetches_live_column`, fails on a clean checkout).
- **Owner to do:** apply the SQL file (read-only, idempotent), register nothing new, then do the live check above.
