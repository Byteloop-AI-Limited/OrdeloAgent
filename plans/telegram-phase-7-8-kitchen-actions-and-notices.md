# Telegram phases 7–8: kitchen actions (Ready, adjust pickup) and restaurant notices on both channels

**Repository:** `OrdeloAgent` (plus a to-do in `restaurant-agents`). **Written:** 15 October 2026, after a grilling session with
the owner (questions 1–10 below are the record). **Status (15 Oct 2026):** ✅ 7a, 7b, 7c, 7d offline prep and 8a built and verified offline; ⏳ 7d and 8b (live checks) and the
step 9 sweep wait for the owner (migration applied, `job_t_receipt_refresh` scheduled, deploy). See "As built" below.
**Main plan:** [`telegram-rest-admin-scaffold-plan.md`](telegram-rest-admin-scaffold-plan.md) (rules 1–8, D11–D27, verification loop).
This file holds ONLY phases 7 and 8. When they are done, fold a short summary back into the main plan and move this file to
`plans/archive/`.

## As built (differences from the text below; the text below is the original plan)

- **SQL files moved out of `migrations/`** (they are the authoritative description of how the feature works, not one-off schema changes):
  `ordelo_datamodels/telegram/` ← `create_t_inbox.sql`, `create_t_invites.sql`, `create_t_order_alerts.sql`;
  `ordelo_datamodels/restaurant_admin/` ← `restaurant_order_decision.sql`, `restaurant_ready_adjust_notices.sql`. File names are unchanged.
  Paths updated in code docstrings, docs, tests (`tests/sql/conftest.py` now finds a file by name with `sql_path()`), CLAUDE.md / agents.md / the
  database-operations skill; "See also" headers added to the related SQL files. Older text below still says `migrations/`.
- **DDL fallout (found live):** the migration adds 6 columns to `delivery_summary` and 2 to `takeaway_summary`; `init_delivery()` /
  `init_takeaway()` (`RETURNS TABLE` + `RETURNING *`) then failed with 42804 (35 returned vs 29 expected) and no order could be created.
  Fixed by listing the columns (table-qualified) in both files; `tests/test_sql_returning_star.py` guards against `RETURNING *` in
  any `RETURNS TABLE` function. **Re-run `init_delivery.sql` and `init_takeaway.sql` after the migration.** My earlier "Nothing is dropped or
  rewritten / safe to apply alone" claim was wrong for these two functions; the isolated-database tests never created an order through them.
- **Review fixes (after the first code review):**
  - *Receipt wording:* the status line says `✅ Marked ready by …`; the tapper's toast says `Marked ready — rider/customer told`
    (or the could-not-be-messaged alert). Receipts never claim a notification succeeded: the database records readiness, not delivery of the nudge.
  - *Temporary read failure:* `_snapshot_quietly` returns an `_UNREAD` sentinel, distinct from "order gone". Refresh leaves such copies
    claimed (the 30 s re-offer retries) instead of replacing and closing them.
  - *Stale sends:* `Receipts.send` and `t_receipt_sent` ignore a send whose dispatch is `rider_cancelled`/`gone`, so a delayed old-rider
    event can no longer delete the current rider's receipt.
  - *D35 for cancelled copies:* `t_receipt_sent` also takes previous copies closed as `edited` (the cancelled-rider view), so they are deleted when the new rider's receipt arrives.
  - *Atomic lifecycle gate:* `restaurant_order_ready` / `restaurant_order_adjust_pickup` read inflight/dispatch `FOR SHARE`, so pickup or
    cancellation cannot change them between the check and the write. **The migration must be re-applied** (idempotent `CREATE OR REPLACE`).
  - *Deferred, with reasons:* persisting the nudge outcome, a shared copy-management helper for cards and receipts, a slimmer notifier,
    and folding `job_t_receipt_refresh` into the order-alert sweep.

- The migration has **12 functions** (not the count first written): the shared and `t_` Ready / adjust RPCs, the five receipt
  functions, the two notice functions and `job_t_receipt_refresh()`. `t_receipts_stale` also ignores receipts older than 3 days.
- **Takeaway test orders** use the `TEST3100` item mechanism (`payment_mode='test'`; delivery goes only to `overwatch_list`
  riders; takeaway creates no dispatch). The "refused-port `payment_uri`" idea in the first draft was invalid and is gone.
- **Both owner decisions applied:** the auto-accept notice is sent AFTER the UPDATE for delivery and takeaway on both channels
  (a failed send can no longer stop the auto-accept); the takeaway stage defaults to `payment_status='test_no_payment'`, with
  the optional stage 8b `pay_at_rest`.
- `POST /telegram/rest-admin/order-alerts` now answers with a `receipts` count next to the card counts.
- Tests: `tests/conftest.py` has an autouse `quiet_telegram_notices` fixture (the Telegram side of `restaurant_notifier` does
  nothing unless a test installs one with `use_adapters`).
- **Live-script fix (found in the first live run):** fake orders use the REAL `restaurant_master.rest_id` of STRK (the order
  webhooks look the restaurant up by `rest_id`; a made-up id made the payload invalid), and the rider job (`delivery_detail`)
  is no longer created in STAGE 1 but in the new **STAGE 2b**, run after Accept + pickup time (as `process_delivery()` does in
  production); before that the dispatch hook crashed on a missing pickup time.
- Step 8a gate (offline): 975 passed, 224 skipped, 1 known failure (`test_restaurant_master_get_admins_fetches_live_column`);
  ruff: no new warnings in touched files (remaining ones are pre-existing).

Read in this order: §1 scope → §2 decisions → §3 design → §4 migration → §5 Python → §6 tests → §7 fake-row script →
§8 steps with verification → §9 docs → §10 operator steps → §11 risks.

---

## 0. Baseline (taken 15 Oct 2026, before any change): the regression gate

Every step in §8 ends by re-running these and comparing against this table. "Nothing broken" means: the same failures as
below, no new ones, and every new test passing.

| Suite | Command | Result now | Known failures |
|---|---|---|---|
| Offline (everything except SQL) | `pytest -q tests` | **853 passed, 140 skipped, 1 failed** | `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column` (pre-existing, fails on a clean checkout) |
| Isolated database | `PGTZ=UTC ORDELO_TEST_DB_URI=postgresql://postgres@localhost:5433/postgres pytest -q tests/sql` | **133 passed, 7 failed** | all 7 in `tests/sql/test_order_test_script_sql.py`, see step 0 |

Why the 7 fail today (committed in `e1d55c6`, not caused by this work):
1. `ordelo_datamodels/test_support/test_create_t_order_alerts.sql` now starts with an **unconditional**
   `INSERT INTO public.t_invites ... status 'claimed'` (the old "Fix B" shortcut). The test fixture already has a claimed STRK
   invite for tuid 111, so it violates `t_invites_one_claim_per_user_rest`. On the shared database it adds a new claimed
   STRK invite row on every run.
2. Its final `SELECT` reads `s.pickup_date`, which `tests/sql/minimal_schema.sql` does not have (the live table does:
   `ordelo_datamodels/delivery/delivery_summary.sql`, `pickup_date DATE NOT NULL DEFAULT CURRENT_DATE`).

Also found: two SQL tests (`test_order_taps_sql.py::test_pickup_states`,
`test_restaurant_decision_sql.py::test_pickup_twice_is_already_set_and_keeps_first_time`) fail when the Postgres session time
zone is not UTC. They compare ISO strings. Step 0 makes `tests/sql/conftest.py` pin `SET TIME ZONE 'UTC'` on every connection, so
`PGTZ` stops mattering.

