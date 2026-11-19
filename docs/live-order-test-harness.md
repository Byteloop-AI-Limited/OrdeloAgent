# Live order test harness (STRK fake orders)

`ordelo_datamodels/test_support/test_restaurant_notices.sql` creates fake **STRK-TEST-*** orders so you can walk the whole
restaurant-admin journey on WhatsApp **and** Telegram with your own phone, without a real customer, restaurant or rider.
Use it for any change that touches the order card, the kitchen receipt, Ready / +10 / +20, rider pickup alerts, the
restaurant notices (auto-accept, delivered, feedback), dispatch or the restaurant webhooks. Written for Phases 7-8 of the
Telegram bot ([plan](../plans/telegram-phase-7-8-kitchen-actions-and-notices.md)); older, smaller sibling:
`test_support/test_create_t_order_alerts.sql` (order card only).

Run it **one stage at a time** in the Supabase SQL editor. Every stage can be repeated; STAGE 0 wipes earlier STRK test
orders. Offline tests that keep the script honest: `tests/sql/test_restaurant_notices_script_sql.py` (real tables and
functions in a throwaway database) and `tests/regressions/test_p7d_test_order_safety.py`. **Change the script and those
tests in the same commit.** Do not run SQL for testing on the shared database other than this script's own stages.

**Rider on Telegram.** To take the rider side of a fake order in `@ByteloopRidersBot` instead of WhatsApp, run
`ordelo_datamodels/test_support/test_rider_telegram_jobs.sql` alongside this script (its STAGE 0 and 0b first, then this
script's STAGE 0-2b, then its STAGE 1-8: offer, Accept, job card, agent chat, codes, missed and expired offers). Offline proof:
`tests/sql/test_rider_telegram_jobs_script_sql.py`. Since R2 STAGE 0 here also closes the rider threads of the fake jobs.

**Breaks, locations and admin pauses (R5-R6).** `ordelo_datamodels/test_support/test_rider_pauses_and_locations.sql` walks `/shift`, `/off`, `/on`, the "ends soon" / "back on" messages, a location shared in Telegram, and the restaurant bot's `/off` / `/on` with the last-admin guard. Its only writes are UPDATEs of `pauses` rows for the owner's phone; proof: `tests/sql/test_rider_pauses_and_locations_script_sql.py`.

## Safety (why it is safe to run against the shared database)

- Every row it creates or deletes has an order number starting `STRK-TEST-` (a test fails if any DELETE or UPDATE is not scoped to it).
- Every order carries an exact `TEST3100` item, so payment mode is `test` and payment calls go to the Wren TEST service only
  ([test-orders.md](test-orders.md)); a delivery goes only to riders in `ordelo_config.overwatch_list`; a takeaway creates no rider job.
- Town is always `dummy`; customer is your own number (`447448440754`) and channel `whatsapp`: nothing reaches a real person.
- The script only READS `restaurant_master` and `rider_master`. It never changes them.

## One-off prerequisites (the PREREQUISITES CHECK query shows each)

| Need | How |
|---|---|
| Migrations applied, cron jobs `job_t_order_alerts`, `job_t_receipt_refresh`, `job_rider_pickup_alerts` + the dispatch jobs scheduled | operator steps in each migration's footer |
| `restaurant_master` row for `STRK` with **your phone in `admins`** and a **non-empty `rest_id`** | order webhooks look the restaurant up by `rest_id`. Once: `UPDATE public.restaurant_master SET rest_id = 'STRK01' WHERE rest_ref = 'STRK' AND rest_id IS NULL;` |
| A claimed `t_invites` row for `STRK` (Telegram) | STAGE 0 copies your existing linked chat if none exists |
| A rider in town `dummy`, `status = 'active'` (the dispatch gate since 22 Oct 2026), in shift, **also in `overwatch_list`** (a second one for race tests) | owner-managed rows |
| `ORDELO_APP_URL` pointing at the instance under test | tunnel for local runs: [local-testing-runbook.md](local-testing-runbook.md) |

## Stages

| Stage | What it does | You then | Expect (both channels unless stated) |
|---|---|---|---|
| 0 | Reset; link your chat to STRK | | |
| 1 | New delivery order (notes, small-order fee, modification, TEST3100) | wait ~5 s | Telegram order card + reminders; WhatsApp confirmation prompt |
| 2 | Shows state | tap **Accept**, then a pickup time | status `unassigned`; delivery card and WhatsApp pickup reply carry the hold until the kitchen receipt |
| 2b | Releases the order to riders (what `process_delivery()` does in production) | run it **after** 2 | dispatch offer on the dummy rider's WhatsApp |
| 2c | Inspect reminder ledger and offer state (read only) | wait, decline, pause, or accept as described in the script | one live Telegram copy; steps f/g check that a plain decline preserves the schedule and cancellation starts a new dispatch round |
| 3 | Shows state | rider accepts the offer in the rider chat, then wait for assignment | **🍳 Please start preparing now / Rider found · ready for pickup at …**, with Ready / +10 / +20 on both channels after assignment |
| 4 | Shows state | Ready on one channel, +10 on the other, Ready again | rider nudged **once**; +10 moves the start detail while open; Ready restores the Telegram receipt heading; second Ready says already ready |
| 5 | Waits | wait | rider pickup alerts to the restaurant (Telegram replies to the receipt) |
| 6 | Cancel + re-dispatch | rerun 2b to release the STRK order | old receipt "no longer on the job"; new receipt after the next rider is assigned |
| 7 | Picked up + complete | rider codes (or the two forcing statements) | "Delivered" notice; receipt becomes done |
| 8 / 8b | Takeaway (`test_no_payment` / optional `pay_at_rest`) | accept + pickup, then Ready | no hold; “🍳 Please start preparing now / Ready for collection at …” (8b: "Pay at restaurant" line); customer event once |
| 9 | Delivery order older than the timeout, no rider job, never answered | wait for the sweep (10 s) | `SELECT * FROM restaurant_confirmation_policy('STRK')` first: `accept` → auto-accept notice, card "Auto-accepted"; `decline` → status `declined`, auto-declined notice to admins, card "Auto-declined (no answer in time)" |
| 9b | Same, but already accepted by an admin with no pickup time | wait for the sweep | always auto-accepted (notice and card include the delivery hold), whatever the action key says |
| 10 | Restaurant feedback | run the `curl` in the script | feedback notice, no reply target |

The script's bottom section (**WATCH IT**) has ready-made queries for Ready bookkeeping, every Telegram copy
(`t_sent_messages`), copies waiting for the sweep (`t_receipts_stale`), customer events, your taps (`t_inbox`) and who is linked.

## WhatsApp regression pass (do after the Telegram pass)

Repeat the stages tapping **only on WhatsApp**. The kitchen instructions are intentionally changed (ADR 0015); the action and payment rules remain:

1. **Stage 1:** the confirmation prompt text and Accept / Decline buttons are unchanged.
2. **Stage 2:** Accept, then a pickup-time button works **within 15 seconds**, replying “Pickup time set to *…*.” and the delivery hold; a second admin tapping afterwards is told who decided.
   Leave it longer than ~25 s and the default pickup time is applied instead ("auto-accepted due to confirmation timeout"), and a
   late pickup tap is answered as already set. That is the 15-second pickup grace, also worth checking once on purpose.
3. **Stage 3:** the WhatsApp kitchen receipt header is “🍳 Please start preparing now”, its body starts “Rider found · ready for pickup at …”, then the order number and retained restaurant code, rider, items, notes and +10 / +20 / Ready buttons. Check the Telegram phone notification preview separately; a rich heading test does not prove its preview.
4. **Stage 4:** Ready on WhatsApp nudges the rider once and a repeat answers "Already marked ready by …"; +10 / +20 move the pickup and the rider is told; the Telegram copies follow within ~5 s.
5. **Stages 5, 7, 9, 10 and 8:** rider alerts, completion and feedback wording stay unchanged. Delivery auto-accept appends the hold; takeaway auto-accept does not. Takeaway receipts say “Please start preparing now / Ready for collection at …” and never hold.
6. **No rider:** on a fresh accepted delivery, run 2b and let offers expire: restaurant admins on both channels get “❌ No rider found for … / The order is cancelled — please don't prepare it.” as a reply to the card where its message ID is available; overwatch still gets one alert and payment/customer events remain unchanged. Repeat for configured auto-accept.
7. **Race:** Ready on both channels at the same moment: one nudge, one winner.

Record the result per stage as: `boundary | action | observed | label | not verified` (labels: offline, isolated database, live Telegram, live WhatsApp).

## Rider exit guard

Repeat with a Telegram rider and a WhatsApp rider.

1. Before pickup, ask to close the job. The rider gets a confirmation prompt. Typing “yes” leaves the assignment active, as does tapping **No, keep it**.
2. Ask again and tap **Yes, cancel job**. Verify that recording the reason closes the rider thread and that stage 2b starts a fresh dispatch round.
3. On a new assignment, verify pickup with the restaurant code. Ask to cancel and then ask to close the job. Each request is refused and alerts overwatch once. The thread stays open and the dispatch stays `pickedup` until normal completion using the customer code.

## Troubleshooting (real failures seen)

| Symptom | Cause | Fix |
|---|---|---|
| `restaurant_master: Input should be a valid dictionary ... None` in `/delivery-hooks/restaurant-confirmation-request` | the order's `rest_id` matches no `restaurant_master` row (or STRK has no `rest_id`) | set STRK's `rest_id` once (above); the script now stops with this advice |
| `fmt_uk_time ... NoneType` in `wa_send_delivery_dispatch_request_to_rider` | a rider job existed before the restaurant accepted, so there was no pickup time | create the rider job only in STAGE 2b, after Accept + pickup |
| Nothing arrives | prerequisites, cron jobs, `ORDELO_APP_URL`, `t_order_card_destinations` count | the script's "NOTHING ARRIVES?" checklist |

## Extending it

Add a stage as a new `-- ===== STAGE n: TITLE =====` block (the offline test splits on that marker), keep every DELETE / UPDATE
scoped to `STRK-TEST-%`, keep town `dummy` and the TEST3100 item, then add a test in `tests/sql/test_restaurant_notices_script_sql.py`
and update the stage list there and in this page.

## Admin onboarding harness (roster, P1)

`ordelo_datamodels/test_support/test_admin_onboarding.sql` exercises the roster on fake phones `4477009009xx` and adds/removes only those from STRK `admins`. Stages: 0 reset, then link, profile, channel changes, unlink, destinations per channel, pause, transition check (read-only, old invite-only admins still routed), 12 manual live. Run `test_restaurant_notices.sql` afterwards as the WhatsApp regression pass. Channel matrix to eyeball on the real STRK admin: before linking, WhatsApp only; after linking, Telegram only (from P2); `/channels` Both, both.
