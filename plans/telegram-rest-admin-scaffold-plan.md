# Telegram restaurant-admin bot — plan

**Repository:** `OrdeloAgent`. **Last updated:** 15 October 2026 (phases 1–6 complete and live-verified).
**What exists, in detail:** [`docs/telegram-layer.md`](../docs/telegram-layer.md) (+ [interactive companion](../docs/telegram-layer.html)): file map, flows, RPC cross-reference table, change log.
**Architecture decision record:** [ADR 0011](../docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) (Amendments 1 and 2).
**Related requirements:** project doc `claude/restaurant-admin-attention-requirements.md` (R1–R3, WhatsApp side). This plan
does **not** implement R1 auto-decline, R2 or R3.
**Full original spec of phases 1–6** (code sketches, SQL listings, scenario matrix, scaffold appendix) is kept in
[`archive/telegram-rest-admin-scaffold-plan-full-2026-10-15.md`](archive/telegram-rest-admin-scaffold-plan-full-2026-10-15.md). The code, migrations and `docs/telegram-layer.md` are the source of truth now.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Scaffold: settings, registry, webhook, restaurant-admin bot, invite onboarding (`t_invites`) | ✅ Done, live |
| 2 | Durable inbox (`t_inbox`), at-most-once per `(bot_key, update_id)` | ✅ Done, live |
| 3 | Shared decision functions (`restaurant_order_decide` / `_set_pickup`); R1-a terminal decline for delivery; WhatsApp switched to them | ✅ Done, live |
| 4 | Order cards: reminders 0/15/30/45 s, ledger, 5-s sweep, housekeeping | ✅ Done, live |
| 5 | Telegram taps: Accept, Decline, pickup time (`OrderCards.tap`) | ✅ Done, live |
| 6 | Verification loop: offline, isolated Postgres, **live Telegram** (Accept, Decline, pickup, WhatsApp-side accept redraw, timeout auto-accept redraw) | ✅ Done 15 Oct |
| 7 | **Ready and adjust-pickup actions on Telegram** | ⬜ To be planned by the owner (see "Next phases") |
| 8 | **Restaurant-facing notices on Telegram** (receipts, timeout/default-pickup notices, driver nearby, delivery complete, feedback, rider alerts to admins) | ⬜ To be planned by the owner (see "Next phases") |
| — | Restaurant group chat (D27) | Later; designed not to be blocked |
| — | Rider bot | Later, not in this plan (ADR 0012) |

Known failing test, not ours: `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`
(also fails on a clean checkout).

---

## Rules for every new phase

1. **RPC pattern.** Each RPC is defined in its migration next to its table, `REVOKE ALL ... FROM PUBLIC, anon, authenticated`,
   called with `client_ordelo_service`, wrapped by one Python module whose docstring names the SQL file and maps function → RPC;
   the SQL header names the Python callers. Update `docs/telegram-layer.md` §6 + change log and the `XREF`/`FILES`/`CHANGELOG`
   arrays in `docs/telegram-layer.html` in the same change (`CLAUDE.md`, "Database-backed logic").
2. **No in-process state.** Gunicorn runs up to 3 workers; every "first one wins" is decided in SQL. The Supabase client is
   synchronous: wrap calls in `asyncio.to_thread`.
3. **Telegram call rules** (learned from the hung Accept tap): the bot session has a 10 s timeout and 5 s keepalive
   (`config/tgram_setting.py`); answer a callback with `answer_quietly` (3 s bound, never raises); never let the answer gate a
   refresh; send/edit per destination in parallel (`asyncio.gather`); the webhook has a 25 s limit. Callback data is limited to 64 bytes.
4. **Authorise by `from_user.id` only** (D14, D27), address by `tcid`; never assume a private chat outside invite onboarding.
5. **The app never calls `set_webhook`/`delete_webhook`.** `allowed_updates` stays `['callback_query', 'message']`.
6. **No `DELETE` without explicit approval** (database-operations skill). The daily housekeeping job is the owner-scheduled exception.
   Agents never run migrations; the owner does (operator steps).
7. **Verify with the `telegram-vertification-loop` skill** and label evidence *offline / isolated database / live Telegram*.
   Never test SQL against the shared database.