How the baseline was run (the Mac's `.venv` is macOS-only, so it cannot run in the Linux sandbox):
- Offline: a separate Python 3.13 environment built from the repo's `uv.lock`
  (`UV_PROJECT_ENVIRONMENT=$HOME/venv-ordelo uv sync --frozen --python 3.13`), `PYTHONPATH=$PWD`.
- SQL: a throwaway Postgres 16 on port 5433, started with
  `initdb -A trust` + `pg_ctl -o '-p 5433 -k /tmp' start`.
- On your Mac: `source .venv/bin/activate && export PYTHONPATH="$PWD" && envLoad && pytest -q tests`. For the SQL suite,
  start pgserver as `tests/sql/conftest.py` describes, then set `ORDELO_TEST_DB_URI`.

---

## 1. Scope (settled in Q1, Q2, Q7)

| # | What | Today (WhatsApp) | Telegram after this plan | Phase |
|---|---|---|---|---|
| A | Confirmation request | `delivery_hooks._handle_restaurant_unconfirmed`, takeaway twin | already done (order card, phases 4–5) | — |
| B | Pickup-time prompt | `_handle_restaurant_accept` ×2 | already done (card pickup buttons) | — |
| **D** | **Kitchen receipt, delivery**, sent when the rider accepts (`delivery_inflight` INSERT, status `assigned`), with buttons **Ready – notify rider**, **+10**, **+20** | `delivery_hooks.delivery_inflight_graph_init_hook` step 3 → `wa_senders.admin_order_reciept` | new pinging message, reply to the card, buttons work, copies follow the DB | 7 |
| **E** | **Kitchen receipt, takeaway**, sent when the pickup time is set, with button **Ready – notify customer** | `takeaway_hooks.pickup_time_updated_hook` step 3 → `wa_senders.takeaway_admin_order_receipt` | same | 7 |
| **C** | Timeout auto-accept notice | `delivery_hooks._handle_restaurant_timedout`, `takeaway_hooks._handle_restaurant_timedout` | new pinging notice, reply to the card (the card is still edited silently as today) | 8 |
| **F** | Rider pickup alerts to admins (−10 heads-up, then chases) | `delivery_hooks._process_rider_pickup_alerts` → `wa_senders.notify_rest_admins_rider_alert` | notice, reply to the receipt | 8 |
| **H** | Delivery completed | `ordelo/agents/rider_agent.py` `verify_customer_confirmation_code` (~line 1152) | notice, reply to the receipt; the receipt also redraws to "Delivered" | 8 |
| **I** | Customer feedback | `watomation/routers/customer_hooks._notify_feedback_admins` | standalone notice | 8 |
| G | Rider nearby restaurant + code | `location_hooks.notify_rider_location_event` (`rid == 'rest'`) | **out of scope**: legacy OwnTracks path, unused (owner, Q1) | — |
| J | Admin availability enquiry | `admin_availability_enquiry_hook` → `enquire_admin_availability` | **out of scope**: belongs with R2 | — |
| — | Dead code | `wa_senders.admin_delivery_driver_nearby`, `admin_delivery_complete_notification` (loop over `REST_MASTER = "dummy"`, no callers) | **deleted** (with `tests/regressions/test_p7_wa_senders.py::test_admin_delivery_driver_nearby` / `::test_admin_delivery_complete_notification`) | 8 |

**WhatsApp stays operational and unchanged**, except for three deliberate fixes the owner approved:
- **Q3:** a second Ready tap no longer nudges the rider again; it replies "Already marked ready by …".
- **Q4:** a repeat adjust tap that changes nothing no longer re-notifies the rider, and an adjust no longer overwrites
  `restaurant_admin`.
- **§3.6:** the delivery auto-accept WhatsApp notice moves after its `UPDATE`. This is an open point for owner review.

`restaurant-agents` sends nothing to restaurant admins. Its leftover admin code is listed for later removal in
`restaurant-agents/docs/to-do.md` ("Remove leftover restaurant-admin code") and its new `CLAUDE.md`. Nothing is removed in
this plan.

---

## 2. Decisions (numbering continues the main plan's D11–D27)

| # | Decision | From |
|---|---|---|
| D28 | **Both channels, always.** Every restaurant-facing notice in scope goes to WhatsApp (to `restaurant_master.admins`, exactly as today) **and** Telegram (to `t_order_card_destinations`, D14). Telegram is not a fallback. WhatsApp text, buttons and callback JSON stay byte-for-byte the same. | Q2 |
| D29 | **One port:** `utils_common/notify/restaurant_notifier.py`, interface `await notify(notice)`. A WhatsApp adapter calls the existing `wa_senders` functions. A Telegram adapter calls the rest-admin bot's `Receipts` / `Notices`. Both run in parallel, are isolated from each other, and never raise to the caller. | Q2 |
| D30 | **Ready is a shared RPC; the first tap per dispatch wins.** `restaurant_order_ready()` records `ready_at/by/dispatch_id` atomically. The follow-up (rider nudge or customer event) runs in Python only on `ok`. WhatsApp is switched to it: a second tap replies "Already marked ready by X" instead of re-nudging. | Q3 |
| D31 | **The Ready / adjust gate lives in SQL:** an inflight row for the order, and its `delivery_dispatch.status` not in `('pickedup','completed')`. This is the same rule as `ordelo/delivery_progress.check_delivery_progress`. Takeaway gate: `status = 'pickup_confirmed'`. | Q3 |
| D32 | **Adjust pickup:** the target is relative to `pickup_time_initial` (set once, on the first adjust). WhatsApp keeps sending the absolute ISO time its buttons carry; Telegram sends minutes. If the target equals the current pickup, return `unchanged` with no write and no rider re-notify. Record `pickup_adjusted_by/at`; never overwrite `restaurant_admin`. Delivery only. | Q4 |
| D33 | **The Telegram kitchen receipt** is a new message that pings, sent as a reply to the latest order-card copy in that chat. It carries every WhatsApp field except the dead live-location link: restaurant code (prominent), pickup, rider name and ID, items with modifiers, small-order fee, total, notes, customer address and phone. Takeaway also shows `💷 Pay at restaurant — collect £X` when `payment_status = 'pay_at_rest'`. | Q5, Q6 |
| D34 | **Receipt copies follow the database.** Ledger rows `t_sent_messages.kind = 'receipt'` hold a receipt status key from SQL `t_receipt_status()`. Its own 5-second job `job_t_receipt_refresh()` posts stale receipts to the existing `/telegram/rest-admin/order-alerts` route, which edits them (silently). | Q5 |
| D35 | **Re-dispatch:** old receipt copies show "Rider X cancelled — finding a new rider" without buttons. The new rider's receipt pings and deletes the older receipt copies in that chat. Ready is **per dispatch** (`ready_dispatch_id`), so the new rider can be told. The adjusted pickup survives. | Q8 |
| D36 | **Plain notices (C, F, H, I):** sent to the D14 destinations, replying to the card (C) or receipt (F, H) when one exists, else standalone (I). Each copy is recorded as a closed `kind = 'notice'` ledger row (audit; purged after 30 days by `t_housekeeping`). No retries. C goes to Telegram only after the auto-accept `UPDATE` succeeded. | Q7 |
| D37 | **Fake-row tests** use `STRK-TEST-*` orders in town **`dummy`**: only in-shift `rider_master` rows with `town = 'dummy'` get dispatch offers (`get_available_riders` filters on `LOWER(town)`). Customer, admin and riders are all the owner. Add a second dummy rider to test the accept race. | Q9 |
| D38 | **One migration** (`restaurant_ready_adjust_notices.sql`, header in the house template). The isolated-database test sits alongside it, so the SQL can be checked without running any service. | Q3, Q10 |

---

## 3. Design

### 3.1 The flow after this change

```
RIDER ACCEPTS (job_assign_dispatch → INSERT delivery_inflight)
  └─ delivery_inflight_whook → POST /delivery-hooks/delivery-inflight-graph-init
       step 3 (was: admin_order_reciept)  →  restaurant_notifier.notify(KitchenReceipt(order, dispatch_id, rider))
            ├─ WhatsApp adapter → wa_senders.admin_order_reciept(delivery_summary, rider_master)        (unchanged)
            └─ Telegram adapter → Receipts.send(OrderRef, dispatch_id)
                                    → t_receipt_snapshot → send (reply to card) per destination → t_receipt_sent
                                    → delete older receipt copies in that chat (D35)

ADMIN TAPS READY
  WhatsApp  /AdminCollectionReady → on_callback_wa_handler.admin_collection_ready
                                     → restaurant_actions.ready(ref, WhatsAppActor(phone))
  Telegram  ord:<no>:d:rdy:0      → orders router → Receipts.tap → restaurant_actions.ready(ref, TelegramActor(bot, tuid))
       restaurant_actions.ready → RPC restaurant_order_ready | t_order_ready      (first tap per dispatch wins, D30/D31)
            ok → delivery: run_rider_agent_w_custom_msg(rider_id, human_msg="call `tool notify_food_ready_for_pickup` …")
                 takeaway: customer_notifier.publish(…"ready_for_collection"…)                      (same as today)
       then Telegram copies: Receipts.refresh(order) right after a Telegram tap; the 5-s job catches WhatsApp taps

ADMIN TAPS +10 / +20
  WhatsApp  /AdminAdjustPickupTime10|20 (absolute ISO) ─┐
  Telegram  ord:<no>:d:adj:10|20 (minutes)        ──────┴─ restaurant_actions.adjust_pickup → RPC restaurant_order_adjust_pickup
            ok → UPDATE pickup_time + restaurant_confirmation_status='restaurant_pickuptime_adjusted'
               → trigger_restaurant_updates → /delivery-hooks/restaurant-confirmation-request
               → _handle_restaurant_pickuptime_adjusted → rider agent `notify_pickup_time_adjusted`   (unchanged path)
            unchanged → no write, no rider message

pg_cron 5 s → job_t_receipt_refresh() → POST /telegram/rest-admin/order-alerts {"receipts":[{order_number, order_type}]}
            → Receipts.refresh(order) → t_receipts_take → edit/delete → t_order_card_mark   (reuses the phase-4 claim/mark)
```

### 3.2 Modules (codebase-design vocabulary: one deep module per concern, interface = test surface)

| Module | Interface (all a caller learns) | Hides | New/changed |
|---|---|---|---|
| `utils_common/order_management/restaurant_actions.py` | `ready(ref, actor) -> ActionOutcome`, `adjust_pickup(ref, actor, *, target=None, minutes=None) -> ActionOutcome`, values `OrderRef`, `WhatsAppActor(phone)`, `TelegramActor(bot_key, tuid)` | which RPC (shared vs `t_` wrapper), result parsing, **the follow-up** (rider nudge / customer event) so both channels behave identically, `asyncio.to_thread` | new; sibling of `restaurant_decision.py` |
| `utils_common/notify/restaurant_notifier.py` | `notify(notice) -> None`; notice values `KitchenReceipt`, `TakeawayReceipt`, `AutoAccepted`, `RiderAlert`, `DeliveryCompleted`, `Feedback` | both adapters, parallel fan-out, per-channel failure isolation, Telegram bot lookup | new; sibling of `customer_notifier.py` |
| `channels/telegram/rest_admin/receipts/` | `Receipts(bot, bot_key)`: `send(order, dispatch_id)`, `refresh(order)`, `tap(query, action)` | snapshot, pure `Receipt` model and views, reply target, ledger, re-dispatch deletion, toasts, Telegram error mapping (reuses `order_cards/io.TelegramIO`) | new; shaped like `order_cards/` |
| `channels/telegram/rest_admin/notices.py` | `Notices(bot, bot_key)`: `send(rest_ref, text_html, *, order=None, reply_to="card"/"receipt"/None)` | destinations, reply target, ledger audit row, isolation | new |
| `channels/telegram/callbacks.py` `OrderAction` | `a` adds `"rdy"`, `"adj"`; `m` = 10/20 for `adj` | — | changed |
| `channels/telegram/rest_admin/orders.py` | one handler: `acc/dec/pk` → `OrderCards.tap`, `rdy/adj` → `Receipts.tap` | — | changed |
| `channels/telegram/bots.py` | `TelegramBot.receipts`, `dp["receipts"]` | — | changed |
| `watomation/routers/telegram_order_alerts.py` | payload gains `receipts: [{order_number, order_type}]` | — | changed (old payloads still valid: `extra="ignore"`) |

The deletion test: remove `restaurant_actions` and the "ready → nudge rider" rule reappears in the WhatsApp handler and the
Telegram tap (two copies that can drift). Remove `restaurant_notifier` and the both-channels rule is repeated at six call
sites. Both modules earn their place.

**Seams that vary (two adapters each, so they are real seams):**
- the notifier's WhatsApp and Telegram adapters;
- the action actor (WhatsApp phone vs Telegram user);
- the RPC layer: fake in Python tests, real Postgres in `tests/sql`.

### 3.3 Where the Telegram adapter gets its bot

The rider-agent tool (H) and the delivery hooks have no `request.app`. The notifier's Telegram adapter is built lazily from the
module-level `config.rest_admin_bot` and `config.tgram_setting.REST_ADMIN_BOT_KEY`. That is the same `Bot` instance that
`channels/telegram/bots.default_registry()` passes to the registry, so one aiohttp session serves both. Tests inject fakes
with `restaurant_notifier.use_adapters(whatsapp=..., telegram=...)`, a test-only seam on the module, reset by a fixture.

### 3.4 Receipt status key (SQL owns it; Python never computes state)

`t_receipt_status(order_number, order_type, dispatch_id) -> text`:

| Order type | Condition (evaluated in this order) | Key | Buttons on the copy |
|---|---|---|---|
| delivery | summary row missing | `gone` | none |
| delivery | `delivery_summary.status = 'completed'` | `done` | none ("✅ Delivered HH:MM") |
| delivery | inflight row with this `dispatch_id`, dispatch status in `('pickedup','completed')` | `picked_up` | none |
| delivery | inflight row with this `dispatch_id`, `ready_dispatch_id = dispatch_id` | `ready@HH:MI` | +10, +20 |
| delivery | inflight row with this `dispatch_id`, not ready | `open@HH:MI` | Ready, +10, +20 |
| delivery | no inflight row for this `dispatch_id` (cancelled before pickup, or another rider now) | `rider_cancelled` | none |
| takeaway | summary missing or `status = 'declined'` | `gone` | none |
| takeaway | `status = 'completed'` | `done` | none |
| takeaway | `ready_at IS NOT NULL` | `ready@HH:MI` | none |
| takeaway | otherwise | `open@HH:MI` | Ready |

`HH:MI` is `to_char(pickup_time AT TIME ZONE 'Europe/London', 'HH24:MI')`. Because the key contains the pickup time, a WhatsApp
+10 tap makes every Telegram copy stale and the 5-second job redraws them. The keys are mirrored by `ReceiptStatus` in
`receipts/model.py`; change both together, as with `t_order_card_status()` ↔ `order_cards/model.Status`.

### 3.5 Reply targets (D33, D36)

`t_receipt_snapshot` returns, per destination, `reply_to`: the newest `t_sent_messages` row for that chat and order with
`kind = 'order_card'` that still exists (`state <> 'closed' OR close_reason = 'edited'`). Notices ask for the newest existing
`kind = 'receipt'` copy (F, H) or card copy (C). Sends use
`reply_parameters=ReplyParameters(message_id=..., allow_sending_without_reply=True)`, so a target deleted by hand never fails the send.

### 3.6 Open point for the owner (changes Q7.4)

Q7.4 said "keep the WhatsApp auto-accept send where it is (before the unguarded `UPDATE`) and send Telegram only after the
update". Through one `notify()` call that means either a `channels=` parameter (it widens the interface for one call site) or
leaving the inline WhatsApp loop in place (two paths for one notice). **Recommendation:** in `delivery_hooks._handle_restaurant_timedout`,
move the single `notify(AutoAccepted(...))` **after** the `UPDATE`, for both channels. Same text, and the same moment in practice;
the only difference is that if the `UPDATE` raises, WhatsApp no longer announces an auto-accept that did not happen. The takeaway
handler already sends after its guarded update, so it does not change. **Owner to confirm or keep the original Q7.4 wording.**

---

## 4. The migration: `ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql`

Run order: after `restaurant_order_decision.sql` and `create_t_order_alerts.sql` (it reads `restaurant_admin_label()`,
`t_order_admin_phone()`, `t_order_card_destinations()`, `t_sent_messages`, `parse_alert_offsets()`). Run it **before** PR 1 deploys.
It never redefines a function owned by another file.

### 4.1 Header (the house template, abridged here; the real file has every line)

```sql
-- =============================================================================================
-- Migration: kitchen actions (Ready, adjust pickup) shared by WhatsApp and Telegram + Telegram kitchen receipts/notices
-- =============================================================================================
-- Run once in the Supabase SQL editor (operator step; the implementing agent never runs it).
-- Repeatable: ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT DO NOTHING.
-- Run AFTER restaurant_order_decision.sql and create_t_order_alerts.sql. Run BEFORE deploying the code that calls it
-- (utils_common/order_management/restaurant_actions.py, channels/telegram/rest_admin/receipts/store.py,
--  channels/telegram/rest_admin/notices.py). Nothing is sent until the operator schedules job_t_receipt_refresh (last section).
--
-- WHAT THIS ADDS
--   Columns    delivery_summary.ready_at / ready_by / ready_dispatch_id / pickup_time_initial / pickup_adjusted_by /
--              pickup_adjusted_at;  takeaway_summary.ready_at / ready_by;  t_sent_messages.dispatch_id
--   Functions  restaurant_order_ready()          Ready, shared by every channel; first tap per dispatch wins (D30, D31)
--              restaurant_order_adjust_pickup()  +10/+20 relative to the original pickup; 'unchanged' writes nothing (D32)
--              t_order_ready()                   Telegram Ready: authorise (D14) then restaurant_order_ready()
--              t_order_adjust_pickup()           Telegram +N: authorise (D14), compute the target, then the shared call
--              t_receipt_status()                receipt status key (IMMUTABLE inputs → key; see plan §3.4)
--              t_receipt_snapshot()              everything to draw a receipt + destinations + reply targets, one read
--              t_receipt_sent()                  record a sent receipt copy, take OLDER receipt copies in that chat (D35)
--              t_receipts_stale()                receipt copies whose key differs from the DB (read-only)
--              t_receipts_take()                 claim one order's stale receipt copies for a refresh pass
--              t_notice_sent()                   audit row for a plain notice (closed at once, D36)
--              job_t_receipt_refresh()           5-second job: stale receipts → POST /telegram/rest-admin/order-alerts
--
-- WHY (plans/telegram-phase-7-8-kitchen-actions-and-notices.md, D28–D38)
--   ...
-- HOW THE PIECES FIT TOGETHER
--   Tables used (defined elsewhere): delivery_summary (delivery/delivery_summary.sql), takeaway_summary (takeaway/takeaway_summary.sql),
--     delivery_inflight (dispatch/delivery_inflight.sql), delivery_dispatch (dispatch/delivery_dispatch.sql), rider_master (core/restaurant_master.sql), food_order /
--     order_item (live tables), t_invites (create_t_invites.sql), t_sent_messages (create_t_order_alerts.sql).
--   Triggers (unchanged): trigger_restaurant_updates is AFTER UPDATE OF restaurant_confirmation_status, so the adjust
--     UPDATE (which sets it to 'restaurant_pickuptime_adjusted') still POSTs /delivery-hooks/restaurant-confirmation-request
--     → _handle_restaurant_pickuptime_adjusted → rider agent. 'unchanged' does no UPDATE, so no webhook.
--   Ready does NOT touch restaurant_confirmation_status, so no trigger fires; the follow-up is Python's (restaurant_actions).
--   Python callers (keep in sync with the module docstrings):
--     utils_common/order_management/restaurant_actions.py
--       ready(ref, WhatsAppActor)          -> restaurant_order_ready(p_order_number, p_order_type, p_admin_phone, p_channel)
--       ready(ref, TelegramActor)          -> t_order_ready(p_bot_key, p_tuid, p_order_number, p_order_type)
--       adjust_pickup(ref, WhatsAppActor)  -> restaurant_order_adjust_pickup(p_order_number, p_target, p_admin_phone, p_channel)
--       adjust_pickup(ref, TelegramActor)  -> t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)
--       callers: watomation/on_callback_wa_handler.py (admin_collection_ready, admin_takeaway_ready,
--                admin_adjust_pickup_time), channels/telegram/rest_admin/receipts/__init__.py (Receipts.tap)
--     channels/telegram/rest_admin/receipts/store.py (ReceiptStore)
--       snapshot()          -> t_receipt_snapshot(p_bot_key, p_order_number, p_order_type, p_dispatch_id)
--       receipt_sent()      -> t_receipt_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_order_number, p_order_type,
--                                             p_rest_ref, p_dispatch_id, p_status)
--       take_for_refresh()  -> t_receipts_take(p_bot_key, p_order_number, p_order_type)
--       mark()              -> t_order_card_mark(...)   (create_t_order_alerts.sql; generic on t_sent_messages.id)
--     channels/telegram/rest_admin/notices.py (Notices)
--       destinations/reply -> t_notice_targets(p_bot_key, p_rest_ref, p_order_number, p_reply_kind)
--       notice_sent()      -> t_notice_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_rest_ref, p_order_number, p_notice)
--     watomation/routers/telegram_order_alerts.py  <- job_t_receipt_refresh() (pg_cron, POST {"receipts": [...]})
--   Receipt status keys MUST match channels/telegram/rest_admin/receipts/model.py (ReceiptStatus).
-- RESULT VOCABULARY
--   restaurant_order_ready:          ok | already_ready | not_ready_state | not_found        (+ not_authorised from t_order_ready)
--   restaurant_order_adjust_pickup:  ok | unchanged | not_ready_state | not_found            (+ not_authorised)
-- CONCURRENCY   one UPDATE ... WHERE <gate> decides each tap; two channels / two admins / three workers cannot both win.
-- SECURITY      RLS unchanged on the summaries; every function REVOKEd from PUBLIC, anon, authenticated (service key only).
-- NOT YET DONE  takeaway adjust; takeaway 'completed' writer (receipt stays 'ready' until something sets it); group chats (D27).
-- =============================================================================================
```

### 4.2 Columns

```sql
ALTER TABLE public.delivery_summary
    ADD COLUMN IF NOT EXISTS ready_at            timestamptz,
    ADD COLUMN IF NOT EXISTS ready_by            text,      -- admin phone (digits), label via restaurant_admin_label()
    ADD COLUMN IF NOT EXISTS ready_dispatch_id   integer,   -- the dispatch the Ready was for (D35)
    ADD COLUMN IF NOT EXISTS pickup_time_initial timestamptz, -- pickup before the FIRST adjust (D32)
    ADD COLUMN IF NOT EXISTS pickup_adjusted_by  text,
    ADD COLUMN IF NOT EXISTS pickup_adjusted_at  timestamptz;
ALTER TABLE public.takeaway_summary
    ADD COLUMN IF NOT EXISTS ready_at timestamptz,
    ADD COLUMN IF NOT EXISTS ready_by text;
ALTER TABLE public.t_sent_messages
    ADD COLUMN IF NOT EXISTS dispatch_id integer;          -- receipts only: which rider's receipt this copy is
CREATE INDEX IF NOT EXISTS t_sent_messages_receipts
    ON public.t_sent_messages (subject_ref, tcid) WHERE kind = 'receipt' AND state <> 'closed';
```

Nullable, no defaults: zero rewrite and no lock beyond the catalog update. `kind` already exists as free text; `'receipt'` and
`'notice'` are new values, documented in this header and in `create_t_order_alerts.sql` §1's comment. That is a comment-only
edit to that file in the same PR.

### 4.3 `restaurant_order_ready` (shared; trusts `p_admin_phone`, like `restaurant_order_decide`)

```sql
CREATE OR REPLACE FUNCTION public.restaurant_order_ready(
    p_order_number text, p_order_type text, p_admin_phone text, p_channel text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_inf record;           -- delivery_inflight + dispatch status
    v_cur record;
BEGIN
    IF p_order_type NOT IN ('delivery', 'takeaway') THEN
        RAISE EXCEPTION 'restaurant_order_ready: bad order type %', p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        SELECT i.dispatch_id, i.rider_id, d.status AS dispatch_status
          INTO v_inf
          FROM public.delivery_inflight i
          JOIN public.delivery_dispatch d ON d.dispatch_id = i.dispatch_id
         WHERE i.order_number = p_order_number;

        UPDATE public.delivery_summary s
           SET ready_at = now(), ready_by = p_admin_phone, ready_dispatch_id = v_inf.dispatch_id
         WHERE s.order_number = p_order_number
           AND v_inf.dispatch_id IS NOT NULL                                   -- D31: in progress ...
           AND v_inf.dispatch_status NOT IN ('pickedup', 'completed')          -- ... and not collected
           AND s.ready_dispatch_id IS DISTINCT FROM v_inf.dispatch_id;         -- first tap per dispatch wins (D35)
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'ok', 'rider_id', v_inf.rider_id, 'dispatch_id', v_inf.dispatch_id,
                                      'rest_name', (SELECT rest_name FROM public.delivery_summary WHERE order_number = p_order_number),
                                      'ready_by', public.restaurant_admin_label(p_admin_phone), 'ready_by_phone', p_admin_phone);
        END IF;
        SELECT ready_at, ready_by, ready_dispatch_id INTO v_cur FROM public.delivery_summary WHERE order_number = p_order_number;
        IF NOT FOUND THEN RETURN jsonb_build_object('result', 'not_found'); END IF;
        IF v_inf.dispatch_id IS NOT NULL AND v_cur.ready_dispatch_id = v_inf.dispatch_id
           AND v_inf.dispatch_status NOT IN ('pickedup', 'completed') THEN
            RETURN jsonb_build_object('result', 'already_ready', 'ready_at', v_cur.ready_at,
                                      'ready_by', public.restaurant_admin_label(v_cur.ready_by), 'ready_by_phone', v_cur.ready_by);
        END IF;
        RETURN jsonb_build_object('result', 'not_ready_state',
                                  'progress', CASE WHEN v_inf.dispatch_id IS NULL THEN 'not_in_progress' ELSE 'picked_up' END);
    END IF;

    -- takeaway
    UPDATE public.takeaway_summary
       SET ready_at = now(), ready_by = p_admin_phone
     WHERE order_number = p_order_number AND status = 'pickup_confirmed' AND ready_at IS NULL;
    IF FOUND THEN
        RETURN (SELECT jsonb_build_object('result', 'ok', 'rest_name', t.rest_name, 'customer_id', t.customer_id,
                                          'order_id', f.order_id, 'ready_by', public.restaurant_admin_label(p_admin_phone),
                                          'ready_by_phone', p_admin_phone)
                  FROM public.takeaway_summary t LEFT JOIN public.food_order f ON f.order_number = t.order_number
                 WHERE t.order_number = p_order_number);
    END IF;
    SELECT status, ready_at, ready_by INTO v_cur FROM public.takeaway_summary WHERE order_number = p_order_number;
    IF NOT FOUND THEN RETURN jsonb_build_object('result', 'not_found'); END IF;
    IF v_cur.ready_at IS NOT NULL THEN
        RETURN jsonb_build_object('result', 'already_ready', 'ready_at', v_cur.ready_at,
                                  'ready_by', public.restaurant_admin_label(v_cur.ready_by), 'ready_by_phone', v_cur.ready_by);
    END IF;
    RETURN jsonb_build_object('result', 'not_ready_state', 'progress', 'not_in_progress');
END $$;
```

Note: `p_channel` is accepted for parity with `restaurant_order_decide` and written to the log line only (no column), so a later
`ready_channel` column is a one-line change.

**Race proof (tests/sql):** two connections call it for the same order. Exactly one `ok`; the other gets `already_ready`.
The UPDATE row lock serialises them, and the second re-evaluates `ready_dispatch_id IS DISTINCT FROM`.

### 4.4 `restaurant_order_adjust_pickup` (delivery only)

```sql
CREATE OR REPLACE FUNCTION public.restaurant_order_adjust_pickup(
    p_order_number text, p_target timestamptz, p_admin_phone text, p_channel text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_inf record;
    v_cur record;
BEGIN
    IF p_target IS NULL THEN RAISE EXCEPTION 'restaurant_order_adjust_pickup: missing target'; END IF;
    SELECT i.dispatch_id, d.status AS dispatch_status INTO v_inf
      FROM public.delivery_inflight i JOIN public.delivery_dispatch d ON d.dispatch_id = i.dispatch_id
     WHERE i.order_number = p_order_number;
    SELECT pickup_time INTO v_cur FROM public.delivery_summary WHERE order_number = p_order_number FOR UPDATE;
    IF NOT FOUND THEN RETURN jsonb_build_object('result', 'not_found'); END IF;
    IF v_inf.dispatch_id IS NULL OR v_inf.dispatch_status IN ('pickedup', 'completed') THEN
        RETURN jsonb_build_object('result', 'not_ready_state',
                                  'progress', CASE WHEN v_inf.dispatch_id IS NULL THEN 'not_in_progress' ELSE 'picked_up' END);
    END IF;
    IF v_cur.pickup_time = p_target THEN
        RETURN jsonb_build_object('result', 'unchanged', 'pickup_time', v_cur.pickup_time);   -- no UPDATE → no trigger
    END IF;
    UPDATE public.delivery_summary
       SET pickup_time_initial = COALESCE(pickup_time_initial, pickup_time),
           pickup_time = p_target,
           restaurant_confirmation_status = 'restaurant_pickuptime_adjusted',   -- fires trigger_restaurant_updates (unchanged)
           pickup_adjusted_by = p_admin_phone,
           pickup_adjusted_at = now(),
           restaurant_update_dtts = now()                                       -- as the WhatsApp handler did
     WHERE order_number = p_order_number;
    RETURN jsonb_build_object('result', 'ok', 'pickup_time', p_target,
                              'by', public.restaurant_admin_label(p_admin_phone), 'by_phone', p_admin_phone);
END $$;
```

`t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)` checks `p_minutes IN (10, 20)` (else RAISE), resolves
`rest_ref`, runs `t_order_admin_phone()` (→ `not_authorised`), and calls the shared function with
`COALESCE(pickup_time_initial, pickup_time) + make_interval(mins => p_minutes)`. `t_order_ready` follows the same shape,
copying `t_order_decide` (restaurant_order_decision.sql §6).

**Card interaction:** `t_order_card_status()` already maps `restaurant_pickuptime_adjusted` → `pickup_set`. The order card's
status key does not change on an adjust, so the order card is not redrawn (its pickup line keeps the first chosen time). The
receipt is the place for the current time. This is deliberate; a test pins it.

### 4.5 Receipt functions (sketch; full code in the PR)

```sql
CREATE OR REPLACE FUNCTION public.t_receipt_status(p_order_number text, p_order_type text, p_dispatch_id integer)
RETURNS text LANGUAGE sql STABLE SET search_path = public AS $$ ... plan §3.4, one CASE over a LEFT JOIN ... $$;

-- {status, rest_ref, dispatch_id,
--  facts:{order_number, order_type, rest_name, rest_code, pickup_at, pickup_initial, pickup_adjusted_by:{label,phone}|null,
--         ready_at, ready_by:{label,phone}|null, rider:{id,name}|null, customer:{address, phone}|null,
--         items:[{qty, name, line_total, mods[]}], small_order_fee, total, notes, pay_at_restaurant, completed_at},
--  destinations:[{tcid, tuid, phone, label, reply_to}]}            reply_to = newest existing card copy in that chat
CREATE OR REPLACE FUNCTION public.t_receipt_snapshot(p_bot_key text, p_order_number text, p_order_type text, p_dispatch_id integer)
RETURNS jsonb ...;

-- inserts kind='receipt' row (idempotent on bot_key,tcid,message_id) and claims OLDER receipt copies of this order in this chat
-- (any dispatch) for deletion: returns {previous:[{id,tcid,message_id}], status}. Mirrors t_order_card_sent (create_t_order_alerts §6).
CREATE OR REPLACE FUNCTION public.t_receipt_sent(...) RETURNS jsonb ...;

-- live receipt copies whose card_status <> t_receipt_status(...) or whose chat is no longer a destination; taken > 30 s re-offered.
CREATE OR REPLACE FUNCTION public.t_receipts_stale(p_bot_key text, p_order_number text DEFAULT NULL, p_order_type text DEFAULT NULL) ...;
CREATE OR REPLACE FUNCTION public.t_receipts_take(p_bot_key text, p_order_number text, p_order_type text) RETURNS jsonb ...;

CREATE OR REPLACE FUNCTION public.t_notice_targets(p_bot_key text, p_rest_ref text, p_order_number text, p_reply_kind text)
RETURNS TABLE (tcid bigint, tuid bigint, phone text, reply_to bigint) ...;   -- destinations + newest existing card/receipt copy
CREATE OR REPLACE FUNCTION public.t_notice_sent(...) RETURNS void ...;          -- INSERT state 'closed', close_reason 'sent'

CREATE OR REPLACE FUNCTION public.job_t_receipt_refresh() RETURNS boolean ...
  -- SELECT DISTINCT order_number, order_type FROM t_receipts_stale('rest_admin') LIMIT 50;
  -- nothing → RETURN true without calling the app; else http_post ORDELO_APP_URL/telegram/rest-admin/order-alerts
  -- {"event_type":"t_receipt_refresh","receipts":[...]}; non-2xx → RAISE NOTICE, RETURN false (the next tick retries naturally)
```

`t_order_card_mark()`'s CHECK on `p_outcome` needs no change. `close_reason` gets the new value `'sent'` for notices; the column
has no CHECK.

Grants: `REVOKE ALL ON FUNCTION ... FROM PUBLIC, anon, authenticated;` for all eleven functions, written out one per line as in
the other migration files.

### 4.6 Operator SQL (commented out at the end of the file)

```sql
-- SELECT cron.schedule('job_t_receipt_refresh', '5 seconds', $$SELECT public.job_t_receipt_refresh()$$);
-- To stop: SELECT cron.unschedule('job_t_receipt_refresh');
-- Rollback of behaviour (no data loss): unschedule the job and redeploy the previous app build; the new columns are inert.
```

---

## 5. Python changes, with code

### 5.1 `utils_common/order_management/restaurant_actions.py` (new)

```python
"""
Kitchen actions after an order is accepted: Ready and adjust pickup (shared by WhatsApp and Telegram).
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql (keep both in sync)
    . Python function -> RPC:
        ready(ref, WhatsAppActor)          -> restaurant_order_ready(p_order_number, p_order_type, p_admin_phone, p_channel)
        ready(ref, TelegramActor)          -> t_order_ready(p_bot_key, p_tuid, p_order_number, p_order_type)
        adjust_pickup(ref, WhatsAppActor)  -> restaurant_order_adjust_pickup(p_order_number, p_target, p_admin_phone, p_channel)
        adjust_pickup(ref, TelegramActor)  -> t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)
    . The first Ready per dispatch wins in SQL (D30). ONLY on 'ok' does this module do the follow-up, identically for
      both channels: delivery -> rider agent `notify_food_ready_for_pickup`; takeaway -> customer event ready_for_collection
    . An adjust's rider message is NOT sent here: the UPDATE fires trigger_restaurant_updates ->
      delivery_hooks._handle_restaurant_pickuptime_adjusted (unchanged)
    . client_ordelo_service (service-role RPCs) inside asyncio.to_thread (CLAUDE.md rule)
    . Callers: watomation/on_callback_wa_handler.py, channels/telegram/rest_admin/receipts/__init__.py
"""
OrderType = Literal["delivery", "takeaway"]
READY_RESULTS = frozenset({"ok", "already_ready", "not_ready_state", "not_found", "not_authorised"})
ADJUST_RESULTS = frozenset({"ok", "unchanged", "not_ready_state", "not_found", "not_authorised"})

@dataclass(frozen=True)
class WhatsAppActor:
    phone: str

@dataclass(frozen=True)
class TelegramActor:
    bot_key: str
    tuid: int

@dataclass(frozen=True)
class ActionOutcome:
    result: str
    by_label: str | None = None        # "Ada" / "…0754" (D19) for "Already marked ready by Ada"
    by_phone: str | None = None
    pickup_time: str | None = None     # ISO, adjust results
    progress: str | None = None        # 'not_in_progress' | 'picked_up' for not_ready_state
    follow_up_failed: bool = False     # ok in SQL but the rider/customer message raised (logged)

async def ready(order_number: str, order_type: OrderType, actor: WhatsAppActor | TelegramActor) -> ActionOutcome:
    data = await _call_ready(order_number, order_type, actor)        # picks the RPC by actor type, validates `result`
    out = ActionOutcome(result=data["result"], by_label=data.get("ready_by"), by_phone=data.get("ready_by_phone"),
                        progress=data.get("progress"))
    if out.result != "ok":
        return out
    try:
        if order_type == "delivery":
            await run_rider_agent_w_custom_msg(       # exactly the text admin_collection_ready sends today
                recipient=data["rider_id"],
                human_msg=f"call `tool notify_food_ready_for_pickup`. Rider should hurry to "
                          f"{data['rest_name']} to pickup the food.",
            )
        else:
            order_id = data.get("order_id") or "-".join(order_number.split("-")[1:])
            payload = {"order_id": order_id, "order_number": order_number, "recipient": data.get("customer_id"),
                       "admin_id": _actor_phone(actor, data), "event": "admin_takeaway_ready",
                       "event_dtts": datetime.now(timezone.utc).isoformat()}
            await customer_notifier.publish(order_number, CustomerOrderEvent(       # exactly what admin_takeaway_ready does
                "ready_for_collection", "ready_for_collection", "order-takeaway-ready", payload, f"/{order_id}"))
    except Exception:
        logger.exception(f"restaurant_actions.ready follow-up failed for {order_number}")
        return replace(out, follow_up_failed=True)
    return out

async def adjust_pickup(order_number: str, actor, *, target: str | datetime | None = None,
                        minutes: int | None = None) -> ActionOutcome:
    """WhatsApp passes the absolute `target` its button carries; Telegram passes `minutes` (10 | 20)."""
```

Imports: `run_rider_agent_w_custom_msg` comes from `ordelo.agents.agent_runner`. To avoid a heavy import at module load, it is
imported inside the function, the same way `takeaway_hooks` imports `queue_release` lazily.

### 5.2 WhatsApp handlers switched (`watomation/on_callback_wa_handler.py`)

```python
async def admin_collection_ready(msg: WhatsApp, callback: CallbackButton[CallbackButtonData]):
    data = CallbackButtonData(**json.loads(callback.data))
    order_number = getattr(data, "order_number", None)
    if order_number is None:                       # buttons sent before order_number existed: keep the old gate path
        return await _legacy_collection_ready(data, callback)   # = today's body, unchanged
    out = await restaurant_actions.ready(order_number, "delivery", WhatsAppActor(callback.sender))
    if out.result == "ok":
        return                                     # today: no reply on success
    await callback.reply(text=_wa_ready_reply(out))
```

`_wa_ready_reply` keeps today's strings for the gate states (`GATE_REPLIES[NOT_IN_PROGRESS]`, `GATE_REPLIES[PICKED_UP]`,
`GATE_REPLIES[UNKNOWN]` for `not_found` or an RPC error). The one new string is `"Already marked ready by {label}"`.
`admin_takeaway_ready`: validation is unchanged; then `restaurant_actions.ready(order_number, "takeaway", ...)`, which replies with
today's `"Customer notification request sent."` on `ok` and `"Already marked ready by {label}"` on `already_ready`.
`admin_adjust_pickup_time`: validation is unchanged; then `restaurant_actions.adjust_pickup(order_number, WhatsAppActor(sender), target=pickup_time)`.
On `ok` it replies with today's `f"Pickup time updated to {fmt_uk_time(pickup_time)}"`. On `unchanged` it gives the same reply
(the admin sees the state they asked for). Gate states reuse `GATE_REPLIES`. An exception gives today's
`"Failed to update pickup time. Please retry."`.

