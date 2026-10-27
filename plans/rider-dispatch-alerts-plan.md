# Rider dispatch alerts: repeated Telegram job offers (plan)

Status: **plan, ready to implement** (26 Oct 2026). Branch `feature/rider-dispatch-alerts`, written against commit `5c264e7`.
Owner decisions were taken in a grilling session on 26 Oct 2026 (section 1). The SQL is already written and checked on a
scratch database: [`ordelo_datamodels/migrations/rider_offer_alerts.sql`](../ordelo_datamodels/migrations/rider_offer_alerts.sql).
**Nothing has been applied to the shared database. The owner applies the migration himself.**

Read first: `CLAUDE.md` (RPC pattern, cross-references), `agents.md` "ordelo_datamodels SQL standard",
`ordelo_datamodels/telegram/t_order_alerts.sql` (the admin reminder job this copies), `ordelo/rider_messaging/` (port,
adapters, factory), `ordelo/dispatch_actions.py`, `channels/telegram/rider/jobs.py`, `docs/live-order-test-harness.md`.

---

## 0. What we are building, in one paragraph

When a job offer goes to a rider **on Telegram** and they don't answer, the rider bot sends the offer again at
**10, 20, 30, 45, 60, 90 and 120 seconds** after the original. Each reminder is a fresh copy (so the phone buzzes; an
edit doesn't). It has the same Accept / Decline buttons and a top line `⏰ Still open · reminder n of 7`. The previous
copy is deleted, so the chat only ever holds one live copy.

Reminders stop for **everyone** as soon as any rider of the order accepts. They also stop for **one rider** when that
rider declines, pauses, goes off shift, becomes inactive, or starts another job. If nobody has accepted by the last offset
(120 s after the order's first Telegram offer), overwatch gets **one** WhatsApp line for that order. WhatsApp riders are
not affected.

## 1. Decisions (owner, 26 Oct 2026)

| # | Decision | Answer |
|---|---|---|
| D1 | Channel | **Telegram riders only.** Only `delivery_dispatch.channel = 'telegram'` offers are reminded. Nothing changes for WhatsApp riders |
| D2 | Cadence | `ordelo_config.RIDER_OFFER_ALERT_OFFSETS_SECS = '10,20,30,45,60,90,120'` (seconds after the offer). One global key, no per-restaurant override. Blank = off. A changed value applies to new offers only |
| D3 | Stop rule, order level | Stop for every rider when **any** offer of the order is `accepted` (not waiting for assignment), or the order is assigned, inflight, timed out, declined or gone |
| D4 | Stop rule, rider level | Stop for one rider when they decline, **pause** (`/off`, `is_paused('rider', …)`), go off shift, are no longer `status = 'active'`, start another job, or have no Telegram chat. Same gate as `get_available_riders()` |
| D5 | Look | Same offer text and buttons, plus a top line `⏰ Still open · reminder n of of` |
| D6 | Copies | Send a new copy, then delete the previous one (like the admin order cards) |
| D7 | Code placement | A new thin router `watomation/routers/rider_offer_alerts.py` (`POST /rider-hooks/offer-alerts`). The logic goes in a deep module `ordelo/offer_reminders.py`. `delivery_hooks.py` only gives up its offer-text code to a shared builder |
| D8 | Overwatch | **Once per order**, when the order's first Telegram offer has passed its last offset and nobody has accepted. Sent through `channels/telegram/ops_alerts.alert_ops` (the overwatch WhatsApp numbers) |
| D9 | Live test | Only `ordelo_datamodels/test_support/test_restaurant_notices.sql` (STRK). STAGE 0 gets a cleanup line and a new read-only **STAGE 2c**. No new test SQL file |
| D10 | Out of scope | Staggering riders (one at a time). Fixing the `job_create_dispatch.sql` header comment. Ledger retention (see section 10) |

## 2. Facts this design depends on (verified in code)

| Fact | Where | Why it matters |
|---|---|---|
| Offers are created every 5 s by `job_create_dispatch()`; the statement trigger POSTs them to `/delivery-hooks/delivery-dispatch` | `ordelo_datamodels/dispatch/job_create_dispatch.sql`, `dispatch/delivery_dispatch.sql` (`delivery_dispatch_whook_statement`) | The first offer is unchanged. Reminders start 10 s after `delivery_dispatch.dtts` |
| The code offers the **next** `DISPATCH_BATCH_SIZE_<VEHICLE>` riders on every 5 s run, until none are left; it does not wait for open offers (the file header says it does, which is wrong; D10) | `job_create_dispatch.sql` lines ~80-160 | Several riders usually hold the same order at once, so all of them get reminders |
| Paused, inactive, off-shift and already-busy riders never get an offer | `get_available_riders()`, same file (`NOT public.is_paused('rider', allRiders.rider_id, NULL)`) | `rider_offer_state()` repeats this gate for **reminders** (D4) |
| Accept sets the offer to `'accepted'` at once; `job_assign_dispatch()` (5 s) picks the winner, sets it `'assigned'` and inserts `delivery_inflight` | `ordelo/dispatch_actions.py` `respond_to_offer()` (around line 125); `dispatch/job_assign_dispatch.sql` | D3 stops on `'accepted'` without waiting for the assignment |
| **When an order is assigned, offers nobody answered stay `status = 'unassigned'`.** Only accepted-but-lost offers become `'missed'` | `dispatch/notify_missed_dispatches.sql` (`d.status = 'accepted'`), `delivery_hooks.notify_missed_dispatches_hook` | "Is this offer still open?" must look at the **order**, not only the offer row (`rider_offer_order_open()`) |
| `dispatch_cancel_before_pickup()` **deletes** the order's other dispatch rows and re-offers the order | `dispatch/dispatch_cancel_before_pickup.sql` (`DELETE FROM delivery_dispatch WHERE order_number = … AND dispatch_id <> …`) | The new table has no foreign key; a reminder for a deleted offer is cancelled ('gone') |
| On assignment, unanswered Telegram offers are edited to "Taken by another rider" and the winner's to "The job is yours"; on timeout to "Offer expired". These edits use `delivery_dispatch.channel_msg_ref` | `delivery_hooks.py` line 630 (inflight init) and line 878 (timed out) → `dispatch_actions.close_open_offers()` (line 157); missed: `delivery_hooks._send_missed_dispatch_if_allowed` | Each reminder **must move `channel_msg_ref` to the new copy**, or the later close edits a deleted message and leaves live buttons |
| `record_offer_ref()` writes `channel_msg_ref` after the first offer is sent | `dispatch_actions.py` line 148, called from `delivery_hooks.py` line 351 | It must only fill an empty ref, so a slow first send can't overwrite a reminder's newer ref (section 5.6) |
| Telegram adapter: `offer_job` sends with `rider_offer_kb(dispatch_id)`; `offer_closed` edits in place; there is no delete | `ordelo/rider_messaging/telegram.py` lines 102-118 | Add `delete()` and the notice line |
| `messenger_for(..., 'telegram', tcid)` **falls back to WhatsApp** when the rider bot or the tcid is missing | `ordelo/rider_messaging/factory.py` `messenger_for()` | The reminder module must refuse to send unless the adapter really is Telegram (no surprise WhatsApp reminders) |
| A tap on any copy is authorised by the Telegram user and `dispatch_id` only, and redraws the tapped message | `channels/telegram/rider/jobs.py` `_handle_offer_tap` (lines 91-118) | Several copies can never double-book; a tap on a deleted copy fails quietly |
| The admin reminder job's shape: seed → cancel → due (collapse to largest) → POST → mark only on 2xx, supersede first | `telegram/t_order_alerts.sql` `job_t_order_alerts()` | Copied as-is |
| `delivery_dispatch.dtts` is `timestamp without time zone`, written by a pg_cron session | `dispatch/delivery_dispatch.sql` | The job (also pg_cron) reads `dtts::timestamptz` in the same zone. Python never writes `dtts` |
| The rider bot is optional: `config.rider_bot` is `None` without a token | `config/tgram_setting.py` line 154 | The route answers 503, so the rows stay pending and nothing is lost |

## 3. Design

### 3.1 Flow

```
pg_cron 5 s ─► job_rider_offer_alerts()                                   (ordelo_datamodels/dispatch/job_rider_offer_alerts.sql)
                 OFFSETS  parse_alert_offsets('RIDER_OFFER_ALERT_OFFSETS_SECS'), >0 only; NULL = OFF (cancel all pending)
                 SEED     reminder rows: Telegram offers, 'unassigned', < 15 min old, rider_offer_state() = 'open'
                          escalation row: one per order (first Telegram offer + last offset), while rider_offer_order_open()
                 CANCEL   pending reminders whose rider_offer_state() is not 'open'; escalations whose order is no longer open
                 DUE      one reminder per offer (largest due offset); every due escalation (+ offered / declined counts)
                 POST     /rider-hooks/offer-alerts {reminders:[{dispatch_id,n,of}], escalations:[{order_number,after_secs,offered,declined}]}
                 MARK     only on 2xx: losers 'superseded' first, then due rows 'sent'
               ─► watomation/routers/rider_offer_alerts.py   (503 without the rider bot; 200 at once; background tasks)
                    ─► ordelo/offer_reminders.remind(dispatch_id, n, of)
                         1 store.snapshot()            rider_offer_reminder_snapshot()   check BEFORE sending
                         2 messenger.offer_job()       fresh copy + "⏰ Still open · reminder n of 7"
                         3 store.reminder_sent()       rider_offer_reminder_sent()       move channel_msg_ref; state AFTER sending
                         4 messenger.delete(previous)  (or delete our own copy when 'stale')
                         5 store.snapshot() again; if closed → messenger.offer_closed(new copy, reason)
                    ─► ordelo/offer_reminders.escalate(order_number, …)   re-checks rider_offer_order_open(), then alert_ops()
```

### 3.2 Modules, interfaces and seams (codebase-design vocabulary)

| Module | Interface (all a caller must know) | Behind it | Seam / adapters |
|---|---|---|---|
| `rider_offer_state(dispatch_id)` (SQL) | `{state: open\|quiet\|closed, reason}` | Every stop rule: the offer's own status, the order (via `rider_offer_order_open`), the rider gate (active, shift, pause, other job, tcid) | Used by the job, both RPCs and STAGE 2c. **The one place the rules live** (locality). Changing D3/D4 is a one-function change |
| `rider_offer_order_open(order)` (SQL) | boolean | "Order still looking for a rider" | Also used by the escalation |
| `job_rider_offer_alerts()` (SQL) | none (cron) | Seeding, collapse, at-least-once marking | Same shape as `job_t_order_alerts()` |
| `ordelo/offer_reminders.py` | `remind(dispatch_id, n, of) -> str`, `escalate(order_number, after_secs, offered, declined) -> bool` | Snapshot, send, swap, delete, re-check, close; the authorised-audience check; never decides rules | **Store seam** `OfferReminderStore` with two adapters: `SupabaseOfferReminderStore` (RPCs, `client_ordelo_service`, `asyncio.to_thread`) and `FakeOfferReminderStore` (tests; same JSON shapes). **Messenger seam**: the existing `RiderMessenger` (Telegram, WhatsApp, `RecordingRiderMessenger`) |
| `RiderMessenger` (existing port) | + `delete(ref)`; `JobOffer.notice` | Telegram: `bot.delete_message`; WhatsApp: no-op (the Cloud API cannot delete) | No new adapter. `delete` is the one method added |
| `ordelo/rider_messaging/offers.py` (new) | `job_offer(row, dispatch_id=None) -> JobOffer` | The offer header and body, moved verbatim out of `delivery_hooks.wa_send_delivery_dispatch_request_to_rider` | Pure function. The first offer and every reminder use it, so they can't drift apart |
| `watomation/routers/rider_offer_alerts.py` | `POST /rider-hooks/offer-alerts` | Validation and scheduling only | Thin route, like `telegram_order_alerts.py` / `pause_hooks.py` |

Deletion test: delete `offer_reminders.py`, and the send → swap → delete → recheck sequence and its race handling would
reappear in the route and in tests. It earns its place. `rider_offer_open()` as a separate boolean wrapper of
`rider_offer_state()` would be a pass-through, so the job compares `->> 'state'` directly. (This is the one change from the
names in the grilling summary.)

### 3.3 Ledger: `public.rider_offer_alert`

| Column | Meaning |
|---|---|
| `kind` | `'reminder'` (one offer at one offset) or `'escalation'` (one order, to overwatch, once) |
| `order_number`, `dispatch_id`, `rider_id` | the subject; `dispatch_id` / `rider_id` are NULL for an escalation (check constraint) |
| `offset_secs`, `n`, `of_n` | the checkpoint and "reminder n of of" |
| `due_at` | `delivery_dispatch.dtts + offset` (escalation: the order's first Telegram offer + last offset) |
| `status` | `pending → sent \| superseded \| cancelled` (same vocabulary as `rider_pickup_alert` / `t_order_alerts`) |

Unique `(dispatch_id, offset_secs) WHERE kind='reminder'`, unique `(order_number) WHERE kind='escalation'`, and a
partial index on `due_at WHERE status='pending'`. RLS is on and everything is revoked from `PUBLIC, anon, authenticated`
(CLAUDE.md rule 5); Python reaches it only through the two RPCs with `client_ordelo_service`.

### 3.4 `rider_offer_state()` table (what the rider sees)

| Situation | state / reason | Reminders | What happens to the rider's latest copy |
|---|---|---|---|
| Unanswered, order open, rider can take it | `open` | continue | — |
| This rider tapped Accept | `closed / accepted` | stop | the tap redraws it "👍 Accepted · waiting"; a reminder in flight redraws its own copy the same way |
| This rider tapped Decline | `closed / declined` | stop | "Declined" |
| Another rider tapped Accept, not yet assigned | `quiet / accepted_elsewhere` | stop | unchanged; the assignment (`close_open_offers 'taken'`) redraws it within ~5 s |
| Assigned to another rider / inflight | `closed / taken` | stop | "❌ Taken by another rider" |
| This rider won | `closed / assigned` | stop | "✅ The job is yours" |
| Order timed out | `closed / expired` | stop | "⌛ Offer expired" |
| Order declined | `closed / cancelled` | stop | "🚫 Order cancelled" |
| Dispatch row deleted (cancel before pickup, test reset) | `closed / gone` | stop | "This job is no longer available" (a tap says the same) |
| Rider paused / off shift / inactive / on another job / no tcid | `quiet / paused` … | stop | unchanged (still tappable, as today) |
| Offer on WhatsApp | `quiet / not_telegram` | never seeded | — |

## 4. Database (the migration is ready; the implementer creates the owner files)

**Migration (history, ready):** [`ordelo_datamodels/migrations/rider_offer_alerts.sql`](../ordelo_datamodels/migrations/rider_offer_alerts.sql).
It's self-contained: PRE-CHECK, STEP 1 table, STEP 2 the five functions with REVOKEs and COMMENTs, STEP 3 the config row,
STEP 4 VERIFY (`1 / true / 5 / 0 / '10,20,30,45,60,90,120'`), STEP 5 deploy + `drift_check.py`, STEP 6 `cron.schedule`
(operator, after the deploy), STEP 7 the STRK live test, an off switch and a rollback.
Checked on a scratch Postgres 16 (repo `tests/sql/minimal_schema.sql` + `availability/pauses.sql` + the migration, applied
twice). Results: seeding only Telegram offers that are `open`; collapse (offset 10 superseded, 20 sent); escalation counts
`offered/declined`; `paused` → cancelled; another rider's Accept → `quiet/accepted_elsewhere` and the order's pending rows
cancelled (escalation included); inflight → `closed/taken`; `reminder_sent` swapped / stale / gone; off switch seeds
nothing; POST 500 → returns false and rows stay pending.

**Owner files to create** (SQL standard: 13-section header, `--` block per object, `COMMENT ON`; bodies **identical** to the
migration; `drift_check.py` will compare them with live after the owner applies it):

| File | Objects | Copy from migration |
|---|---|---|
| `ordelo_datamodels/dispatch/rider_offer_alert.sql` | table `rider_offer_alert` (+3 indexes, RLS, REVOKE), fn `rider_offer_order_open`, fn `rider_offer_state`, fn `rider_offer_reminder_snapshot`, fn `rider_offer_reminder_sent` | STEP 1 + the first four functions of STEP 2 |
| `ordelo_datamodels/dispatch/job_rider_offer_alerts.sql` | fn `job_rider_offer_alerts`, config row, the `cron.schedule('job_rider_offer_alerts', '5 seconds', …)` line annotated "not yet active on live" (the job-file rule) | the job function + STEP 3 + STEP 6 |

Header content to fill in (main points):
- `HOW IT FITS`: the flow in 3.1; a pointer to `delivery_dispatch.sql` journey step 4 "offers"; "Telegram only (D1)".
- `CALLED BY`:
  - `rider_offer_state`: sql `job_rider_offer_alerts()`, `rider_offer_reminder_snapshot()`, `rider_offer_reminder_sent()`, and `test_support/test_restaurant_notices.sql` STAGE 2c.
  - `rider_offer_reminder_snapshot`: python `ordelo/offer_reminders.py: SupabaseOfferReminderStore.snapshot()`.
  - `rider_offer_reminder_sent`: python `ordelo/offer_reminders.py: SupabaseOfferReminderStore.reminder_sent()`.
  - `rider_offer_order_open`: sql `rider_offer_state()`, `job_rider_offer_alerts()`; python `ordelo/offer_reminders.py: SupabaseOfferReminderStore.order_open()`.
  - `job_rider_offer_alerts`: cron `'job_rider_offer_alerts' 5 seconds`.
- `SECURITY`: RLS on, revoked, service key only.
- `TESTS`: `tests/sql/test_rider_offer_alerts_sql.py`, `tests/sql/test_rider_offer_alerts_migration_sql.py`, `tests/ordelo/test_offer_reminders.py`, `tests/sql/test_restaurant_notices_script_sql.py`.
- `GOTCHAS`:
  - The rider gate copies `get_available_riders()`; keep the two in step.
  - The `dtts` time zone note (section 2).
  - One escalation per order, even after a re-dispatch.
  - `accepted_elsewhere` is quiet, not closed.
  - No foreign key, on purpose.

Also update, in the same commit:
- `ordelo_datamodels/dispatch/delivery_dispatch.sql` `HOW IT FITS` step 4: append "→ unanswered Telegram offers are reminded by `job_rider_offer_alerts()` (dispatch/job_rider_offer_alerts.sql)". Also add `rider_offer_state()`, `rider_offer_reminder_snapshot()`, `rider_offer_reminder_sent()`, `rider_offer_order_open()` and `job_rider_offer_alerts()` to `CALLED BY delivery_dispatch: sql`.
- `ordelo_datamodels/guide_content.json`: add the two files to the dispatch capability, then `python scripts/datamodels/build_guide.py` (never hand-edit `catalog.json` or the guide).
- `python scripts/datamodels/format_sql.py --check` and `sqlfluff lint` on the two new files.

## 5. Python changes (file by file, with diffs)

### 5.1 `ordelo/rider_messaging/models.py`: `JobOffer.notice`

```diff
 @dataclass(frozen=True)
 class JobOffer:
     """A delivery offer to one rider. header / text are written once, in WhatsApp style (*bold*), as today."""

     dispatch_id: int
     order_number: str
     header: str
     text: str
     footer: str = "♾️ Byteloop AI"
+    # Telegram only: one line above the offer, e.g. "⏰ Still open · reminder 3 of 7" (ordelo/offer_reminders.py).
+    # The WhatsApp adapter ignores it (reminders are never seeded for WhatsApp offers, D1).
+    notice: str | None = None
```

### 5.2 New `ordelo/rider_messaging/offers.py`: one offer builder (the WhatsApp regression guard)

Move the text **verbatim** from `watomation/routers/delivery_hooks.py` lines 327-342, including the leading four
spaces before `Pickup time` and the trailing `    """`. **Before** moving it, capture a golden: run the current
function against the fixture row in 5.9 and store the `(header, text)` it produces.

```python
"""
The job offer a rider sees, built from one offer row (the bulk_dispatch item of delivery_dispatch_whook_statement() in
ordelo_datamodels/dispatch/delivery_dispatch.sql, or the 'offer' object of rider_offer_reminder_snapshot() in
ordelo_datamodels/dispatch/rider_offer_alert.sql; same keys, same JSON types).
    . job_offer(row, dispatch_id=None) -> JobOffer: header "<distance> miles, £<payout>, @<pickup>" and the WhatsApp-style
      body, byte-identical to what delivery_hooks.wa_send_delivery_dispatch_request_to_rider sent before (golden test).
  Classes/Functions:
    . job_offer
"""

from __future__ import annotations

from typing import Any, Mapping

from utils_common.tz_utils import fmt_uk_time

from .models import JobOffer


def job_offer(row: Mapping[str, Any], dispatch_id: int | None = None) -> JobOffer:
    pickup_time = fmt_uk_time(row["pickup_time"])
    header_text = f"{row['distance']} miles, £{row['rider_payout']}, @{pickup_time}"
    wa_text = f"""
    Pickup time - *{pickup_time}*

Pickup location - *{row["rest_name"]}*
{row["rest_address"]}

Drop off location - *{row["customer_name"]}*
{row["customer_address"]}

Order number - *{row["order_number"]}*

Vehicle type - *{row["vehicle_type"]}*
    """
    return JobOffer(
        dispatch_id=dispatch_id if dispatch_id is not None else int(row["dispatch_id"]),
        order_number=row["order_number"],
        header=header_text,
        text=wa_text,
    )
```

Export it from `ordelo/rider_messaging/__init__.py` (`from .offers import job_offer`, add to `__all__`).

### 5.3 `watomation/routers/delivery_hooks.py`: use the builder (no behaviour change)

```diff
-from ordelo.rider_messaging import JobOffer, dispatch_channel, for_dispatch, for_thread
+from ordelo.rider_messaging import dispatch_channel, for_dispatch, for_thread, job_offer
@@ async def wa_send_delivery_dispatch_request_to_rider(
     if not await rider_dispatch_allowed(order_number, recipient):
         return

-    pickup_time = fmt_uk_time(delivery_summary["pickup_time"])
-
-    header_text = f"{delivery_summary['distance']} miles, £{delivery_summary['rider_payout']}, @{pickup_time}"
-    wa_text = f"""
-    Pickup time - *{pickup_time}*
-    ... (lines 331-341, moved to ordelo/rider_messaging/offers.py)
-    """
     logger.info(f"Sending dispatch to rider {recipient} for order {order_number}")
     messenger = await for_dispatch(dispatch_id, rider_id=recipient, wa_client=_async_wa_client)
-    ref = await messenger.offer_job(
-        JobOffer(dispatch_id=dispatch_id, order_number=order_number, header=header_text, text=wa_text)
-    )
+    ref = await messenger.offer_job(job_offer(delivery_summary, dispatch_id))
```

Keep the `fmt_uk_time` import: the file uses it elsewhere too. Run
`tests/watomation/routers/test_delivery_hooks.py` unchanged; it must pass as it is.

### 5.4 `ordelo/rider_messaging/port.py`: one new method

```diff
     async def offer_closed(self, ref: MsgRef | None, order_number: str, reason: OfferClosedReason) -> None:
         ...
+
+    async def delete(self, ref: MsgRef | None) -> None:
+        """Remove one of OUR messages from the rider's chat (an older copy of a repeated offer). Telegram: delete_message;
+        a ref from another chat or channel, None, or a message already gone is ignored. WhatsApp: does nothing (the
+        Cloud API cannot delete sent messages). Never raises for 'already gone'."""
+        ...
```

### 5.5 Adapters

`ordelo/rider_messaging/telegram.py` (module docstring mapping table: add `delete  delete_message (older copy of a
repeated offer)` and note `notice` under `offer_job`):

```diff
     async def offer_job(self, offer: JobOffer) -> MsgRef:
         body = f"<b>{escape(offer.header, quote=False)}</b>\n{wa_to_html(offer.text.strip())}"
+        if offer.notice:  # repeated offer (ordelo/offer_reminders.py): one italic line on top
+            body = f"<i>{escape(offer.notice, quote=False)}</i>\n{body}"
         sent = await self.bot.send_message(self.tcid, body, reply_markup=rider_offer_kb(offer.dispatch_id))
         return tg_ref(self.tcid, sent.message_id)
+
+    async def delete(self, ref: MsgRef | None) -> None:
+        parsed = parse_tg_ref(ref)
+        if parsed is None or parsed[0] != self.tcid:
+            return
+        try:
+            await self.bot.delete_message(chat_id=self.tcid, message_id=parsed[1])
+        except TelegramBadRequest as e:  # already deleted by the rider, or too old: nothing left to remove
+            logger.info(f"telegram[rider]: {ref} not deleted: {e.message}")
```

`ordelo/rider_messaging/whatsapp.py`: add only this (no other change, so WhatsApp messages stay byte-identical):

```python
    async def delete(self, ref: MsgRef | None) -> None:
        # The WhatsApp Cloud API cannot delete a sent message; reminders are Telegram-only (D1).
        return None
```

`ordelo/rider_messaging/fake.py`:

```python
    async def delete(self, ref) -> None:
        self._record("delete", ref=ref)
```

### 5.6 `ordelo/dispatch_actions.py`: `record_offer_ref` fills an empty ref only

If the first offer's send is slow, its `record_offer_ref` could land **after** the first reminder moved the ref to copy 2,
leaving copy 2 with live buttons and the ref pointing at a deleted message. Guard it (the only caller is
`delivery_hooks.py` line 351, the first offer, on both channels):

```diff
 async def record_offer_ref(dispatch_id: int, ref: str | None) -> None:
-    """Store where the offer message is (delivery_dispatch.channel_msg_ref), so a closed offer can be edited (D49)."""
+    """Store where the FIRST offer message is (delivery_dispatch.channel_msg_ref), so a closed offer can be edited (D49).
+    Only fills an empty ref: a Telegram reminder (rider_offer_reminder_sent) may already have moved it to a newer copy."""
     if not ref:
         return
     await asyncio.to_thread(
-        lambda: client_ordelo.table("delivery_dispatch").update({"channel_msg_ref": ref}).eq("dispatch_id", dispatch_id).execute()
+        lambda: client_ordelo.table("delivery_dispatch").update({"channel_msg_ref": ref}).eq("dispatch_id", dispatch_id)
+        .is_("channel_msg_ref", "null").execute()
     )
```

Add a case to `tests/ordelo/test_dispatch_actions.py`: an existing ref is not overwritten.

### 5.7 New `ordelo/offer_reminders.py` (the deep module)

```python
"""
Telegram rider offer reminders (plans/rider-dispatch-alerts-plan.md, D1-D8).
    . remind(dispatch_id, n, of) -> str  send a fresh copy of one unanswered Telegram offer with "⏰ Still open · reminder n of
      of", move delivery_dispatch.channel_msg_ref to it, delete the previous copy, and redraw the new copy if the job was
      decided meanwhile. Outcome (logs/tests): sent | skipped:<reason> | closed:<reason> | stale | failed
    . escalate(order_number, after_secs, offered, declined) -> bool  one overwatch line when nobody accepted; once per order
      is guaranteed by the SQL ledger; re-checks the order first
    . WHEN an offer may be reminded is decided ONLY by SQL rider_offer_state(); this module never repeats the rules.
    . Never sends on WhatsApp: if the factory falls back (no rider bot / no tcid) the reminder is skipped.
    . Store seam: OfferReminderStore (SupabaseOfferReminderStore = the RPCs; tests use a fake with the same JSON shapes).
  Classes/Functions:
    . Snapshot, Swap, OfferReminderStore, SupabaseOfferReminderStore, reminder_notice, remind, escalate

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_offer_reminder_snapshot (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.snapshot()
  . rider_offer_reminder_sent (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.reminder_sent()
  . rider_offer_order_open (fn, ordelo_datamodels/dispatch/rider_offer_alert.sql): SupabaseOfferReminderStore.order_open()
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Protocol

from loguru import logger

from ordelo.rider_messaging import job_offer, messenger_for
from utils_common.order_management.test_order_dispatch import rider_dispatch_allowed


@dataclass(frozen=True)
class Snapshot:
    """rider_offer_reminder_snapshot(): the state AND everything needed to send."""
    state: str                      # open | quiet | closed
    reason: str | None              # closed: an OfferClosedReason; quiet: why (paused, ...)
    dispatch_id: int
    order_number: str | None = None
    rider_id: str | None = None
    tcid: int | None = None
    msg_ref: str | None = None
    offer: dict[str, Any] | None = None

    @classmethod
    def from_rpc(cls, d: dict[str, Any]) -> "Snapshot":
        return cls(d["state"], d.get("reason"), int(d["dispatch_id"]), d.get("order_number"), d.get("rider_id"),
                   d.get("tcid"), d.get("msg_ref"), d.get("offer"))


@dataclass(frozen=True)
class Swap:
    """rider_offer_reminder_sent(): swapped | stale | gone, plus the state AFTER the send."""
    result: str
    previous_ref: str | None
    state: str
    reason: str | None

    @classmethod
    def from_rpc(cls, d: dict[str, Any]) -> "Swap":
        return cls(d["result"], d.get("previous_ref"), d["state"], d.get("reason"))


class OfferReminderStore(Protocol):
    async def snapshot(self, dispatch_id: int) -> Snapshot: ...
    async def reminder_sent(self, dispatch_id: int, new_ref: str, expected_ref: str | None) -> Swap: ...
    async def order_open(self, order_number: str) -> bool: ...


class SupabaseOfferReminderStore:
    """The RPCs, over the service key (the ledger and functions are revoked from anon; CLAUDE.md rule 5)."""

    def __init__(self, client: Any = None):
        self._client = client

    def _c(self):
        if self._client is None:
            from config import client_ordelo_service
            self._client = client_ordelo_service
        return self._client

    async def _rpc(self, fn: str, params: dict[str, Any]) -> Any:
        return await asyncio.to_thread(lambda: self._c().rpc(fn, params).execute().data)

    async def snapshot(self, dispatch_id: int) -> Snapshot:
        return Snapshot.from_rpc(await self._rpc("rider_offer_reminder_snapshot", {"p_dispatch_id": dispatch_id}))

    async def reminder_sent(self, dispatch_id: int, new_ref: str, expected_ref: str | None) -> Swap:
        return Swap.from_rpc(await self._rpc(
            "rider_offer_reminder_sent", {"p_dispatch_id": dispatch_id, "p_new_ref": new_ref, "p_expected_ref": expected_ref}))

    async def order_open(self, order_number: str) -> bool:
        return bool(await self._rpc("rider_offer_order_open", {"p_order_number": order_number}))


def reminder_notice(n: int, of: int) -> str:
    return f"⏰ Still open · reminder {n} of {of}"


async def _quietly(what: str, aw: Awaitable[Any]) -> None:
    try:
        await aw
    except Exception:
        logger.exception(f"offer reminder: {what} failed")


async def remind(dispatch_id: int, n: int, of: int, *, store: OfferReminderStore | None = None, bot: Any = None) -> str:
    store = store or SupabaseOfferReminderStore()
    snap = await store.snapshot(dispatch_id)                                      # check BEFORE sending
    if snap.state != "open" or snap.offer is None or snap.tcid is None:
        return f"skipped:{snap.reason or snap.state}"
    if not await rider_dispatch_allowed(snap.order_number, snap.rider_id):         # TEST3100 -> overwatch riders only
        return "skipped:not_allowed"
    messenger = messenger_for(snap.rider_id, "telegram", snap.tcid, tg_bot=bot)
    if messenger.channel != "telegram":                                           # factory fell back to WhatsApp
        return "skipped:no_rider_bot"
    try:
        new_ref = await messenger.offer_job(replace(job_offer(snap.offer, dispatch_id), notice=reminder_notice(n, of)))
    except Exception:
        logger.exception(f"offer reminder {dispatch_id}: send failed")
        return "failed"
    swap = await store.reminder_sent(dispatch_id, new_ref, snap.msg_ref)           # move the ref; state AFTER sending
    if swap.result == "stale":                                                    # another reminder won: drop ours
        await _quietly("delete own copy", messenger.delete(new_ref))
        return "stale"
    await _quietly("delete previous copy", messenger.delete(swap.previous_ref))
    reason = swap.reason if swap.state == "closed" else None
    if reason is None:                                                            # a tap on the old copy in between
        again = await store.snapshot(dispatch_id)
        reason = again.reason if again.state == "closed" else None
    if reason:
        await _quietly("close new copy", messenger.offer_closed(new_ref, snap.order_number or "", reason))
        return f"closed:{reason}"
    logger.info(f"offer reminder {dispatch_id}: {n}/{of} sent to {snap.rider_id[-4:]}")
    return "sent"


async def escalate(order_number: str, after_secs: int, offered: int, declined: int, *,
                   store: OfferReminderStore | None = None, alert: Callable[[str], Awaitable[None]] | None = None) -> bool:
    store = store or SupabaseOfferReminderStore()
    if not await store.order_open(order_number):                                  # accepted meanwhile: say nothing
        return False
    if alert is None:
        from channels.telegram.ops_alerts import alert_ops as alert
    mins = f"{after_secs // 60} min" if after_secs % 60 == 0 else f"{after_secs} s"
    await alert(f"⚠️ {order_number}: no rider has accepted after {mins} ({offered} offered on Telegram, {declined} declined)")
    return True
```

Notes for the implementer:
- `messenger_for(..., tg_bot=None)` imports `config.rider_bot`; the route already refuses without it. Tests use
  `use_messenger(RecordingRiderMessenger(channel="telegram"))` (fake channel must be `"telegram"` or `remind` skips).
- Mask phones in logs (`[-4:]`, like `ops_alerts.mask`).
- Never call `client_ordelo_service` directly from an `async def` without `asyncio.to_thread` (CLAUDE.md).

### 5.8 New `watomation/routers/rider_offer_alerts.py` + registration

```python
"""
Rider offer reminder ingress (thin route; logic in ordelo/offer_reminders.py).
    . POST /rider-hooks/offer-alerts, called every ~5 s (only when something is due) by job_rider_offer_alerts()
      (ordelo_datamodels/dispatch/job_rider_offer_alerts.sql) through http_post
    . Body: {"event_type", "timestamp", "reminders": [{dispatch_id, n, of}], "escalations": [{order_number, after_secs, offered, declined}]}
    . 503 when the rider bot is not configured: non-2xx keeps the checkpoints pending, so nothing is lost
    . Answers 200 at once and does the Telegram work in background tasks
    . The database is re-checked before every send (rider_offer_reminder_snapshot), so a replayed or forged call cannot
      remind an offer that is not open; like the other SQL-triggered hooks this route carries no secret

Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . offer_alerts(): job_rider_offer_alerts() in ordelo_datamodels/dispatch/job_rider_offer_alerts.sql via pg_cron 'job_rider_offer_alerts' (5 seconds)
(end of database objects)
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ordelo import offer_reminders

router = APIRouter(tags=["rider-hooks"])


class Reminder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dispatch_id: int = Field(ge=1)
    n: int = Field(ge=1)
    of: int = Field(ge=1)


class Escalation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_number: str = Field(min_length=1, max_length=100)
    after_secs: int = Field(ge=1)
    offered: int = Field(default=0, ge=0)
    declined: int = Field(default=0, ge=0)


class OfferAlertsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reminders: list[Reminder] = []
    escalations: list[Escalation] = []


@router.post("/rider-hooks/offer-alerts", include_in_schema=False)
async def offer_alerts(payload: OfferAlertsPayload, background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_rider_offer_alerts() in ordelo_datamodels/dispatch/job_rider_offer_alerts.sql via pg_cron 'job_rider_offer_alerts' (5 seconds)
    """
    from config import rider_bot

    if rider_bot is None:
        raise HTTPException(503, "rider bot not configured")
    for r in payload.reminders:
        background_tasks.add_task(offer_reminders.remind, r.dispatch_id, r.n, r.of)
    for e in payload.escalations:
        background_tasks.add_task(offer_reminders.escalate, e.order_number, e.after_secs, e.offered, e.declined)
    return {"status": "accepted", "reminders": len(payload.reminders), "escalations": len(payload.escalations)}
```

`watomation/fapp_ordelo_agent.py` (next to the `pause_hooks` line, about line 173):

```diff
 app.include_router(pause_hooks.router)  # POST /pause-hooks/sweep (job_pause_sweep, R5-R6)
+app.include_router(rider_offer_alerts.router)  # POST /rider-hooks/offer-alerts (job_rider_offer_alerts)
```

…and add `rider_offer_alerts` to the import on line 45: `from watomation.routers import pause_hooks, rider_offer_alerts, telegram_order_alerts, telegram_webhook, web_hooks`.

### 5.9 Offer-text fixture (for the golden and the SQL ↔ Python contract)

```python
ROW = {"dispatch_id": 41, "order_number": "STRK-TEST-101500", "rider_id": "447448440754", "rider_payout": 5,
       "vehicle_type": "bicycle", "distance": 1.5, "pickup_time": "2026-10-26T19:30:00+00:00", "rest_name": "Strk Kitchen",
       "rest_address": "40b The Walnuts High Street Orpington BR6 0TW", "customer_name": "Test Customer",
       "customer_address": "1 Test Street Orpington BR6 0TW"}
```

`rider_offer_reminder_snapshot()` returns `offer` with exactly these keys. In jsonb, `rider_payout 5.0` serialises as `5`
and `pickup_time` as ISO with an offset, the same as the trigger's `row_to_json`. That's checked in the SQL test (6.1).

## 6. Tests

### 6.1 Offline and isolated-database

| Test file | What it proves |
|---|---|
| `tests/ordelo/test_rider_offers_golden.py` (new) | `job_offer(ROW)` gives **byte-identical** `(header, text)` to the golden captured from the pre-refactor `wa_send_delivery_dispatch_request_to_rider`. **WhatsApp regression guard** |
| `tests/ordelo/test_rider_messaging.py` (extend) | Telegram `offer_job` with `notice` puts one `<i>` line on top; without it, the output is unchanged. `delete` calls `delete_message` for its own chat, ignores other chats / WhatsApp refs / None, and swallows `TelegramBadRequest`. WhatsApp `delete` makes no client call |
| `tests/ordelo/test_offer_reminders.py` (new) | With a `FakeOfferReminderStore` (same JSON as the RPCs) and `RecordingRiderMessenger(channel="telegram")`: `open` → `offer_job` (notice "reminder 3 of 7"), `reminder_sent(expected=snap.msg_ref)`, `delete(previous)` → `sent`. `quiet` / `closed` / no tcid / no offer → no call. `rider_dispatch_allowed` False → `skipped:not_allowed`. Fake channel `whatsapp` → `skipped:no_rider_bot`. `stale` → `delete(new)` only. `swapped` + `closed/taken` → `delete(prev)` + `offer_closed(new, "taken")`. Second snapshot `closed/accepted` → `offer_closed(new, "accepted")`. `offer_job` raises → `failed`, no `reminder_sent`. `delete` raising doesn't stop the close. `escalate`: open → one alert text; closed → none |
| `tests/watomation/routers/test_rider_offer_alerts.py` (new) | 503 without `rider_bot`; with it, one background task per reminder and per escalation; extra keys ignored; `dispatch_id` 0 → 422 |
| `tests/ordelo/test_dispatch_actions.py` (extend) | `record_offer_ref` uses `.is_("channel_msg_ref", "null")` |
| `tests/sql/test_rider_offer_alerts_sql.py` (new; loads the two owner files) | Covers every row of 3.4 through `rider_offer_state()`. The job: seeds only Telegram + open + <15 min; one row per offset with `n/of_n`; collapse (10 superseded, 20 sent); supersede-before-sent order; cancel on Decline / pause / off shift / inactive / no tcid / another job / another rider's Accept / assignment / summary timedout / declined / dispatch deleted; escalation once per order, cancelled by an Accept, counts `offered/declined`; blank config cancels all pending and seeds nothing; offsets `0`/negative ignored; POST 500 → `false` and still pending; payload JSON shape. `rider_offer_reminder_sent` swapped / stale / gone, plus two threads racing (one swapped, one stale, mirror `test_order_cards_sql.py` threading). Snapshot `offer` keys and types equal one `bulk_dispatch` item. Grants revoked; the file applies twice |
| `tests/sql/test_rider_offer_alerts_migration_sql.py` (new) | The migration applies twice on the post-R6 shape and VERIFY returns `1 / true / 5 / 0 / '10,20,30,45,60,90,120'` (pattern: `test_rider_telegram_r5_r6_migration_sql.py`) |
| `tests/sql/test_restaurant_notices_script_sql.py` (extend) | STAGES list gains `"STAGE 2c"` after `"STAGE 2b"` (line 110). STAGE 2c runs read-only. STAGE 0 deletes `rider_offer_alert` rows only for `STRK-TEST-%` (add the table to the list at line 69) |
| `tests/test_datamodels_standard.py`, `ruff check .`, the full `pytest` | Headers, guide freshness, lint |

`tests/sql/conftest.py`: add `"rider_offer_alert.sql"` and `"job_rider_offer_alerts.sql"` to `MIGRATION_FILES` **after**
`"pauses.sql"` and `"rider_master.sql"`. `rider_offer_state()` is plpgsql, so the order only matters for the SQL-language
`rider_offer_order_open()`, which needs the dispatch tables from `minimal_schema.sql`.

`tests/sql/minimal_schema.sql`: the test shape lacks live columns that the snapshot and seed read. Add (test defaults,
live has them):

```diff
 CREATE TABLE IF NOT EXISTS public.delivery_dispatch (
     dispatch_id serial PRIMARY KEY,
     order_number varchar(100) NOT NULL,
     rider_id    varchar(12) NOT NULL,
+    rider_payout double precision NOT NULL DEFAULT 5,       -- live: NOT NULL, no default
+    vehicle_type varchar(15) NOT NULL DEFAULT 'bicycle',     -- live: NOT NULL, no default
+    distance    double precision NOT NULL DEFAULT 1.5,       -- live: NOT NULL, no default
     status      varchar(50) NOT NULL CHECK (...),
     status_update_dtts timestamp,
     reason_for_decline text,
+    dtts        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
```

…and `rest_address text`, `customer_name text` on `delivery_summary` (check first; the scratch run needed them).

### 6.2 Live test on STRK (`test_restaurant_notices.sql` only, D9)

Prerequisites as today (STAGE 0 already sets `lohith` and `lohithNwg` to `channel = 'telegram'`, town `dummy`, in shift, in
`overwatch_list`). Plus: the migration applied, the code deployed, `job_rider_offer_alerts` scheduled.

**STAGE 0 diff** (add one line to the VALUES list, before `delivery_dispatch`):

```diff
         ('public.t_order_alerts',                $q$DELETE FROM public.t_order_alerts WHERE order_number LIKE 'STRK-TEST-%'$q$),
+        ('public.rider_offer_alert',             $q$DELETE FROM public.rider_offer_alert WHERE order_number LIKE 'STRK-TEST-%'$q$),
         ('public.t_sent_messages',               $q$DELETE FROM public.t_sent_messages
```

**New STAGE 2c** (insert between STAGE 2b and STAGE 3; read only; the marker format is what the offline test splits on):

```sql
-- ===== STAGE 2c: RIDER OFFER REMINDERS (Telegram; watch, read only) =====
-- Run after STAGE 2b while the offer is unanswered, and re-run it between steps. Telegram riders get the offer again at
-- +10/+20/+30/+45/+60/+90/+120 s (ordelo_config RIDER_OFFER_ALERT_OFFSETS_SECS); each new copy replaces the previous one,
-- so the chat shows ONE live copy and the phone buzzes each time. Try, one per fresh order (STAGE 0, 1, accept, 2b):
--   a) ignore it ~35 s: reminder rows n=1..3 'sent'; the chat shows one copy "⏰ Still open · reminder 3 of 7"
--   b) second rider taps Decline: that rider's pending rows 'cancelled'; the first rider keeps getting reminders
--   c) a rider sends /off in @ByteloopRidersBot: their pending rows 'cancelled' by the next run (reminder_state 'paused')
--   d) one rider taps Accept: every pending row of the order 'cancelled' within ~5 s; the other rider's copy becomes
--      "Taken by another rider" after the assignment, the winner's "The job is yours"; then go on with STAGE 3
--   e) ignore it 2 min: the escalation row 'sent' and overwatch WhatsApp gets
--      "⚠️ STRK-TEST-…: no rider has accepted after 2 min (N offered on Telegram, M declined)", once
-- WhatsApp riders: no rows at all (reminders are Telegram only).
SELECT a.kind, a.dispatch_id, r.rider_name, a.n, a.of_n, a.offset_secs, a.due_at, a.status, a.swept_at
  FROM public.rider_offer_alert a LEFT JOIN public.rider_master r ON r.rider_id = a.rider_id
 WHERE a.order_number LIKE 'STRK-TEST-%'
 ORDER BY a.kind DESC, a.dispatch_id, a.offset_secs;
SELECT d.dispatch_id, r.rider_name, d.channel, d.status, d.channel_msg_ref,
       public.rider_offer_state(d.dispatch_id) AS reminder_state
  FROM public.delivery_dispatch d JOIN public.rider_master r ON r.rider_id = d.rider_id
 WHERE d.order_number LIKE 'STRK-TEST-%'
 ORDER BY d.dispatch_id;
```

Also add a STAGE 2c row to the stage table in `docs/live-order-test-harness.md` and the stage list in the script's own
header comment. In the PREREQUISITES CHECK, add `(SELECT count(*) FROM pg_proc WHERE proname = 'job_rider_offer_alerts') AS
offer_reminders_present -- 1`, and add `'job_rider_offer_alerts'` to the commented cron query.

**WhatsApp regression pass** (the owner's priority): this change touches WhatsApp only through the offer builder (5.2)
and the no-op `delete`. Proof: the golden test (6.1), the unchanged `test_delivery_hooks.py`, and the existing WhatsApp pass
in `docs/live-order-test-harness.md` (STAGE 1-10 tapping only on WhatsApp). Restaurant WhatsApp prompts and receipts must
be unchanged. Record each step as `boundary | action | observed | label | not verified`.

## 7. Races (and why each ends correctly)

| Race | Outcome |
|---|---|
| Two workers remind the same offer | `rider_offer_reminder_sent` locks the row; one gets `swapped`, the other `stale` and deletes its own copy. One live copy |
| Assignment happens while a reminder is being sent | `close_open_offers` edits whichever ref it read. If it read the old one, the reminder's `reminder_sent` returns `closed/taken`: the reminder deletes the old copy and redraws the new one "Taken". If it read the new one, it edits it itself |
| The rider taps Accept on the old copy while the reminder sends | The tap edits the old copy ("Accepted…"); the reminder sees `closed/accepted` (after-send state or the re-check) and redraws its new copy the same way, then deletes the old |
| The rider taps the old copy after the swap but before the delete | The old copy is deleted. The new copy may still show buttons for up to ~5 s, until the assignment (`close_open_offers` winner → "The job is yours") or the missed notice ("Taken", via `dc.msg_ref` = the new copy). A second tap is harmless (`respond_to_offer`) |
| The first offer's `record_offer_ref` lands after the first reminder | Prevented by 5.6 (fills an empty ref only) |
| The job runs while the route is down | POST non-2xx → `false`, rows stay pending; the next success sends only the latest due reminder per offer |
| The rider deleted the chat message or blocked the bot | `delete` / `edit` raise `TelegramBadRequest` / `TelegramForbiddenError`; logged and skipped. Blocked → `offer_job` raises → `failed`; the ledger already says `sent` (at-least-once means at least one POST, as in `t_order_alerts`) |

## 8. Rollout (the owner runs every SQL step)

1. PR 1: 5.1-5.6, the golden test, adapter tests. No behaviour change. Merge, deploy, run the WhatsApp regression pass.
2. PR 2: the owner files (section 4), `minimal_schema.sql` and `conftest.py`, the SQL tests, the guide rebuild.
3. PR 3: 5.7-5.8 and their tests.
4. PR 4: `test_restaurant_notices.sql` STAGE 0 + 2c, the script test, `docs/live-order-test-harness.md`, docs (section 9).
5. Owner: migration STEP 0-4 → deploy PR 2-4 → `drift_check.py` → STEP 6 `cron.schedule` → STAGE 0, 1, accept + pickup,
   2b, 2c (a-e) on STRK → WhatsApp regression pass.
6. Off switch if anything misbehaves: set `RIDER_OFFER_ALERT_OFFSETS_SECS` to `''` (the next run cancels everything pending).

## 9. Docs to update in the same PRs

- `CONTEXT.md` → under `### Offer`: add **Offer reminder**: "a repeat of an unanswered Telegram offer at the configured
  offsets, replacing the previous copy; stops when any rider of the order accepts or this rider can no longer take it.
  _Avoid_: nag, re-dispatch (a re-dispatch is a new offer)." Also `GLOSSARY.md` if it lists offer terms.
- `docs/delivery_process.md`, phase 4 "Rider assignment": one paragraph and the config key in the config table (near
  line 735).
- `docs/telegram-layer.md` (rider bot part) and `plans/telegram-rider-bot-plan.md`: a short note that offers now repeat
  (link here). The next free decision number there is **D55** if you record D1-D8 in that plan's numbering.
- `docs/to-do.md`: (a) the `job_create_dispatch.sql` header mismatch (D10); (b) `rider_offer_alert` retention:
  `t_housekeeping()` is not scheduled on live, so add the table to it when housekeeping is scheduled; (c) an escalation
  fires once per order, even after a re-dispatch.

## 10. Not in this change

Staggered dispatch. WhatsApp rider reminders. Ledger retention (about 8 small rows per Telegram offer; see 9 (b)). A
per-restaurant override of the offsets.