8. **Real-endpoint tests with fake database rows (owner rule, 15 Oct).** Wherever possible, a phase's plan includes a re-runnable
   SQL script that inserts fake rows and drives the real endpoint and real code path against a real Telegram chat, with a
   reset-by-status step. Reference: `ordelo_datamodels/test_support/test_create_t_order_alerts.sql` (fake `STRK-TEST-*` delivery
   order in `restaurant_unconfirmed`; re-running wipes the earlier test orders and their `t_order_alerts` / `t_sent_messages` /
   `debug_log` rows; deliberately has no `food_order`, so the existing webhook does not trigger payment or customer messages).
   Pair it with an isolated-database test of the script itself (`tests/sql/test_order_test_script_sql.py`). Prerequisite for
   cards to arrive: a **claimed** `t_invites` row for the order's own `rest_ref` (a chat linked under another restaurant gets nothing).

---

## What was built (summary; details in `docs/telegram-layer.md`)

```
order created → delivery_summary / takeaway_summary (restaurant_confirmation_status, status, restaurant_admin, pickup_time, dtts)
   ▲ restaurant_order_decide / restaurant_order_set_pickup   shared by WhatsApp and Telegram (phase 3)
   │    ▲ t_order_decide / t_order_set_pickup                Telegram wrappers: D14 authorisation, then the shared call
 t_order_alerts (schedule)  t_sent_messages (ledger, cleanup only)  t_inbox   t_housekeeping() daily
 job_t_order_alerts() every 5 s: seed → cancel → due reminders → stale cards → POST /telegram/rest-admin/order-alerts (2xx → mark)

Telegram tap → webhook → Dispatcher → InboxMiddleware → orders router → OrderCards.tap
Sweep POST   → telegram_order_alerts.py → OrderCards.remind / refresh
WhatsApp tap → on_callback_wa_handler.py → utils_common/order_management/restaurant_decision.py
```

| Module | Interface | Hides |
|---|---|---|
| `utils_common/order_management/restaurant_decision.py` | `decide`, `set_pickup`, `describe` | RPC names, race handling, table choice |
| `channels/telegram/inbox.py` | `InboxMiddleware(bot_key)` | claim/finish RPCs, fail-open policy |
| `channels/telegram/rest_admin/order_cards/` | `OrderCards`: `remind`, `refresh`, `tap`; value `OrderRef` | destinations, authorisation, DB re-checks, send→record→delete order, ledger states, per-viewer card, events, toasts, Telegram error mapping |
| `channels/telegram/replies.py` | `answer_quietly` | callback-answer timeout and failure handling |

The card (`order_cards/model.py`) is an immutable `Card` changed only by events (`Reminded`, `Accepted`, `Declined`,
`PickupChosen`, `AutoAccepted`, `Vanished`); every text, button and toast is composed there. Status keys
(`awaiting/accepted/pickup_set/declined/auto_accepted/gone`) match SQL `t_order_card_status()`; change both together.

Migrations (owner ran all): `create_t_invites.sql`, `create_t_inbox.sql`, `restaurant_order_decision.sql`, `create_t_order_alerts.sql`.
Cron: `job_t_order_alerts` every 5 s, `t_housekeeping` daily 03:20. To switch alerts off: blank `TGRAM_ORDER_ALERT_OFFSETS_SECS`
or `cron.unschedule('job_t_order_alerts')`.

## Agreed decisions (settled; the numbering is referenced from code and docs)