`ordelo/delivery_progress.py` stays. It is still used by `/notify-food-ready-for-pickup` (restaurant-agents' only caller, listed
for removal) and by `_handle_restaurant_pickuptime_adjusted` / `_process_rider_pickup_alerts`.

### 5.3 `utils_common/notify/restaurant_notifier.py` (new)

```python
"""
Restaurant-facing notices on every channel (D28, D29): one call, WhatsApp AND Telegram, in parallel.
    . notify(notice) never raises; each channel and each recipient fails alone (logged)
    . WhatsApp adapter: calls the EXISTING wa_senders functions with the arguments they take today (text/buttons unchanged)
    . Telegram adapter: channels/telegram/rest_admin (Receipts.send / Notices.send) using config.rest_admin_bot
    . Callers: delivery_hooks (KitchenReceipt, AutoAccepted, RiderAlert), takeaway_hooks (TakeawayReceipt, AutoAccepted),
      customer_hooks (Feedback), ordelo/agents/rider_agent.py (DeliveryCompleted)
"""
@dataclass(frozen=True)
class KitchenReceipt:          # D: WhatsApp needs the two payload dicts it gets today
    delivery_summary: DeliverySummary
    rider_master: dict
    dispatch_id: int

@dataclass(frozen=True)
class TakeawayReceipt:         # E
    order_number: str; pickup_time: str; rest_name: str; admins: list[str]
    restaurant_msg_id: str | None; rest_ref: str

@dataclass(frozen=True)
class AutoAccepted:            # C
    order_number: str; order_type: Literal["delivery", "takeaway"]; rest_ref: str
    admins: list[str]; pickup_display: str; pickup_minutes: int

@dataclass(frozen=True)
class RiderAlert:              # F: the kwargs notify_rest_admins_rider_alert takes today
    phase: str; order_number: str; pickup_time: str; rider_id: str
    rider_name: str | None; rest_ref: str | None; rest_admins: list[str] | None

@dataclass(frozen=True)
class DeliveryCompleted:       # H
    order_number: str; rest_ref: str

@dataclass(frozen=True)
class Feedback:                # I: what customer_hooks._notify_feedback_admins gets today
    rest_ref: str; admins: list[str]; feedback_id: str; restaurant_name: str; cust_id: str
    cust_name: str | None; order_reference: str | None; description: str; received_at: datetime

Notice = KitchenReceipt | TakeawayReceipt | AutoAccepted | RiderAlert | DeliveryCompleted | Feedback

async def notify(notice: Notice) -> None:
    wa, tg = _adapters()
    results = await asyncio.gather(wa.send(notice), tg.send(notice), return_exceptions=True)
    for channel, r in zip(("whatsapp", "telegram"), results):
        if isinstance(r, BaseException):
            logger.opt(exception=r).error(f"restaurant_notifier: {channel} {type(notice).__name__} failed")
```

