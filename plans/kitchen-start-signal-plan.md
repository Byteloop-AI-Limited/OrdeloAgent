# Plan: hold the kitchen until a rider accepts, then say "start preparing"

Status: **planned, not started** (17 Nov 2026). The owner answered eight grilling questions (decisions D1 to D8 below).
Repo: OrdeloAgent (one doc line in restaurant-frontend). **No SQL, no migration, no config key.**

## 1. The problem

For a delivery, the kitchen should cook only once a rider has accepted the job. Today, though, the two messages an admin sees
read as "accepted, go", and nothing tells the kitchen to wait:

| Message | Today (Telegram, screenshots of STRK-FPBH-33) | Built in |
|---|---|---|
| Order card after the pickup time is set | `✅ You accepted · pickup 11:14 PM` + order body | `channels/telegram/rest_admin/order_cards/model.py` `Card._status_line` (line 278, cases `pickup_set` 293 / `auto_accepted` 297), `Card.view` (333) |
| Kitchen receipt, first send (rider accepted) | `🧾 Kitchen receipt · 🚚 Delivery`, number, badge `📋 Preparing · pickup …` | `channels/telegram/rest_admin/receipts/model.py` `_title_lines` (255), `_rich_head` (502), `_badge_text` (439) |
| WhatsApp reply after the pickup time is chosen | `Pickup time updated` | `watomation/on_callback_wa_handler.py:290` |
| WhatsApp kitchen receipt | header `Order #… (Kitchen)` | `utils_common/waba_utils/wa_senders.py` `admin_order_reciept` (232; header/text at 295-296), `takeaway_admin_order_receipt` (320; 351-352) |
| Auto-accept notice (timeout) | `… auto-accepted … Pickup 11:14 PM` | WhatsApp `wa_senders.admin_auto_accept_notice` (154); Telegram `utils_common/notify/restaurant_notifier.py:272-280` |
| No rider found | restaurant admins get nothing (commented out); overwatch only | `watomation/routers/delivery_hooks.py:849-861` |

The new wording also opens a gap. Once the card says "wait for the kitchen receipt", a delivery with no rider would leave
the kitchen waiting for a receipt that never comes, because the No-rider admin notice is commented out.

## 2. Decisions (owner, 17 Nov 2026)

| # | Question | Decision |
|---|---|---|
| D1 | Channels | **Telegram and WhatsApp**, with the wording kept in one shared module |
| D2 | No rider found | **Turn the restaurant notice back on**, reworded so it says the order is cancelled and must not be prepared. Sent as a reply to the card, on both channels. The overwatch alert stays |
| D3 | Configured auto-accept restaurants | **Every delivery is treated the same**: they get the hold wording and the No-rider notice too, and the `configured_auto` skip goes |
| D4 | Order card after a rider accepts | **The card is left as it is** (it stays terminal, no SQL). The receipt threaded under it carries the "start" |
| D5 | Where "start" sits on the receipt | **The first line is the call to action** while the receipt is `open`. After Ready it goes back to today's heading |
| D6 | Takeaway | **Takeaway is never held.** Its receipt uses the same headline, worded for collection |
| D7 | New rider after a cancellation | **Same wording** ("Please start preparing now"), with no re-dispatch flag |
| D8 | Wording | Approved as below |

### Approved wording (D8)

```
HOLD   (delivery card after pickup_set / auto_accepted, WhatsApp pickup reply, auto-accept notice on both channels)
       ⏳ Don't start cooking yet — we're finding a rider.
       Start when the kitchen receipt arrives.

START  (kitchen receipt while 'open'; WhatsApp receipt header + first body line)
       delivery:  🍳 Please start preparing now
                  Rider found · ready for pickup at 11:14 PM
       takeaway:  🍳 Please start preparing now
                  Ready for collection at 11:14 PM

DROP   (No-rider notice, reply to the card, both channels)
       ❌ No rider found for STRK-FPBH-33.
       The order is cancelled — please don't prepare it.
```