| # | Decision |
|---|---|
| D11 | **Parallel channels.** Linked admins get Telegram and the existing WhatsApp message; the first decision on either channel wins. |
| D12 | **Reminders only**: 0, 15, 30, 45 s after `dtts`, then stop. No answer → the existing timeout auto-accept decides. R1 auto-decline out of scope. |
| D13 | The database schedules reminders (5-s pg_cron sweep, checkpoints `pending/sent/superseded`, `rider_pickup_alert` pattern). |
| D14 | Receive and act only with a `claimed` `t_invites` row for the order's `rest_ref` (bot `rest_admin`) **and** that invite's phone in `restaurant_master.admins`. Checked at every send and every tap, in SQL. |
| D15 | Buttons Accept and Decline. Delivery decline sets `delivery_summary.status = 'declined'` atomically (R1-a fixed), cancels payment, tells the customer. |
| D16 | Customer on delivery decline mirrors takeaway: `cancel_payment` unless pay-at-restaurant; web: `queue_release` fallback + `restaurant_declined` event; WhatsApp customer: direct text from Ordelo's number. |
| D17 | The WhatsApp Decline button stays commented out; Decline is Telegram-only. |
| D18 | One SQL function decides (`restaurant_order_decide`), used by both channels; losing taps get a graceful reply naming who decided. |
| D19 | "by X" = Telegram first name of that phone's claimed invite, else `…` + last 4 digits (SQL `restaurant_admin_label`). |
| D20 | Pickup on Telegram: the accepter's card becomes pickup buttons (order time + 5/15/25 min); shared `restaurant_order_set_pickup`. WhatsApp pickup buttons still go to WhatsApp admins. |
| D21 | Inbox: claim first, skip duplicates (at-most-once), fail open if unreachable. |
| D22 | Daily `t_housekeeping()` deletes inbox rows > 7 days and closed ledger/checkpoint rows > 30 days (`TGRAM_INBOX_RETENTION_DAYS`, `TGRAM_LEDGER_RETENTION_DAYS`). `t_invites` is never purged. |
| D23 | Scope: delivery and takeaway orders starting `restaurant_unconfirmed`; no per-restaurant switch; configured auto-accept never alerts. |
| D24 | Repeat = new message, then delete the older copy in that chat. DB is authoritative, checked before and after every send; the ledger is cleanup only. Decided orders are edited to the final state, never deleted. |
| D25 | `tuid` (Telegram user id) authorises; `tcid` (chat id) addresses. New tables use `tuid`/`tcid`; `t_invites` keeps `telegram_user_id`/`telegram_chat_id`. |
| D26 | The order card is one deep module (`OrderCards`) over an immutable `Card` changed only by events. |
| D27 | Group-ready, not group-built (see below). |

## Future: restaurant group chat (D27 — not built)