**WhatsApp adapter, mapping** (this table is the parity contract; a test asserts each row's exact call):

| Notice | WhatsApp adapter does exactly |
|---|---|
| `KitchenReceipt` | `await wa_senders.admin_order_reciept(delivery_summary=n.delivery_summary, rider_master=n.rider_master)` |
| `TakeawayReceipt` | `await wa_senders.takeaway_admin_order_receipt(order_number=…, pickup_time=…, rest_name=…, admins=…, restaurant_msg_id=…, rest_ref=…)` |
| `AutoAccepted` | `await wa_senders.admin_auto_accept_notice(admins, order_number, pickup_display, pickup_minutes)`: the loop moved verbatim from the two `_handle_restaurant_timedout` (text `f"Order {order_number} auto-accepted due to confirmation timeout. Pickup time set to {pickup_display} ({pickup_minutes} mins from order time)."`, one admin at a time as today) |
| `RiderAlert` | `await wa_senders.notify_rest_admins_rider_alert(phase=…, order_number=…, pickup_time=…, rider_id=…, rider_name=…, rest_ref=…, rest_admins=…)` |
| `DeliveryCompleted` | `await wa_senders.admin_delivery_completed(order_number, rest_ref)`: the loop moved verbatim from `rider_agent.py` (`RestaurantMaster.get_admins_for(rest_ref)`, text `f"✅ Delivery completed for {order_number}."`). Sync accessor: called in `asyncio.to_thread` |
| `Feedback` | the `asyncio.gather` over `send_restaurant_feedback_notification` moved verbatim from `customer_hooks._notify_feedback_admins` (same per-admin warning log) |

Senders are looked up as `wa_senders.<name>` at call time, so existing `monkeypatch.setattr(wa_senders, ...)` tests keep working.

**Telegram adapter, mapping:**

| Notice | Telegram |
|---|---|
| `KitchenReceipt` | `Receipts.send(OrderRef(n.delivery_summary.order_number, "delivery"), n.dispatch_id)` |
| `TakeawayReceipt` | `Receipts.send(OrderRef(n.order_number, "takeaway"), None)` |
| `AutoAccepted` | `Notices.send(n.rest_ref, "⏱ <b>{no}</b> auto-accepted (no answer in time). Pickup {pickup_display} ({mins} min after order).", order=…, reply_to="card")` |
| `RiderAlert` | the three wordings of `notify_rest_admins_rider_alert`, composed by a shared pure `rider_alert_text(phase, minutes_past, pickup_display, rider_label)` extracted from `wa_senders` (WhatsApp keeps calling it, then its `*bold*`; Telegram HTML-escapes it and uses `<b>`), `reply_to="receipt"` |
| `DeliveryCompleted` | `Notices.send(n.rest_ref, "✅ Delivered — <b>{no}</b>", order=…, reply_to="receipt")` + `Receipts.refresh(order)` (copies → "✅ Delivered HH:MM") |
| `Feedback` | `Notices.send(n.rest_ref, <the six lines, escaped>, order=None, reply_to=None)` |

### 5.4 Call-site edits (each is one line plus an import; WhatsApp still happens through the adapter)

| File | Today | After |
|---|---|---|
| `watomation/routers/delivery_hooks.py` `delivery_inflight_graph_init_hook` step 3 | `background_tasks.add_task(admin_order_reciept, delivery_summary=…, rider_master=…)` | `background_tasks.add_task(restaurant_notifier.notify, KitchenReceipt(delivery_summary, rider_master, dispatch_id))` (`dispatch_id` is already read at the top of the hook) |
| `watomation/routers/takeaway_hooks.py` `pickup_time_updated_hook` step 3 | `add_task(takeaway_admin_order_receipt, …)` | `add_task(restaurant_notifier.notify, TakeawayReceipt(…same values…))` |
| `delivery_hooks._handle_restaurant_timedout` | WhatsApp loop **before** the `UPDATE` | `await restaurant_notifier.notify(AutoAccepted(…))` **after** the `UPDATE` (open point §3.6) |
| `takeaway_hooks._handle_restaurant_timedout` | WhatsApp loop after the guarded update | `await restaurant_notifier.notify(AutoAccepted(…))` in the same place |
| `delivery_hooks._process_rider_pickup_alerts` (`audience == "rest_admins"`) | `await notify_rest_admins_rider_alert(…)` | `await restaurant_notifier.notify(RiderAlert(…same kwargs…))` |
| `ordelo/agents/rider_agent.py` `verify_customer_confirmation_code` | inline WhatsApp loop to admins | `await restaurant_notifier.notify(DeliveryCompleted(order_number, rest_ref))` |
| `watomation/routers/customer_hooks.py` `submit_restaurant_feedback` | `add_task(_notify_feedback_admins, …)` | `add_task(restaurant_notifier.notify, Feedback(…))`; the 404/503 checks and the response are unchanged |
| `utils_common/waba_utils/wa_senders.py` | dead `admin_delivery_driver_nearby`, `admin_delivery_complete_notification`, `REST_MASTER = "dummy"` | deleted; docstring list updated; new `admin_auto_accept_notice`, `admin_delivery_completed`, `rider_alert_text` |

Existing tests that patch `delivery_hooks.admin_order_reciept` (`tests/watomation/routers/test_delivery_hooks.py:222`) and
`takeaway_hooks.takeaway_admin_order_receipt` (`test_takeaway_hooks.py:153, :297`) change their patch target to the notifier.
Their assertions about what WhatsApp receives stay the same.

### 5.5 Telegram: `channels/telegram/rest_admin/receipts/`

```
receipts/
  __init__.py   Receipts(bot, bot_key, store=None, io=None): send(order, dispatch_id), refresh(order), tap(query, action)
  model.py      pure: ReceiptStatus, ReceiptFacts, Receipt.from_snapshot(snap).view(viewer) -> View; toast(outcome)
  store.py      ReceiptStore: snapshot / receipt_sent / take_for_refresh / mark  (RPCs in restaurant_ready_adjust_notices.sql)
```

`Receipts.send` copies the shape of `OrderCards.remind` (`order_cards/__init__.py`):
1. Take the snapshot (D24 check before sending).
2. Send to every destination in parallel (`asyncio.gather`), each as a reply to its `reply_to`.
3. Record each copy with `t_receipt_sent` and delete the `previous` copies it returns (D35).
4. If the returned status differs from what was drawn, run `refresh` (D24 check after sending).

`Receipts.tap`:

```python
async def tap(self, query: CallbackQuery, action: OrderAction) -> None:
    order = OrderRef(action.o, "delivery" if action.t == "d" else "takeaway")
    actor = TelegramActor(self._bot_key, query.from_user.id)          # D14/D27: the USER, never the chat
    try:
        out = (await restaurant_actions.ready(order.order_number, order.order_type, actor) if action.a == "rdy"
               else await restaurant_actions.adjust_pickup(order.order_number, actor, minutes=action.m))
    except Exception:
        logger.exception(...); await answer_quietly(query, TROUBLE, True); return
    text, alert = receipt_toast(action.a, out)
    await asyncio.gather(answer_quietly(query, text, alert), self._refresh_quietly(order))   # rule 3: never gate the refresh
```

Toasts, all composed in `receipts/model.py`:

| Result | Toast |
|---|---|
| `ok` (Ready) | "Rider notified" / "Customer notified" |
| `ok` (adjust) | "Pickup 12:50" |
| `unchanged` | "Pickup already 12:50" |
| `already_ready` | "Already marked ready by Ada" |
| `not_ready_state`, progress `picked_up` | "Food already picked up" |
| `not_ready_state`, progress `not_in_progress` | "This order is no longer in progress" |
| `not_authorised` | "You're not an admin for this restaurant any more." (alert) |
| `not_found` | `GONE_TEXT` |

**View** (HTML, every value escaped; `<b>` for the code and the totals; buttons only for the states in §3.4). The layout is the
one approved in Q6:

```
🧾 KITCHEN RECEIPT · 🚚 Delivery
<b>ELAS-CEKT-22</b>
✅ Marked ready by Ada                           ← status line, only once something happened (claims only what is recorded)
🔑 Restaurant code: <b>47</b>
⏰ Pickup: <b>12:50</b> (moved +10 by …0754)
🛵 Rider: Sam — 447700900123

<b>Items</b>
• 2 × Chicken Shawarma — £17.00
   ↳ extra garlic sauce
• 1 × Fries — £3.50

Small order fee: £1.00
<b>Total: £21.50</b>

📝 <b>Notes</b>
<i>Please ring the bell twice</i>

🏠 Customer: 1 Test Street, Orpington BR6 0TW — 447448440754
[🍳 Ready – notify rider] [12:50 (+10)] [13:00 (+20)]
```

The adjust buttons always show `pickup_initial + 10` / `+ 20`, never cumulative (D32). Telegram's 4096-character limit: if a
huge order would exceed it, items after the limit are replaced by `… and N more items (see WhatsApp/printer)`. The cut is made
in the model and tested.

### 5.6 `channels/telegram/rest_admin/notices.py` (new, small)

```python
class Notices:
    async def send(self, rest_ref: str, text_html: str, *, order: OrderRef | None = None,
                   reply_to: Literal["card", "receipt"] | None = None, notice: str) -> int:
        """Send one plain notice to every D14 destination of the restaurant, in parallel. Returns how many chats got it.
        Records each sent copy with t_notice_sent (closed audit row). Never raises."""
```

### 5.7 Wiring

- `channels/telegram/callbacks.py`: `a: Literal["acc", "dec", "pk", "rdy", "adj"]`. Docstring: `m` is the minutes after the
  order time for `pk`, and +minutes over the original pickup for `adj`.
- `channels/telegram/rest_admin/orders.py`: one `@router.callback_query(OrderAction.filter())` handler routes `pk/acc/dec` to
  `order_cards.tap` and `rdy/adj` to `receipts.tap`. `receipts` is injected like `order_cards`.
- `channels/telegram/bots.py`: `TelegramBot.receipts`; `build_rest_admin_dispatcher(settings, cards, receipts)`;
  `dp["receipts"] = receipts`.
- `watomation/routers/telegram_order_alerts.py`: `OrderAlertsPayload.receipts: list[_Order] = []`, then
  `background_tasks.add_task(tg.receipts.refresh, ...)`.

---

## 6. Tests (new and changed)

### 6.1 Isolated database: `tests/sql/test_restaurant_ready_adjust_notices_sql.py` (no services needed)

Uses the existing `tests/sql/conftest.py`. Add `"restaurant_ready_adjust_notices.sql"` to `MIGRATION_FILES` and, in
`minimal_schema.sql`:
- `delivery_inflight`, `delivery_dispatch` (with the real status CHECK) and `rider_master (rider_id, rider_name, town, vehicle_type, is_in_shift)`;
- the real columns `food_order.notes / small_order_fee / payment_status`, `order_item.price / modifications`, and
  `delivery_summary.pickup_date / customer_address / rest_confirmation_code`.

Copy the column types from the live DDL with `ordelo_datamodels/test_support/get_ddl_for_table.sql`. That query is read-only; the
owner runs it.

| Test | Proves |
|---|---|
| `test_ready_delivery_ok_records_who_and_dispatch` | `ok`, `ready_at/by/dispatch_id` set, returns `rider_id`, `rest_name` |
| `test_ready_twice_same_dispatch_is_already_ready_with_label` | second call `already_ready`, label "Ada" via a claimed invite, else "…0754" |
| `test_ready_race_two_connections_one_wins` | two connections; exactly one `ok` |
| `test_ready_not_in_progress_without_inflight` / `test_ready_after_pickup_is_picked_up` | gate D31 |
| `test_ready_new_dispatch_after_cancel_can_be_ready_again` | D35 (`ready_dispatch_id` differs → `ok`) |
| `test_ready_takeaway_ok_once_then_already_ready` / `test_ready_takeaway_needs_pickup_confirmed` | takeaway gate |
| `test_ready_does_not_fire_restaurant_trigger` | `trigger_log` stub unchanged |
| `test_adjust_relative_to_initial_not_cumulative` | +10 then +20 → initial+20; +10 again → initial+10 |
| `test_adjust_same_target_is_unchanged_and_writes_nothing` | no row change, no `trigger_log` row |
| `test_adjust_fires_restaurant_trigger_once` | `trigger_log` row with `restaurant_pickuptime_adjusted` |
| `test_adjust_keeps_restaurant_admin_and_records_adjuster` | D32 |
| `test_adjust_gate_states` | not in progress / picked up |
| `test_adjust_card_status_stays_pickup_set` | the order card is not redrawn by an adjust (§4.4) |
| `test_t_order_ready_and_adjust_not_authorised_for_revoked_or_unlisted_phone` | D14 for both wrappers |
| `test_t_order_adjust_rejects_other_minutes` | RAISE on 15 |
| `test_receipt_status_keys_table` | every row of §3.4, including `rider_cancelled` and `done` after `dispatch_complete`-shaped rows |
| `test_receipt_snapshot_fields_and_reply_to` | items/mods/fee/notes/total/pay-at-restaurant; `reply_to` = newest existing card copy |
| `test_receipt_sent_takes_older_copies_any_dispatch` | D35 deletion claim |
| `test_receipts_stale_after_whatsapp_adjust_and_take_is_exclusive` | key change → stale; `SKIP LOCKED` with two connections |
| `test_job_t_receipt_refresh_posts_only_when_stale` | `http_calls` stub; 0 calls when nothing is stale |
| `test_notice_sent_is_closed_audit_row` / `test_housekeeping_purges_old_notices` | D36, D22 |
| `test_functions_revoked_from_anon` | the grants |

### 6.2 Offline Python

| File | Tests |
|---|---|
| `tests/utils_common/order_management/test_restaurant_actions.py` (new) | RPC chosen per actor; result validation; delivery `ok` runs the rider agent with **exactly** today's `human_msg`; takeaway `ok` publishes exactly today's `CustomerOrderEvent`; non-ok runs no follow-up; follow-up exception → `follow_up_failed`, no raise |
| `tests/utils_common/test_restaurant_notifier.py` (new, beside `test_customer_notifier.py`) | **WhatsApp parity:** for each notice, the recorded `wa_senders` call equals the pre-change call (golden args); both channels called; one channel raising does not stop the other; Telegram adapter not built when the notice has no Telegram mapping (none today) |
| `tests/watomation/test_on_callback_wa_handler.py` (changed) | today's nine `test_admin_*` tests keep their names and asserted replies; new: `test_admin_collection_ready_second_tap_replies_already_ready_no_nudge`, `test_admin_adjust_pickup_time_unchanged_does_not_write`, `test_admin_collection_ready_legacy_button_without_order_number` |
| `tests/channels/telegram/test_receipt_model.py` (new) | pure views for every §3.4 key × viewer; buttons and 64-byte callback data; HTML escaping of notes and items; 4096 cut; toasts |
| `tests/channels/telegram/test_receipts.py` (new) | real `Dispatcher` + `RecordingSession` (`tests/channels/telegram/conftest.py`): send replies to the card id; older copies deleted; tap Ready → toast + edit of every copy; wrong actor; stale button (picked up); repeated update (inbox skip); `from_user.id != chat.id` |
| `tests/channels/telegram/test_notices.py` (new) | per-destination isolation, reply targets, audit RPC called |
| `tests/watomation/routers/test_telegram_order_alerts.py` (changed) | `receipts` payload → `Receipts.refresh` tasks; old payload shape still accepted |
| `tests/watomation/routers/test_delivery_hooks.py`, `test_takeaway_hooks.py`, `test_customer_hooks.py` (changed) | patch target becomes the notifier; the WhatsApp args asserted are unchanged; timeout handler sends the notice after the update |
| `tests/regressions/test_p7_wa_senders.py` (changed) | the two dead-function tests deleted |
| `tests/utils_common/waba_utils/test_wa_senders.py` (changed) | new `rider_alert_text` wording tests; the six existing `test_notify_rest_admins_rider_alert_*` must still pass untouched |

### 6.3 Test the fake-row script itself: `tests/sql/test_restaurant_notices_script_sql.py`

Runs every stage of the §7 script on the isolated database. It checks:
- each stage leaves the rows it promises;
- re-running is clean;
- **only `STRK-TEST-%` rows and dummy-town data are touched** (a row count of every other table before and after);
- `town = 'dummy'` on every order;
- no claimed invite is duplicated (the conditional insert).

---

## 7. Fake-row script: `ordelo_datamodels/test_support/test_restaurant_notices.sql`

Re-runnable against the shared database. You run it one block at a time in the Supabase SQL editor; each block is marked
`-- ===== STAGE n =====`. It follows the house style of `test_create_t_order_alerts.sql`: header, WHAT IT TOUCHES, PREREQUISITES,
WATCH IT queries, NOTHING ARRIVES? section.

**Prerequisites** (each with a check query in the file):
- migrations applied;
- `job_t_order_alerts`, `job_t_receipt_refresh`, `job_rider_pickup_alerts` and the dispatch jobs scheduled;
- a claimed STRK invite for 447448440754;
- ≥ 1 in-shift `rider_master` with `town = 'dummy'` and a vehicle type that `process_delivery` offers;
- `ORDELO_APP_URL` pointing at the instance under test (tunnel for local runs, runbook).

**Side-effect safety, written into the script header after offline verification (step 7d.1). Corrected during implementation:**
the first draft of this plan said `payment_uri = 'http://127.0.0.1:9/...'`. That is wrong: `FoodOrder.payment_uri` is a derived
property (`{stripe_url[_test]}/threads/{thread_id}/orders/{order_id}/payment-url`), not a column. The repo's own test path is used instead
(`docs/test-orders.md`):
- **Every fake order carries an exact `TEST3100` item.** `create_food_order_with_items` (the function real orders use) then saves
  `payment_mode = 'test'`, so every payment-service request goes to `ms_settings.stripe_url_test` (the Wren **test** service), never
  the live one. A delivery order with this item is offered only to riders in `ordelo_config.overwatch_list`; a takeaway creates no
  rider dispatch. The riders you put in town `dummy` must therefore also be in `overwatch_list`.
- Delivery capture (at rider accept) and cancel POST to the test service for a thread that does not exist there: an HTTP 4xx,
  caught as `httpx.HTTPError`, logged, `None`. (`tests/regressions/test_p7d_test_order_safety.py`)
- Customer = 447448440754 and `origin_channel = 'whatsapp'`, so customer events go to your WhatsApp only.
- **Takeaway:** default `payment_status = 'test_no_payment'` (your decision): `capture_takeaway_payment` returns before any HTTP call,
  after one overwatch "capture reconciliation" message about the test order. **Optional stage 8b**, `pay_at_rest`: exactly one print-only
  request, to the **test** service (a receipt job, not a Stripe payment). Run it only if you accept that.
- The pay-at-restaurant line is fully covered in the isolated-database and model tests either way.

| Stage | What the block does | You should see |
|---|---|---|
| 0 RESET | Deletes every `STRK-TEST-%` row from: `delivery_inflight`, `delivery_dispatch`, `delivery_detail`, `delivery_summary`, `takeaway_summary`, `order_item` (via `food_order.order_id LIKE 'STRK-TEST-%'`), `food_order`, `rider_pickup_alert`, `t_order_alerts`, `t_sent_messages`, `order_customer_event`, `notification_outbox`, `order_notification_subscription`, `debug_log` (if present). Conditional STRK invite insert (`WHERE NOT EXISTS` a claimed one). | nothing |
| 1 NEW DELIVERY ORDER | Inserts, through `create_food_order_with_items`, a `food_order` (notes, small-order fee, `test_no_payment`) + 3 `order_item` (`TEST3100`, one with modifications) + a `delivery_detail` row (town `dummy`) + `delivery_summary` (`STRK-TEST-<HHMMSS>`, `town = 'dummy'`, `restaurant_unconfirmed`) | Telegram card + WhatsApp confirmation prompt |
| 2 ACCEPT + PICKUP | *you tap* Accept and a pickup time (either channel); block 2 only shows state | dispatch offer on your **rider** WhatsApp (dummy town) |
| 3 RIDER ACCEPTS | *you tap* Accept as the rider → `job_assign_dispatch` → `delivery_inflight` INSERT | **Kitchen receipt D on WhatsApp and Telegram** (Telegram replies to the card); rider graph starts on your phone |
| 4 READY / ADJUST | *you tap* Ready (Telegram), +10 (WhatsApp), Ready again (WhatsApp) | rider nudged once; Telegram copies redraw within 5 s ("Marked ready by Ada", pickup moved); second Ready → "Already marked ready by Ada" |
| 5 PICKUP ALERTS | wait: with pickup = order + 5 min, `job_rider_pickup_alerts` fires −10 / +2 / +7 | **F on WhatsApp and Telegram** (reply to receipt) |
| 6 CANCEL + RE-DISPATCH | `SELECT dispatch_cancel_before_pickup(<dispatch_id>)` (the real function) | old receipt → "Rider … cancelled"; new offer to dummy riders; accept → new receipt, old copy deleted; Ready offered again |
| 7 PICKED UP + COMPLETE | *you* give the rider codes in the rider chat (real tools) or `UPDATE delivery_dispatch SET status='pickedup'` then `SELECT dispatch_complete_func(<dispatch_id>)` | receipt → "Picked up", then H "✅ Delivered" on both channels |
| 8 TAKEAWAY | Inserts a takeaway order (`payment_status = 'test_no_payment'`, see the takeaway caution above); *you* accept + choose pickup. Optional 8b: same with `pay_at_rest` | **E on both**; Ready → customer event once (8b: also the `💷 Pay at restaurant` line, and one print-only payment-service request) |
| 9 TIMEOUT | Inserts a delivery order and back-dates `dtts` past `RESTAURANT_CONFIRMATION_TIMEOUT` (or waits) | **C on both**, after the auto-accept update |
| 10 FEEDBACK | comment block with the `curl -X POST $ORDELO_APP_URL/customer-hooks/restaurant-feedback …` for `rest_ref STRK` | **I on both** |

**Race test (optional):** add a second dummy rider. In stage 3 both riders get the offer; the first accept wins and only one
receipt is sent per chat. In stage 4, tap Ready on Telegram and WhatsApp at the same moment: exactly one rider nudge.

**WATCH IT** queries:
- `ready_at, ready_by, ready_dispatch_id, pickup_time, pickup_time_initial, pickup_adjusted_by` for the test orders;
- `t_sent_messages` rows by `kind` (`order_card` / `receipt` / `notice`) with `card_status`, `state` and `dispatch_id`;
- `t_receipts_stale('rest_admin')`;
- `rider_pickup_alert` checkpoints;
- `order_customer_event` for the test orders.

---

## 8. Steps, each with its own verification and regression gate

Labels as in the main plan: **offline / isolated database / live Telegram (+ live WhatsApp)**. A step is done only when its
gate passes: baseline numbers unchanged except the new tests (all passing) and the step-0 fixes.

### Step 0: clean baseline (small PR or first commit of PR 1)
- Make the STRK invite insert in `test_create_t_order_alerts.sql` conditional (`WHERE NOT EXISTS (SELECT 1 FROM t_invites WHERE rest_ref='STRK' AND status='claimed')`).
- Add `pickup_date` to `minimal_schema.sql`.
- Pin UTC in `tests/sql/conftest.py` (`conn.execute("SET TIME ZONE 'UTC'")` in `_connect`).
- **Gate:** offline 853 passed / 1 known failure. Isolated DB: **140 passed, 0 failed**, with and without `PGTZ`.

### Step 7a: migration + SQL tests (isolated database)
- Write `restaurant_ready_adjust_notices.sql` (§4) and `test_restaurant_ready_adjust_notices_sql.py` (§6.1) test-first: each
  RPC result value gets a red test, then the SQL.
- **Gate:** all §6.1 tests pass; the migration applies twice in a row (idempotent); the old SQL suite is unchanged. Evidence label:
  *isolated database*.

### Step 7b: `restaurant_actions` + WhatsApp switched (offline)
- §5.1, §5.2. TDD on `test_restaurant_actions.py` and the new WhatsApp handler tests.
- **Gate:** every existing `test_on_callback_wa_handler.py` and `tests/regressions/test_p5_regressions.py` test passes unchanged
  (their reply strings are the contract), plus the new ones; full offline suite = baseline + new.

### Step 7c: notifier + Telegram receipts + taps + refresh route (offline)
- §5.3 (`KitchenReceipt`, `TakeawayReceipt` only), §5.4 first two rows, §5.5, §5.7.
- **Gate:**
  - WhatsApp parity tests for D and E pass (the recorded `admin_order_reciept` / `takeaway_admin_order_receipt` calls are
    identical to the pre-change calls);
  - dispatcher-boundary receipt tests pass, including every scenario row of the main plan's verification loop (allowed actor,
    wrong actor, revoked, stale button, repeated update, WhatsApp vs Telegram race, downstream failure, group-shaped update);
  - full offline suite = baseline + new; `ruff check .` clean.