## 3. Design: one module decides what the kitchen is told

**Today.** The rule "a delivery waits for a rider, a takeaway doesn't" has no home, and adding these three messages
directly would spread both the rule and the wording across nine call sites in four files on two channels: the card model,
the receipt model (HTML and rich forms), the notifier's Telegram adapter, `wa_senders` (four senders) and the WhatsApp
callback handler. The two channels would drift, as the auto-accept and no-rider texts already have.

**The change.** Add a new **module** `utils_common/order_management/kitchen_instructions.py`. Its **interface** is three
pure functions that return plain text:

```python
OrderType = Literal["delivery", "takeaway"]

@dataclass(frozen=True)
class KitchenInstruction:
    headline: str   # the line that must catch the eye; channels make it bold / a heading
    detail: str     # the line under it

def hold(order_type: OrderType) -> KitchenInstruction | None   # None for takeaway (D6)
def start(order_type: OrderType, pickup_at: datetime | str | None) -> KitchenInstruction
def no_rider(order_number: str) -> KitchenInstruction
```

- **Depth and the deletion test.** Deleting the module would put the order-type rule, the time formatting and the
  wording back into every caller, so it earns its place.
- **Seam.** The interface is the **seam**. There are two **adapters** (Telegram's HTML and rich renderers, and WhatsApp's
  `wa_senders` and callback replies), so the seam is real, not hypothetical.
- **Plain text only.** Each adapter adds its own markup (Telegram `escape` + `<b>`, rich `RichTextBold` / heading, WhatsApp
  `*bold*`), so no channel's markup leaks into another.
- **Placement.** It sits next to `restaurant_decision.py` and `restaurant_actions.py`, the other cross-channel kitchen
  rules. `receipts/model.py` already imports from that package.
- **Testability.** The interface is the test surface: one table-driven test covers every stage × order type, and the
  channel tests only check that the text is placed and escaped.

**What stays out.** "When is the order in each stage" is already decided by the existing status keys
(`t_order_card_status()` gives `pickup_set` / `auto_accepted`, and the receipt kind gives `open`) and by the existing
events (`delivery_timedout`). The new module decides **what to say**, never **when**. That keeps it pure and avoids a
second source of truth beside the SQL status functions.

### New module (full content)

```python
"""
What the kitchen is told to do with an accepted order, on every channel (pure: no I/O, no channel markup).
    . Delivery: HOLD from the pickup time until a rider accepts, START on the kitchen receipt, DROP when no rider is found
    . Takeaway: never held; START on the kitchen receipt (sent as soon as the pickup time is set)
    . Plain text: Telegram escapes and bolds it (order_cards/model.py, receipts/model.py, restaurant_notifier.py),
      WhatsApp wraps it in *bold* (wa_senders.py, on_callback_wa_handler.py)
    . WHEN each applies is decided elsewhere (status keys and events); this module only decides WHAT is said
    . Overview: CONTEXT.md "Kitchen instruction"; docs/adr/0015-the-kitchen-receipt-is-the-start-signal.md
  Classes/Functions:
    . KitchenInstruction
    . hold, start, no_rider
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from utils_common.tz_utils import fmt_uk_time

OrderType = Literal["delivery", "takeaway"]


@dataclass(frozen=True)
class KitchenInstruction:
    headline: str
    detail: str


def hold(order_type: OrderType) -> KitchenInstruction | None:
    """Delivery only: the restaurant accepted, no rider yet. Takeaway is never held (None)."""
    if order_type != "delivery":
        return None
    return KitchenInstruction("⏳ Don't start cooking yet — we're finding a rider.", "Start when the kitchen receipt arrives.")


def start(order_type: OrderType, pickup_at: datetime | str | None) -> KitchenInstruction:
    """The go signal on the kitchen receipt. pickup_at is the CURRENT pickup time (moves with +10 / +20)."""
    at = fmt_uk_time(pickup_at) if pickup_at else None
    if order_type == "delivery":
        detail = f"Rider found · ready for pickup at {at}" if at else "Rider found"
    else:
        detail = f"Ready for collection at {at}" if at else "Get it ready for collection"
    return KitchenInstruction("🍳 Please start preparing now", detail)


def no_rider(order_number: str) -> KitchenInstruction:
    return KitchenInstruction(f"❌ No rider found for {order_number}.", "The order is cancelled — please don't prepare it.")
```