Cards go to **destinations** returned by one SQL function (`t_order_card_destinations`); a group is a new row source
(`UNION ALL` linked groups with `tuid`/`phone` NULL), a `t_chat_links` table filled by `/link <invite>` in the group, `my_chat_member`
in `allowed_updates` to notice removal, and `Viewer(shared=True)` wording. Authorisation is unchanged (the tapper's `tuid`). Open:
whether admins in a linked group still get private copies. Rules until then: never authorise from `chat.id`, never assume
`chat.type == "private"` outside invite onboarding, never key a card or ledger row by `tuid` alone.

## Known limits and risks

- **Unauthenticated** `/telegram/rest-admin/order-alerts` (like `/delivery-hooks/*`): worst case someone triggers reminders or
  final-state edits; it cannot change an order.
- **Fail-open inbox:** decisions stay atomic, so a double delivery cannot double-apply.
- **Alias order prefixes** (`_REST_REF_ALIAS_MAP`) get no cards.
- **Pickup times in the past** can be offered (order time + 5/15/25, WhatsApp parity); R1 notes a filter, not done.
- **No truncation** to Telegram's 4096-character limit; long order numbers drop buttons rather than fail (64-byte callback data).
- **Cards sent before a migration** are answered but not redrawn.
- **Orphan copy:** a send that times out after Telegram received it can leave an untracked copy.
- **Shared `ORDELO_APP_URL`:** one database serves test and local runs; the sweep calls whichever URL is set (point it at the tunnel for local tests).
- **Takeaway customer messaging and delivery decline use Ordelo's number**, not the restaurant app (ADR-0006 follow-up, R1).
- R2, R3 and R1 auto-decline remain separate (`claude/restaurant-admin-attention-requirements.md`).

---

## Next phases (owner is adding the detailed plan)

Source survey (15 Oct), so the plan starts from facts. Handoff §12 steps 3–5 are what remains of "phase one".

**Phase 7 — ready and adjust-pickup actions.** Today these are WhatsApp buttons on the receipt sent after accept
(`utils_common/waba_utils/wa_senders.admin_order_reciept` / `takeaway_admin_order_receipt`), handled in
`watomation/on_callback_wa_handler.py`: `admin_collection_ready` ("Ready – Notify Rider"), `admin_takeaway_ready`,
`admin_adjust_pickup_time` (+10/+20 min). Natural shape: extend `OrderCards` and the SQL wrappers rather than add a new component;
the actions must still reach the assigned rider through the existing workflow (handoff step 4).

**Phase 8 — restaurant-facing notices.** WhatsApp-only senders to route through a transport-neutral "notify the restaurant's admins"
path (Telegram when linked, WhatsApp fallback): `admin_order_reciept`, `takeaway_admin_order_receipt`, timeout auto-accept notice and
default-pickup notice (`_handle_restaurant_timedout`), `admin_delivery_driver_nearby`, `admin_delivery_complete_notification`,
`send_restaurant_feedback_notification` (`customer_hooks.py`), `notify_rest_admins_rider_alert` (`delivery_hooks.py`), admin sends in
`location_hooks.py` and `delivery_hooks.py`.

**Pilot prerequisites (handoff §12 step 5):** acknowledgement target, escalation owner, runbook, and a 2–3 restaurant Android pilot
(locked, muted, battery-saver phones). Backend persistence does not prove the phone makes a sound.

*(Owner: add the Phase 7 and Phase 8 detail here, including a real-endpoint fake-row test script per rule 8.)*

---

## Verification loop (every phase; the `telegram-vertification-loop` skill)

1. Trace the boundary: update/event → webhook → dispatcher → inbox middleware → handler → `OrderCards`/wrapper → RPC → Bot API call; name the observable result and durable state per actor.
2. Test first where practical. Dispatcher boundary offline: real `Dispatcher` + `RecordingSession` (`tests/channels/telegram/conftest.py`); assert method, `tcid`, text, keyboard, callback answer, send count; check the 64-byte limit and HTML escaping.
3. Webhook boundary offline (`test_telegram_webhook.py`, `test_telegram_order_alerts.py`): assert the `t_inbox` outcome, not just HTTP 200.
4. **Isolated database** (`tests/sql/`, `run_sql_tests.py`, pgserver; refuses non-local hosts): every migration and RPC, races with two connections, the test script. Never the shared database.
5. **Live Telegram** with the owner, using the fake-row script (rule 8). A successful Bot API call is API acceptance, not proof a human saw it.
6. Rerun focused tests and the whole suite (`pytest tests/channels tests/watomation/routers -q`); keep the known failure explicit; update `docs/telegram-layer.md` and its change log.
7. Scenario rows to cover each time: allowed actor, wrong actor, revoked identity, stale button, repeated update, competing requests (Telegram vs WhatsApp), downstream failure, `from_user.id` ≠ `chat.id` (group-shaped).

Evidence report per scenario: `boundary | command or action | observed | label (offline / isolated database / live Telegram) | not verified`.
Never claim SQL behaviour, durability, user-visible delivery, payment or fulfilment from mocked Bot API calls or an HTTP 200 alone.

## Docs to update per phase

`docs/telegram-layer.md` (flow, file map, §6 cross-reference rows, not-done list, change log) and `.html` (`FLOWS`, `FILES`, `XREF`, `TODO`,
`CHANGELOG`); `CONTEXT.md` terms; an ADR 0011 amendment for any new decision; `docs/alerts-and-notifications.md` for restaurant-admin rows;
database-operations skill tables reference for new tables.

## Operator steps (owner; the implementing agent must not do these)

Phases 2–5 done. For each new migration: run it in Supabase, deploy, then smoke test. Test loop: run
`ordelo_datamodels/test_support/test_create_t_order_alerts.sql` for a fresh STRK order (needs a claimed STRK invite for 447448440754).

## Appendix — Phase 1 scaffold (✅ done, commit `8d26ed3`)

Settings (`config/tgram_setting.py`, keys `tgram_<bot_key>_{bot_token,bot_username,webhook_secret,webhook_base_url}`, required at start),
bot registry (`channels/telegram/bots.py`), webhook route (`/telegram/{bot}/webhook`, secret check, always 200), restaurant-admin bot
`@OrdeloRestaurantBot`, invite onboarding (`t_invites`, `t_claim_invite`, `/start <code>` + confirmation tap; contact share dropped), tables use
the `t_` prefix, service-role client `client_ordelo_service`. Full original text is in the archive file above.