### Step 7d: live check of Phase 7 (owner + agent)
1. **Offline first:** tests prove three things, and the results go into the §7 script header:
   - `capture_delivery_payment` / `cancel_payment` on a `payment_mode = 'test'` order go only to the test service and, on its 4xx, log and return `None`;
   - `capture_takeaway_payment` with `payment_status = 'test_no_payment'` returns before any HTTP call;
   - `generate_product_order_summary` (called by `gen_capture_payload`) makes no outside call for the fake order, or the
     header names the one it makes.
2. Owner applies the migration (operator step), schedules `job_t_receipt_refresh`, deploys PR 1 (or runs it locally behind the
   tunnel, `docs/local-testing-runbook.md`).
3. Run script stages 0–4, 6, 7 (delivery), then 8 (takeaway). Fill the evidence table:
   `boundary | action | observed | label | not verified`. Example row:
   `Telegram Ready tap | tap on STRK-TEST-… | rider WhatsApp "food ready", copies redrawn, ready_by set | live Telegram + live WhatsApp | phone sound`.
4. **WhatsApp regression, live:** the WhatsApp receipt text and buttons look exactly as before (compare with a screenshot from a
   pre-change order); the WhatsApp Ready, +10 and +20 buttons still work; the rider receives the same messages.
- **Gate:** every stage row observed on both channels; the `t_sent_messages`/summary columns match the WATCH IT expectations.