## 4. Code changes, file by file

### 4.1 Telegram order card: `channels/telegram/rest_admin/order_cards/model.py`

Only `view()` changes; `_status_line` keeps its current wording. The hold lines go between the status line and the body,
for every viewer (the decider, others and group chats), and only in `pickup_set` and `auto_accepted`. The card is
redrawn when it moves into those states, so existing copies pick the lines up through the normal refresh. It is
`TERMINAL` afterwards and is never touched again (D4).

```diff
+from utils_common.order_management import kitchen_instructions
 ...
+    def _hold(self) -> str | None:
+        """D-hold: a delivery with a pickup time waits for a rider; the kitchen receipt is the start signal."""
+        if self.status not in ("pickup_set", "auto_accepted"):
+            return None
+        h = kitchen_instructions.hold(self.facts.order_type)
+        return f"<b>{escape(h.headline)}</b>\n{escape(h.detail)}" if h else None
+
     def view(self, viewer: Viewer) -> View:
         ...
-        text = f"{self._status_line(viewer)}\n{self._body()}"
+        text = "\n".join(p for p in (self._status_line(viewer), self._hold(), self._body()) if p)
         return View(text, self._keyboard(viewer), self.status in TERMINAL)
```

Result for the screenshot's order:

```
✅ You accepted · pickup 11:14 PM
⏳ Don't start cooking yet — we're finding a rider.      (bold)
Start when the kitchen receipt arrives.
STRK-FPBH-33 · £17.57 · 🚚 Delivery
1x Buffalo Chicken Wings
…
```

### 4.2 Kitchen receipt: `channels/telegram/rest_admin/receipts/model.py`