### Step 8a: plain notices (offline)
- §5.3 remaining notices, §5.4 remaining rows, §5.6; delete the dead `wa_senders` functions and their two tests.
- **Gate:** WhatsApp parity tests for C, F, H and I. `test_notify_rest_admins_rider_alert_*` (6 tests) and the timeout-handler
  tests in `test_delivery_hooks.py` / `test_takeaway_hooks.py` pass with only the patch-target change. Full offline suite =
  baseline − 2 deleted dead-code tests + new.

### Step 8b: live check of Phase 8
- Script stages 5, 7 (H), 9, 10, then a full re-run of stages 0–10 on the final build.
- **Gate:** C, F, H and I observed on both channels; WhatsApp texts unchanged; notice audit rows present.

### Step 9: regression sweep before merge (both PRs)
- `pytest -q tests` (offline) and `pytest -q tests/sql` (isolated DB) compared against §0;
  `pytest tests/channels tests/watomation/routers -q` as the main plan asks; `ruff check .`.
- Report: numbers vs baseline, the one known failure still listed, new tests count, anything skipped and why.

---

## 9. Docs to update in the same change (main plan "Docs to update per phase")

- `docs/telegram-layer.md`:
  - flow (§3.1 here) and file map;
  - **§6 cross-reference rows** for every new column and function (defining file, Python caller, tests);
  - not-done list and change log entries for 7 and 8.
- `docs/telegram-layer.html`: the `FLOWS`, `FILES`, `XREF`, `TODO` and `CHANGELOG` arrays.
- `docs/adr/0011-…md`: **Amendment 3** (D28–D38: both channels, the shared Ready/adjust RPCs, receipts follow the DB).
- `docs/alerts-and-notifications.md`: restaurant-admin rows now list both channels.
- `CONTEXT.md`: terms *Kitchen receipt*, *Ready (per dispatch)*, *Notice*, *Receipt status key*.
- `.claude/skills/database-operations` tables reference: the new columns, `t_sent_messages.kind` values, the new job.
- `docs/callback_handlers.md`: the WhatsApp handlers now call `restaurant_actions`.
- Main plan: status rows 7 and 8, then the phase summary once done.
- `restaurant-agents`: already done in this session (`docs/to-do.md` section, new `CLAUDE.md`).

## 10. Operator steps (owner only)

1. Before PR 1: run `restaurant_ready_adjust_notices.sql` in Supabase (test database first). Check with
   `SELECT proname FROM pg_proc WHERE proname LIKE 't_receipt%' OR proname LIKE 'restaurant_order_%';`.
2. Deploy PR 1; then `SELECT cron.schedule('job_t_receipt_refresh', '5 seconds', $$SELECT public.job_t_receipt_refresh()$$);`.
3. Run the §7 script (needs a dummy-town in-shift rider and a claimed STRK invite).
4. Deploy PR 2; run the §7 stages for Phase 8.
5. Rollback: unschedule `job_t_receipt_refresh` and redeploy the previous build. The new columns are nullable and unused by the
   old code, and the old WhatsApp handlers work against the new schema.

## 11. Risks and limits

- **Follow-up after `ok` is not transactional with the RPC.** If the process dies between the Ready RPC and the rider nudge, the
  nudge is lost and a re-tap says "already ready". This is the same exposure as today's path (no record at all). Mitigation: the
  receipt shows "Ready" so the admin can phone the rider. A trigger-driven follow-up stays possible later.
- **Old WhatsApp receipt buttons without `order_number`** (sent before that field existed) keep the legacy gate path, which has
  no RPC record. They are rare and can be removed after one release.
- **Order card vs receipt pickup:** the card keeps the first chosen time; the receipt shows the adjusted one (§4.4).
- **Takeaway 'completed'**: nothing sets it today, so takeaway receipts stay at "Ready" (not wrong, just never "Collected").
- **Notices are best-effort.** No retries; a notice that fails is logged.
- **Unauthenticated `/telegram/rest-admin/order-alerts`** now also accepts `receipts`. The worst case is a redraw from the
  database; nothing can change an order (same as today).
- **Shared `ORDELO_APP_URL`**: the receipt job calls whichever instance it points to (main plan, known limits).
- **Phone audibility** is still unproven (pilot prerequisite, main plan).