There is one helper, and both forms read it (the module's rule: "two decisions are made once and read by BOTH forms").

```diff
+from utils_common.order_management import kitchen_instructions
+from utils_common.order_management.kitchen_instructions import KitchenInstruction
 ...
+    def _start(self) -> KitchenInstruction | None:
+        """D5: while the food is being made ('open') the first line is the call to action; gone after Ready."""
+        if self.kind != "open":
+            return None
+        return kitchen_instructions.start(self.facts.order_type, self.facts.pickup_at)
```

HTML form, `_title_lines` (line 255; also used by the handed-over `top`, which is never `open`):

```diff
     def _title_lines(self, viewer: Viewer) -> list[str]:
         f = self.facts
         kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
         lines = [f"🧾 KITCHEN RECEIPT · {kind}", f"<b>{escape(f.order_number)}</b>"]
+        if (go := self._start()) is not None:
+            lines = [f"<b>{escape(go.headline)}</b>", escape(go.detail), ""] + lines
         if status := self._status_line(viewer):
             lines.append(status)
         return lines
```

Rich form, `_rich_head` (line 502). The heading becomes the call to action, one size larger (aiogram
`InputRichBlockSectionHeading.size`: 1 is the largest, 6 the smallest; today it is 3):

```diff
     def _rich_head(self, viewer: Viewer) -> list:
         f = self.facts
         kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
-        return [
-            InputRichBlockSectionHeading(text=f"🧾 Kitchen receipt · {kind}", size=3),
-            InputRichBlockParagraph(text=RichTextBold(text=f.order_number)),
-            InputRichBlockButtons(buttons=[self._badge(viewer)]),
-        ]
+        if (go := self._start()) is not None:
+            head = [
+                InputRichBlockSectionHeading(text=go.headline, size=2),
+                InputRichBlockParagraph(text=RichTextBold(text=go.detail)),
+                InputRichBlockParagraph(text=[RichTextBold(text=f.order_number), f" · 🧾 Kitchen receipt · {kind}"]),
+            ]
+        else:
+            head = [
+                InputRichBlockSectionHeading(text=f"🧾 Kitchen receipt · {kind}", size=3),
+                InputRichBlockParagraph(text=RichTextBold(text=f.order_number)),
+            ]
+        return head + [InputRichBlockButtons(buttons=[self._badge(viewer)])]
```

These stay as they are:

- **Badge.** `_badge_text` keeps "📋 Preparing · pickup 11:14 PM", so there's no churn in the badge tests.
- **Moved pickup.** `pickup_at` is the current time, so after a +10 the headline detail redraws with the new time.
- **`rider_cancelled`.** Not `open`, so it shows no call to action. A new rider's fresh receipt is `open` and says
  "Please start preparing now" again (D7).
- **`_fit`.** Still measures the whole HTML text. The call to action adds about 70 characters, inside the 4000 limit.

The resulting rich receipt (open, delivery):

```
🍳 Please start preparing now                     (heading, size 2)
Rider found · ready for pickup at 11:14 PM        (bold)
STRK-FPBH-33 · 🧾 Kitchen receipt · 🚚 Delivery
[ 📋 Preparing · pickup 11:14 PM ]                (blue badge)
⏰ Pickup: 11:14 PM
▸ Progress · step 2 of 5
🔑 Restaurant code: …   🛵 Rider: …   Items …
[ 🍳 Ready – notify rider ]  [ 11:24 PM (+10) ] [ 11:34 PM (+20) ]
```

After Ready the receipt goes back to today's layout, starting with `🧾 Kitchen receipt · 🚚 Delivery`.

### 4.3 Notifier, Telegram adapter: `utils_common/notify/restaurant_notifier.py`

- **AutoAccepted (lines 272-280).** Append the hold for deliveries. `AutoAccepted.order_type` already exists (line 82).
  The card below it shows the same lines, but this notice is the message that makes the phone buzz.
  ```diff
               text = (
                   f"⏱ <b>{escape(notice.order_number)}</b> auto-accepted (no answer in time). "
                   f"Pickup {escape(notice.pickup_display)} ({notice.pickup_minutes} min after order)."
               )
  +            if (h := kitchen_instructions.hold(notice.order_type)) is not None:
  +                text += f"\n<b>{escape(h.headline)}</b>\n{escape(h.detail)}"
  ```
- **NoRiderFound (lines 287-292).** The wording comes from the module, and the call stays `reply_to="card"`.
  ```diff
  -            text = f"🚫 No rider found for <b>{escape(notice.order_number)}</b>. The order was cancelled and the customer has been told."
  +            d = kitchen_instructions.no_rider(notice.order_number)
  +            text = f"<b>{escape(d.headline)}</b>\n{escape(d.detail)}"
  ```
- **WhatsApp adapter (line 165).** Pass `order_type`:
  `wa_senders.admin_auto_accept_notice(notice.admins, notice.order_number, notice.pickup_display, notice.pickup_minutes, order_type=notice.order_type)`.
- **Docs in the code.** The `NoRiderFound` docstring (line 101), "Not sent for configured auto-accept orders", becomes "Sent
  for every delivery (D3)". Also update the mapping in the module docstring (line 18-19).

### 4.4 WhatsApp senders: `utils_common/waba_utils/wa_senders.py`

| Function | Change |
|---|---|
| `admin_auto_accept_notice` (154) | New keyword `order_type: str = "delivery"`. For a delivery, append `\n*{h.headline}*\n{h.detail}`. Takeaway text unchanged |
| `admin_no_rider_notice` (185) | `text = f"*{d.headline}*\n{d.detail}"` from `no_rider(order_number)`, replacing `"No Rider Found for order number: …"` |
| `admin_order_reciept` (232; 295-296) | `go = start("delivery", delivery_summary.pickup_time)`. `header=go.headline` (fits WhatsApp's 60-character header limit) and `text=f"*{go.detail}*\n{rest_header}\n" + rest_text + "\n" + delivery_instructions`, so the order number moves to the first body line |
| `takeaway_admin_order_receipt` (320; 351-352) | The same, with `start("takeaway", pickup_time)` |

WhatsApp messages are never edited, so the call to action stays on the WhatsApp receipt for good. That is acceptable: it is
the message that started the cooking. Check the body length against WhatsApp's 1024-character limit for
interactive bodies. The existing receipts with long item lists are already close, and this adds about 50 characters (see
Risks).

### 4.5 WhatsApp pickup reply: `watomation/on_callback_wa_handler.py:290`

```diff
         if outcome.result == "ok":
-            await msg.reply(text="Pickup time updated")
+            await msg.reply(text=_pickup_set_reply(order_type, outcome.pickup_time or pickup_time))
 ...
+def _pickup_set_reply(order_type: str, pickup_time: str) -> str:
+    """'Pickup time set to *11:14 PM*.' plus, for a delivery, the hold lines (kitchen_instructions.hold)."""
+    text = f"Pickup time set to *{fmt_uk_time(pickup_time)}*."
+    if (h := kitchen_instructions.hold(order_type)) is not None:
+        text += f"\n*{h.headline}*\n{h.detail}"
+    return text
```

The `already_set` / `not_accepted` reply ("Pickup time already updated") is left as it is.

### 4.6 Turn the No-rider admin notice back on: `watomation/routers/delivery_hooks.py:849-861`

Replace the commented block. The configured-auto skip is gone (D3). `RestaurantMaster.get_admins_for` is synchronous, so it
goes through `asyncio.to_thread`, as CLAUDE.md requires. `notify()` never raises, so the overwatch step and the background
tasks still run.

```diff
-    # 2. Restaurant admins are deliberately NOT told "no rider found" for now: only
-    # overwatch is. To bring the admin notice back ...
-    #
-    # if delivery_summary.get("rest_confirmation_method") != "configured_auto":
-    #     rest_ref = delivery_summary["order_number"].split("-")[0]
-    #     rest_admins = RestaurantMaster.get_admins_for(rest_ref)
-    #     await restaurant_notifier.notify(
-    #         NoRiderFound(delivery_summary["order_number"], rest_admins or [], rest_ref)
-    #     )
+    # 2. Tell the restaurant (WhatsApp + Telegram, every delivery incl. configured auto-accept): its card told the
+    # kitchen to hold until the receipt, so it must hear that no receipt is coming (kitchen_instructions.no_rider).
+    rest_ref = delivery_summary["order_number"].split("-")[0]
+    try:
+        rest_admins = await asyncio.to_thread(RestaurantMaster.get_admins_for, rest_ref)
+    except Exception:
+        logger.exception("No-rider admin lookup failed", extra={"order_number": delivery_summary.get("order_number")})
+        rest_admins = []
+    await restaurant_notifier.notify(NoRiderFound(delivery_summary["order_number"], rest_admins or [], rest_ref))
```

Also:

- Add `NoRiderFound` to the import on line 87.
- Change module docstring line 11, "Suppresses no-rider admin messages for configured auto-accept orders", to "Tells
  restaurant admins and overwatch when no rider is found".
- The Telegram copy goes to linked admins even when `rest_admins` is empty, because `Notices.send` resolves chats by
  `rest_ref`.
- Test orders (`STRK-TEST-*`) get the notice as well. Only the `post_delivery_timedout` webhook skips test orders, and that
  stays.

### 4.7 Nothing in SQL

Nothing changes in SQL: no status key, ledger kind or cron job. `no_rider_found` is already a Telegram notice kind
(`restaurant_notifier.py:290`). So there is no migration, no `build_guide.py` run and no drift check.

## 5. Tests

| File | Change |
|---|---|
| **new** `tests/utils_common/order_management/test_kitchen_instructions.py` | Table-driven: `hold` (delivery gives the two lines, takeaway gives None); `start` (delivery / takeaway × with and without a time, a str or a datetime, the UK time format); `no_rider` (the number is in the headline) |
| `tests/channels/telegram/test_order_card_model.py` | Delivery `pickup_set` and `auto_accepted` have the hold lines for the decider, another admin and a group, placed between the status line and the body. Takeaway `pickup_set` has none. `awaiting` / `accepted` / `declined` / `auto_declined` / gone have none. The order number is escaped |
| `tests/channels/telegram/test_receipt_model.py` | `open` delivery / takeaway: the HTML starts with the bold headline then the detail, and the rich first block is a size-2 heading with the call to action. `ready` / `picked_up` / `done` / `rider_cancelled` have no call to action and the old heading. Adjusting the pickup moves the detail time. Update the layout assertions in `test_open_delivery_has_everything_the_kitchen_needs` (51), `test_kitchen_html_has_the_progress_quote_and_everything_else_as_before` (289) and `test_takeaway_open_has_only_ready_and_the_pay_line` (103). `test_huge_order_is_cut_with_a_marker_and_always_fits` (122) still passes |
| `tests/utils_common/test_restaurant_notifier.py` | `test_whatsapp_adapter_auto_accepted_is_todays_text` (141) passes `order_type` (rename it). Telegram auto-accept: delivery has the hold, takeaway (`test_telegram_takeaway_auto_accept_replies_to_the_takeaway_card`, 235) does not. The Telegram no-rider text is the new wording |
| `tests/regressions/test_p7_wa_senders.py` | Auto-accept text tests (48, 56): delivery has the hold, takeaway has today's text. New tests: `admin_no_rider_notice` text; the receipt header is the call to action and the body starts with the detail then `Order #… (Kitchen)` |
| `tests/watomation/test_on_callback_wa_handler.py` | Line 303 `{"text": "Pickup time updated"}` becomes the new reply. Add takeaway (no hold) |
| `tests/watomation/routers/test_delivery_hooks.py` | Line 431: `notices == [NoRiderFound("ELAS-ABCD-1", [...], "ELAS")]` and overwatch is still told. Line 471 `…skips_no_rider_admin_message_for_configured_auto_accept` is turned round to `…tells_admins_for_configured_auto_accept_too`. New test: the admin lookup failing still tells overwatch and schedules the tasks |
| `tests/watomation/test_customer_notification_contracts.py` | Run it. The no-rider path must still leave the customer events unchanged |

Then run `pytest`, `ruff check .` and `tests/test_datamodels_standard.py` (no SQL changed, but it confirms that).

## 6. Docs

| Doc | Change |
|---|---|
| `CONTEXT.md` | New entry **Kitchen instruction**: what the kitchen is told about an accepted order, which is hold (delivery, from the pickup time until a rider accepts), start (the kitchen receipt) or drop (no rider found). Takeaway is never held. _Avoid_: prep notice, cooking alert. In the **Order card** entry (line 337), add "a delivery card with a pickup time carries the hold lines" |
| **new** `docs/adr/0015-the-kitchen-receipt-is-the-start-signal.md` | Records D4 and D7: the card stays terminal and the receipt is the start signal. A live card ("Rider found") was rejected because it would need rider state in `t_order_card_status()` plus a refresh trigger. Recorded so future reviews don't suggest it again |
| `docs/alerts-and-notifications.md` + `.html` | Rows: Admin chooses pickup time (hold reply), Delivery operational receipt and Collection receipt (call-to-action headline), **No rider found → Restaurant admins (WhatsApp + Telegram, every delivery) + Overwatch**, Restaurant-confirmation timeout (hold on auto-accept) |
| `docs/telegram-layer.md` + `.html` | Rows for Order cards and Kitchen receipts in the file map (lines 51, 54), plus a change-log entry |
| `docs/delivery_process.md` | Phases 2-4: the kitchen holds until the receipt. Update the no-rider bullet |
| `docs/live-order-test-harness.md` and the comments in `ordelo_datamodels/test_support/test_restaurant_notices.sql` (STAGE 2 / 3 / 4) | The expected texts. Comment-only, so `tests/sql/test_restaurant_notices_script_sql.py` is unaffected (check that it doesn't match comments) |
| restaurant-frontend `docs/alerts-and-notifications.md` | No-rider row: restaurant admins are told again |
| `plans/restaurant-confirmation-timeout-action-plan.md` | Note under follow-ups that the "No rider found → overwatch only" follow-up is reversed by this plan |

## 7. Order of work

1. `kitchen_instructions.py` and its test.
2. The Telegram card (4.1) and receipt (4.2), with their model tests.
3. The notifier (4.3), `wa_senders` (4.4) and the WhatsApp reply (4.5), with their tests.
4. The No-rider notice (4.6) and its hook tests.
5. Docs (6): CONTEXT.md, ADR 0015, then each `.md` with its `.html` companion.
6. Full `pytest` and `ruff`, then a commit on a branch of the owner's choosing. Commit and push only when asked.
7. Live check (8).

## 8. Live check (`STRK-TEST-*` harness, `docs/live-order-test-harness.md`)

1. **Hold.** Run STAGE 0 and 1, then accept and pick a time on **Telegram**. The card shows the bold hold lines; the group
   copy shows them too. Repeat on a fresh order on **WhatsApp**: the reply is "Pickup time set to *…*." plus the hold.
2. **Start.** Run STAGE 2b and 3 (the rider accepts). The Telegram receipt opens with "🍳 Please start preparing now /
   Rider found · ready for pickup at …". **Check the phone's notification preview.** If Telegram previews a rich message
   by something other than its first heading, note what it shows. The WhatsApp receipt header is the call to action.
3. **Adjust, then Ready.** Run STAGE 4. Tap +10: the detail time moves. Tap Ready: the call to action disappears and the
   heading is "🧾 Kitchen receipt · 🚚 Delivery" again.
4. **Auto-accept.** On a fresh order, accept but don't choose a time. After 15-25 s the auto-accept notice on both
   channels carries the hold, and so does the card.
5. **No rider.** On a fresh order, accept, run STAGE 2b and let the offer expire without a rider. Both channels get the
   DROP text as a reply to the card, overwatch gets one message, and the payment-release behaviour is unchanged.
6. **Takeaway.** The takeaway stage: the card has no hold, and the receipt says "Ready for collection at …".

## 9. Risks and open points

- **Telegram preview of rich messages (unknown).** The plan assumes the notification shows the first heading. Step 8.2
  checks this. If it doesn't, the fallback is to put the call to action in the reply-quote target instead. That would be
  a new decision, so it's not built now.
- **WhatsApp body limit.** Interactive bodies are capped at 1024 characters. A very long order could already exceed it,
  and this adds about 50. Check: log `len(text)` in a test with a large `FoodOrder`; if close, trim the instructions
  block, not the call to action.
- **The card stays as it is after a rider accepts (D4).** An admin scrolling up still sees "don't start cooking yet" on the
  card. The receipt threaded under it, with its larger headline, is what supersedes it. ADR 0015 records why.
- **New rider (D7).** A re-dispatch receipt says "Please start preparing now" even if the food is already on.
  Harmless by decision.
- **Not in scope.** Order-card wording for `awaiting` / `accepted`; the badge text; rider-facing messages; customer
  messages.
