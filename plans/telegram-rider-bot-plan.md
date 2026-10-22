# Telegram rider bot (@ByteloopRidersBot): plan

**Repository:** `OrdeloAgent`. **Written:** 22 October 2026 (design session with the owner, decisions D39–D54).
**Status:** R0 written. **R1 live** (migration applied and onboarding tested live by the owner on 22 Oct: an existing rider
was linked and switched to Telegram; an unknown phone was asked for town and vehicle and registered). **R2-R4 live** (migration
applied, code deployed, `/job` in the menu; the owner tested a rider job end to end on Telegram and on WhatsApp on 22 Oct). Next: R5.
**Builds on:** [`telegram-rest-admin-scaffold-plan.md`](telegram-rest-admin-scaffold-plan.md) (restaurant-admin bot, decisions D11–D38; detail in [`docs/telegram-layer.md`](../docs/telegram-layer.md)),
[ADR 0011](../docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) (Amendment 3),
[ADR 0012](../docs/adr/0012-rider-threads-follow-dispatch-assignments.md) (Amendment 1),
[ADR 0013](../docs/adr/0013-pauses-have-a-mandatory-end-and-are-computed.md) (new).
**Hard rule from the owner:** WhatsApp keeps working and its rider messages do not change. Telegram is added beside it.

## Why

On WhatsApp a rider can only be messaged inside a 24-hour window, so riders are asked every day whether they are working
(the shift question at 11:00 UTC). On Telegram a rider who has pressed `/start` can be messaged at any time. Telegram riders are
therefore **on by default** and step away with `/off` for a fixed time (6 h, 1 day, 3 days). The same pause pattern will be used for
restaurant admins' alerts.

## Phases

| Phase | What | WhatsApp change | Status |
|---|---|---|---|
| **R0** | This plan, ADR 0011 Amendment 3, ADR 0012 Amendment 1, ADR 0013, `CONTEXT.md` terms | none | ✅ written |
| **R1** | Scaffold: `rider_master` Telegram columns, `channel`, unique `rider_id`; dispatch gate (`status = 'active'`, not paused); onboarding RPCs; `pauses` table + `is_paused()` + sweep job (SQL only); rider bot settings (optional), registry, router with working `/start` onboarding, `/help`, `/whoami`; `ordelo/rider_messaging/` (interface, both adapters, fake); `ordelo/pauses.py`; tests and the live harness | dispatch skips non-`active` riders (owner checks statuses first) | ✅ live 22 Oct (migration applied, onboarding tested live) |
| **R2** | Rider thread per dispatch: `ORDELO-dispatch-<id>`, `rider_threads.sql`, runner and hook simplifications (below), one active rider thread per rider | thread ids only | ✅ live 22 Oct |
| **R3** | `ContextSchema.wa_client` → `messenger`; every tool, `respond_node` and rider hook send through `RiderMessenger`; `delivery_dispatch.channel` + `channel_msg_ref`; `for_dispatch()` | none (byte-identical, pinned by tests) | ✅ live 22 Oct |
| **R4** | Offers on Telegram: `ordelo/dispatch_actions.respond_to_offer()` shared by both channels; `ro1:` taps; `rj1:` job-card taps; `offer_closed` edits (missed, assigned, expired); `/job`; rider text on Telegram → agent; other-channel pointer reply | none (handler texts kept) | ✅ live 22 Oct |
| **R5** | Telegram location requests through WaLocation (`telegram_current`); `/off`, `/on`, `/shift`; `/pause-hooks/sweep` + `job_pause_sweep` scheduled; Telegram riders leave the daily shift question; shift "Yes" refused for non-active riders | WhatsApp riders unchanged | ⬜ |
| **R6** | Restaurant-admin pauses (`/off`, `/on` on the restaurant bot), last-admin guard, card and notice destinations skip paused admins | — | ⬜ |
| later | Race-hardening of assignment in SQL (ADR 0011 point 4); rename `wa_location*` to channel-neutral names; Telegram live location | — | not planned |

## Decisions (settled with the owner on 22 Oct 2026; numbers continue the restaurant plan's D11–D38)

| # | Decision |
|---|---|
| D39 | **Phone proof:** riders join only by Telegram's "Share my phone number" button. The contact is accepted only if `contact.user_id == from_user.id`. Typed or forwarded numbers are refused. One generic link for everybody (`t.me/ByteloopRidersBot?start=join`), no per-phone invites. |
| D40 | **Identity lives on `rider_master`**, not in a new table: `tuid`, `tcid`, `t_username`, `t_first_name`, `t_linked_at`, `phone_verified`; unique `tuid` (partial index). `rider_id` becomes `NOT NULL UNIQUE`. Deviates from ADR 0011 point 5 (Amendment 3). |
| D41 | **Unknown phone → new row**, `status = 'inactive'`, chosen town and vehicle, Telegram first name (`'TBD'` fallback). `is_in_shift` is not used as the gate (insert leaves its default). **`get_available_riders()` requires `status = 'active'`** (exact). The WhatsApp shift "Yes" will refuse non-active riders (R5). The owner activates with `status = 'active'`. |
| D42 | **Link conflicts, one RPC (`t_rider_link`):** phone linked to another Telegram account → the link **moves** (ops alert); this Telegram account linked to another rider → **refused** (ops alert); same person again → refresh `tcid`/names. |
| D43 | **One channel per rider:** `rider_master.channel` (`'whatsapp'` default, `'telegram'` set by linking; operator can flip back). Everything we start goes to that channel only. Not both (restaurants' D28 does not apply). |
| D44 | **Channel fixed per dispatch:** `delivery_dispatch.channel` copied from the rider when the offer row is created; the offer, Accept and the whole job conversation stay there. A rider message on the other channel during a job gets a fixed "your job X is on Telegram/WhatsApp" reply and is not passed to the agent. |
| D45 | **`RiderMessenger` replaces `wa_client`** in the agent's run context and in rider hooks: `say`, `send_place`, `request_location`, `send_contact`, `mark`, `offer_job`, `offer_closed`. Text is written once in WhatsApp style; the WhatsApp adapter passes it through (byte-identical), the Telegram adapter renders HTML. `MsgRef` is opaque (WhatsApp: raw wamid, so running checkpoints stay valid; Telegram: `tg:<tcid>:<message_id>`). Built by `for_rider()` (R1) / `for_dispatch()` (R3). |
| D46 | **Thread per dispatch without changing the shared `thread` table:** new rider threads get `thread_id = ORDELO-dispatch-<dispatch_id>` (keeps the existing `<agent>-<suffix>` convention that `job_terminate_stale_active_threads_new` parses with `split_part(thread_id, '-', 1)`). Rider-only `rider_thread_open` (idempotent, `ON CONFLICT DO NOTHING`) and `rider_thread_close(thread_id)`. `create_thread`, `get_or_create_thread`, `make_threads_inactive`, the cron jobs, restaurant-agents and customer/WEB threads are untouched. Nothing parses the id: a dispatch computes its thread id. |
| D47 | **At most one active rider thread per rider**, enforced by `rider_thread_open` (opening B closes A, cancel reason recorded as not given). The scheduled stale-thread close closes a rider thread even when the cancel reason is missing; `retain_thread` stays `false` on rider threads. Inbound routing: actor → rider → their single active thread. |
| D48 | **Offer rules extracted once:** `ordelo/dispatch_actions.respond_to_offer(rider_id, dispatch_id, order_number, accept)` → `assigned | declined | gone | already_on_this_job | taken | cancel_own_job`. WhatsApp handler keeps its JSON payload and texts; Telegram uses `ro1:<dispatch_id>:a|d`, authorises by `tuid`, edits the offer after a tap. Race-hardening of assignment deferred. |
| D49 | **Missed / closed offers:** `delivery_dispatch.channel_msg_ref` stores the offer's `MsgRef`. `offer_closed(ref, order, reason)`: WhatsApp sends today's "picked up by another rider" text; Telegram **edits the offer to "Taken by another rider" and removes the buttons**, sending nothing new, so no late Accept is possible. `notify_missed_dispatches_hook` loops dispatches through it. |
| D50 | **Telegram location:** one-off location via the same WaLocation module and tables (`source = 'telegram_current'`, `tg:` inbound id in the existing unique column). Telegram **live** location is out of scope. |
| D51 | **Pauses (ADR 0013):** one channel-neutral `pauses` table for riders and restaurant admins, `ends_at` mandatory, durations only from `ordelo_config`. **Availability is computed** (`is_paused()` from the clock), so no job flips anyone back on; `job_pause_sweep()` only closes rows and sends "ends soon" / "back on" messages, marking on 2xx. A second `/off` replaces the end time (never stacks). |
| D52 | **Last-admin guard:** a restaurant admin cannot pause if no other admin of that restaurant would stay unpaused (`not_allowed`). Built in R6; `pause_start` refuses `rest_admin` (`not_supported`) until then. |
| D53 | **Telegram riders leave the daily shift question** (`enquire_shift_availability` selects `channel = 'whatsapp'`; linking sets `is_in_shift = true` once). Rider bot commands: `/start`, `/help`, `/whoami` (R1), `/job` (R4), `/shift`, `/off`, `/on` (R5). Plain text reaches the agent only when the rider has an active thread on Telegram; no AI intent detection on Telegram. WhatsApp dev commands stay WhatsApp-only. |
| D54 | **Rider bot is optional at start-up:** registered only when `tgram_rider_bot_token` is set (warning otherwise), so the scaffold can deploy before the bot exists; a token that is set but malformed, or a missing secret next to it, still fails fast. |

## `/start` and onboarding (D39–D42, built in R1)

```
t.me/ByteloopRidersBot?start=join   (any payload; group chats refused)
  t_rider_profile(tuid)
    linked, profile complete  -> "✅ You're already linked, Sam."
    linked, town/vehicle TBD  -> next sign-up question
    not linked                -> "Tap Share my phone number" [📞 Share my phone number]  (request_contact)
contact message
  contact.user_id != from_user.id            -> refused ("share your OWN number")               D39
  t_rider_link(tuid, tcid, phone, username, first_name)                                           D42
    linked         existing rider, first link -> channel 'telegram', is_in_shift true, phone_verified
    already_linked same account               -> tcid / names refreshed
    relinked       new account, same phone    -> link moves; ops alert (WhatsApp overwatch)
    registered     unknown phone              -> new row: status 'inactive', town/vehicle 'TBD'; ops alert
    tuid_taken     account linked elsewhere   -> refused; ops alert
    bad_phone      not 8-12 digits            -> refused
  needs_profile -> [town buttons]  t_rider_choices().towns         (rsu:t:<town>)
                -> [vehicle buttons] t_rider_choices().vehicle_types (rsu:v:<vehicle>)
                -> t_rider_set_profile(tuid, town | vehicle): fills 'TBD' only (locked otherwise)
                -> "✅ Thanks Priya! You're registered for Salisbury (bike). Ordelo will activate your account."
operator: UPDATE rider_master SET status = 'active' WHERE rider_id = ...   -> dispatchable from the next run   D41
```

No state is kept in the process: after the contact step every call is keyed by the tapping person's `from_user.id`; the phone
never travels in callback data. Choices are the distinct live values (`'TBD'` excluded, towns de-duplicated case-insensitively).

## Data model (no duplicated tables)

| Object | Change | Phase |
|---|---|---|
| `rider_master` | `rider_id NOT NULL UNIQUE`; `channel` (`whatsapp`\|`telegram`); `tuid` (unique), `tcid`, `t_username`, `t_first_name`, `t_linked_at`, `phone_verified`; `CHECK (tuid IS NULL) = (tcid IS NULL)` | R1 |
| `get_available_riders()` | `+ status = 'active' AND NOT is_paused('rider', rider_id, NULL)` | R1 |
| `pauses` | new, channel-neutral: `audience` (`rider`\|`rest_admin`), `principal` (phone), `scope` (`rest_ref` for admins), `starts_at`, `ends_at NOT NULL`, `ended_at`, `end_reason`, `reminded_at`, `announced_at`, `created_via`, `created_by`; one open row per person (unique partial index) | R1 |
| `thread` | **unchanged**. New rider rows use `thread_id = ORDELO-dispatch-<id>` via rider-only functions (`agent_threads/rider_threads.sql`) | R2 |
| `delivery_dispatch` | `channel` (stamped from the rider by the BEFORE INSERT trigger `trigger_delivery_dispatch_stamp_channel`, whatever the insert says), `channel_msg_ref` (offer `MsgRef`), `thread_id` (the dispatch's rider thread, written by `rider_thread_open`; partial index) | R2-R4 |
| `wa_location_observation` | `source` CHECK gains `'telegram_current'` | R5 |
| `t_invites` | unchanged; riders never use invites | — |

Files (all with the 13-section header): `core/rider_master.sql`, `telegram/t_rider_onboarding.sql`, `availability/pauses.sql`,
`availability/job_pause_sweep.sql`, `dispatch/job_create_dispatch.sql`, one-off `migrations/rider_telegram_r1.sql` (applied 22 Oct),
live harness `test_support/test_rider_onboarding.sql`. R2-R4: `agent_threads/rider_threads.sql`, `dispatch/delivery_dispatch.sql`,
one-off `migrations/rider_telegram_r2_r4.sql` (the ONE migration for R2-R4), live harness `test_support/test_rider_telegram_jobs.sql`
(with `test_restaurant_notices.sql`, whose STAGE 0 now also closes the rider threads of fake jobs).

## Modules (deep modules, small interfaces)

| Module | Interface | Hides | Phase |
|---|---|---|---|
| `ordelo/rider_messaging/` | `RiderMessenger`: `say`, `send_place`, `request_location`, `send_contact`, `mark`, `job_card`, `offer_job`, `offer_closed`; `for_rider()`, `for_dispatch()`, `dispatch_channel()`, `for_thread()`, `use_messenger()` | channel choice, addresses, pywa vs aiogram, WhatsApp-style → HTML, keyboards, callback packing, reply threading, reactions, edit-in-place | R1 (built), wired in R3 |
| `channels/telegram/rider_links.py` | `link`, `set_profile`, `choices`, `profile` | `t_rider_*` RPCs, link/move/register rules | R1 |
| `channels/telegram/rider/` | router factory, command menu | onboarding conversation, ops alerts | R1 |
| `ordelo/pauses.py` | `pause`, `resume`, `current` | durations policy, one-open-pause, extend-not-stack, races, expiry | R1 (built), used R5/R6 |
| `ordelo/agents/rider_threads.py` (+ `rider_threads.sql`) | `open_for_dispatch`, `touch`, `active_for_rider`, `describe`, `for_dispatch`, `close` → `RiderThread` / `OpenOutcome` | thread id format, the dispatch join, single-active rule, never re-creating a closed thread | R2 |
| `ordelo/agents/agent_runner.py` | `resolve_rider_thread(recipient, dispatch_id=, thread_id=)`, `run_rider_agent(thread, …)`, `run_rider_agent_w_custom_msg(…, dispatch_id=, thread_id=)` (returns `None` when no thread is open), `init_ordelo_graph` | which thread a run belongs to, checkpointer config, the run's messenger | R2/R3 |
| `ordelo/dispatch_actions.py` | `respond_to_offer(...) -> OfferOutcome`, `whatsapp_reply`, `record_offer_ref`, `close_open_offers` | stale tap, already on job, taken, own-job cancel; which offers are still open | R4 |
| `channels/telegram/rider/jobs.py` | router: `ro1:` / `rj1:` taps, `/job`, text | authorisation by `tuid`, background agent turns, the other-channel pointer | R4 |
| `ordelo/rider_shift.py` | `set_shift(rider_id, on) -> ShiftOutcome` | status gate, inflight check | R5 |

**Seam check (codebase-design):** `RiderMessenger` has two real adapters (WhatsApp, Telegram) plus the recording fake, so it is a real
seam, not a hypothetical one. The deletion test passes: without it, ~20 send sites would each branch on channel.

## Agent integration (R2, R3)

**Where the agent starts talking on Telegram.** R3 changes the code: `ContextSchema` holds `messenger: RiderMessenger` instead of
`wa_client`; the 13 tools in `rider_agent.py`, `respond_node`, and the rider sends in `delivery_hooks.py` (food ready, pickup adjusted,
pickup alerts, close threads), `wa_location.py` and `restaurant_actions.py` go through it. WhatsApp output is pinned byte-identical by
tests. R4 is the first time it happens live: offers reach Telegram riders, their dispatches get `channel = 'telegram'`, and from then
on the same agent code talks to them through the Telegram adapter. Inbound Telegram text goes rider bot router → actor → rider →
active thread → the same runner WhatsApp uses.

**State keys.** `reply_to_msg_id` and `latest_wa_msg_id` keep their names and hold `MsgRef` values (raw wamids on WhatsApp). `mark()`
and `say(reply_to=...)` ignore a reference from the other channel. WaLocation's `record_prompt_sent` takes the `MsgRef` returned by
`request_location()`.

### Simplifications that the dispatch-based thread id allows (R2, surveyed 22 Oct)

Today every runner call resolves the thread from the phone (`get_config_for_recipient` → `get_or_create_thread`), which also
**creates** a thread whenever a late hook fires after the job ended. With `thread_id = ORDELO-dispatch-<id>`:

| Call site | Today | After R2 |
|---|---|---|
| `agent_runner.run_rider_agent_w_custom_msg(recipient, …)` | DB round trip to find/create a thread by phone | `run_rider_agent(dispatch_id, …)`: config built in memory; refuses if the thread is not open (no accidental thread creation) |
| `agent_runner.init_ordelo_graph` + `_get_config_for_recipient_with_retry` | retry wrapper around phone lookup/creation | `rider_thread_open(...)` once (idempotent), config computed; the retry wrapper goes |
| `clear_wa_location_request(recipient)`, `clear_pickup_alert_cue(recipient)` | phone lookup (and `get_or_create_thread` could spawn a thread just to clear state, see `wa_location.py:328`) | take `dispatch_id`; no lookup, no spawn |
| `delivery_hooks.py` food ready (785), pickup adjusted (1590), pickup alerts (1263, 1279) | carry `rider_id`, re-resolve thread | carry the known `dispatch_id` (payloads already have it or `delivery_inflight` gives it) |
| `delivery_hooks.close_threads` | `make_threads_inactive(phone)` for every idle thread in the payload, including customer threads; goodbye always on WhatsApp | only `ORDELO-dispatch-*` rows: `rider_thread_close(thread_id)`; goodbye via `for_dispatch()` |
| `rider_agent.verify_customer_confirmation_code` (1177), `terminate_delivery_job` (1285) | `make_threads_inactive(phone)` closes every rider thread of that phone | `rider_thread_close(state.dispatch_id)`: exactly one |
| `thread_hooks.run_system_message` | reduces the given `thread_id` to a phone, then looks the thread up again | uses the given `thread_id` directly (validated: rider thread, open) |
| `on_message_wa_handler.process_wa_msg`, `on_wa_location_handler`, `wa_location.py:258` | `get_active_thread(phone)` then runner by phone | `rider_thread_active(rider_id)` returns the one open dispatch thread (D47) |
| `on_message_wa_handler.reset_thread` (`/reset`, dev) | closes every thread of the phone | closes the rider's active dispatch thread |
| `debug_state(recipient)`, `/debug-state-by-thread`, `fapp /threads` (still queries the old `from_number` column) | phone-based, creates a thread on read | by `dispatch_id` or exact `thread_id`, read-only; `/threads` fixed to `recipient` |
| `agent_runner.is_food_already_picked_up` | marked superseded | kept (still the worked example in `docs/get_latest_state_guide.md`); delete separately |

Threads already running when R2 ships keep their old `ORDELO-<uuid>` ids and close the old way; `get_active_thread` still finds both
kinds during the change-over.

**Done in R2-R4 (22 Oct):** every row above except `/reset` (it still closes every thread of the phone, which includes the
dispatch thread: kept, dev only) and `is_food_already_picked_up` (kept). Also: the inflight hook initialises the graph only when
`rider_thread_open` says `opened`, so a re-fired hook does nothing; Ready from the restaurant (`restaurant_actions._nudge_rider`)
names its dispatch; `run_system_message` answers 404 for a closed thread; `_send_delivery_instructions` lost its duplicate summary
query.

### R4 behaviour on Telegram (what a rider sees)

```
offer (job_create_dispatch -> /delivery-hooks/delivery-dispatch -> for_dispatch().offer_job)    [Accept] [Decline]
  Accept  ro1:<id>:a -> respond_to_offer: accepted   -> offer reads "👍 Accepted · X  Waiting for confirmation…"
          job_assign_dispatch picks the winner (5 s) -> inflight hook -> winner's offer "✅ The job is yours · X",
                                                       other unanswered Telegram offers "❌ Taken by another rider · X"
                                                       accepted-but-lost (notify-missed-dispatches) "❌ Taken by another rider"
          -> rider_thread_open -> the agent sends the job card [Pickup Location] [Dropoff Location] [Contact Customer]
  Decline ro1:<id>:d -> declined                      -> "Declined · X"
  late tap on a closed offer                          -> "This job is no longer available" / "Taken by another rider"
  order times out                                     -> open offers "⌛ Offer expired · X"
job card tap rj1:<id>:pk|dr|cc -> the agent with the WhatsApp words ("Send me the pickup location", ...); closed job: toast
text -> the agent (typing…, background run); /job -> current job summary; no job -> "No active job. Use /job to check, or /help."
WhatsApp message while the job is on Telegram -> "Your current job *X* is on Telegram. Please reply there." (and the reverse)
```

### Known limits until R5

- A Telegram rider cannot answer a location request yet (the agent's request arrives with a "Share current location" button,
  but the shared location is not ingested until R5, D50). The request expires as on WhatsApp when unanswered.
- Telegram riders still get the daily WhatsApp shift question (D53, R5) and have no `/off` / `/on` yet.
- Two agent turns on the same thread at the same moment are not serialised (same as WhatsApp today; `docs/to-do.md`).

## Verification (every phase; `telegram-vertification-loop` skill)

Label evidence *offline / isolated database / live Telegram*. R1 evidence so far (22 Oct, cloud copy of the repo):

| Boundary | Command | Observed | Label |
|---|---|---|---|
| SQL: onboarding RPCs, every result, concurrency, grants, dispatch gate | `pytest tests/sql/test_rider_onboarding_sql.py` | 27 passed | isolated database (Postgres 16) |
| SQL: pauses + sweep (clock decides, 2xx marking, retries, races, grants) | `pytest tests/sql/test_pauses_sql.py` | 28 passed | isolated database |
| SQL: migration on a pre-R1 table (pre-checks catch dups/NULLs/status spellings, repeatable, VERIFY) | `pytest tests/sql/test_rider_telegram_r1_migration_sql.py` | 2 passed | isolated database |
| SQL: live harness script, every stage twice, touches only fake rows | `pytest tests/sql/test_rider_onboarding_script_sql.py` | 5 passed | isolated database |
| Whole SQL suite (incl. restaurant phases) | `pytest tests/sql` | 299 passed | isolated database |
| Dispatcher: onboarding, wrong actor, relink, refused, choices, 64-byte limit | `pytest tests/channels/telegram/test_rider_router.py` | 23 passed | offline |
| Messenger adapters (WhatsApp call shapes, Telegram rendering/edits) | `pytest tests/ordelo/test_rider_messaging.py` | 29 passed | offline |
| Live `/start` with a real phone | `test_support/test_rider_onboarding.sql` STAGE 8 | existing rider linked (channel `telegram`); unknown phone asked town + vehicle, row updated | **live Telegram** (owner, 22 Oct) |

R2-R4 evidence (22 Oct, cloud copy; the R1 migration and code as committed by the owner):

| Boundary | Command | Observed | Label |
|---|---|---|---|
| SQL: rider threads (every result, one open per rider, decline-reason note, legacy threads, other agents untouched, concurrent opens, grants), channel stamp | `pytest tests/sql/test_rider_threads_sql.py` | 15 passed | isolated database |
| SQL: R2-R4 migration on the post-R1 live shape (pre-checks, repeatable, VERIFY 3/1/6/0, legacy thread closed by the next job) | `pytest tests/sql/test_rider_telegram_r2_r4_migration_sql.py` | 3 passed | isolated database |
| SQL: live harness `test_rider_telegram_jobs.sql` (no delete/insert, scoped updates, every stage twice) and the notices harness STAGE 0 thread close | `pytest tests/sql/test_rider_telegram_jobs_script_sql.py tests/sql/test_restaurant_notices_script_sql.py` | 6 + 26 passed | isolated database |
| Whole SQL suite | `pytest tests/sql` | 324 passed | isolated database |
| Rider bot jobs: offer taps (every outcome → edit), job-card taps, `/job`, text routing, wrong channel, not linked / not yours / expired, 64 bytes | `pytest tests/channels/telegram/test_rider_jobs.py` | 24 passed | offline (real Dispatcher) |
| Offer rules, WhatsApp texts unchanged, `close_open_offers` | `pytest tests/ordelo/test_dispatch_actions.py tests/watomation/test_on_callback_wa_handler.py` | 13 + 31 passed | offline |
| Agent through the messenger (WhatsApp byte-identical), runner thread rules | `pytest tests/ordelo/agents/` | 62 passed | offline |
| Messenger: job card both adapters, closed-offer texts, `for_dispatch` / `for_thread` | `pytest tests/ordelo/test_rider_messaging.py` | 41 passed | offline |
| Hooks (offer via messenger, missed/expired/taken edits, `close_threads`), WhatsApp handlers | `pytest tests/watomation/` | 206 passed | offline |
| Whole offline suite | `pytest --ignore=tests/sql` | all pass except the known baseline failure and 7 header-path checks for files absent from the cloud copy | offline |
| Live job as a rider, Telegram and WhatsApp | owner, after migration + deploy | works on both apps (owner's report, 22 Oct) | **live Telegram + WhatsApp** |

Repo baseline in that copy: the known failure `test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`; the
`tests/sql` suite had been broken since the 16 Oct reorganisation (files missing from `MIGRATION_FILES`, no pg_cron stub) and is fixed
in this change.

## Operator steps (owner; agents never apply SQL)

R1 (all ✅ done by the owner on 22 Oct):

1. ✅ Bot `@ByteloopRidersBot` and the `tgram_rider_*` AWS secrets.
2. ✅ `migrations/rider_telegram_r1.sql` steps 0–6.
3. ✅ Deploy, rider webhook, command menu.
4. ✅ Live onboarding test (existing and new rider).

R2-R4 (all ✅ done by the owner on 22 Oct):

5. ✅ Database: `ordelo_datamodels/migrations/rider_telegram_r2_r4.sql` steps 0–4 (pre-checks; the `delivery_dispatch` ALTERs; the
   whole `dispatch/delivery_dispatch.sql`; the whole `agent_threads/rider_threads.sql`; VERIFY shows 3 / 1 / 6 / 0). Apply BEFORE
   deploying: the new code calls `rider_thread_open` at the first assignment. Then `python scripts/datamodels/drift_check.py`.
6. ✅ Deploy the R2-R4 code.
7. ✅ Re-publish the rider bot command menu (it now has `/job`): `notebooks/telegram/tgram_setup_bot.py` with `BOT_KEY = 'rider'`.
   The webhook needs no change (`message`, `callback_query`).
8. ✅ Live test (owner tested as a rider on Telegram and WhatsApp). For later checks: your rider row must be `status = 'active'`, town `dummy`, in `overwatch_list`, linked on Telegram. Run
   `test_support/test_rider_telegram_jobs.sql` STAGE 0 and 0b, then `test_restaurant_notices.sql` STAGE 0–2b, then
   `test_rider_telegram_jobs.sql` STAGE 1–8. Then a WhatsApp pass (a WhatsApp rider, or switch yourself back with STAGE 9) to
   confirm WhatsApp offers, the job card and the agent replies are unchanged.

## Known limits and risks

- `rider_master` has RLS off and anon grants, so `tuid`/`tcid` are readable by anon (existing security review item, `docs/to-do.md`).
- Status gate: any live rider whose status is not exactly `'active'` stops getting offers after step 5 of the migration (pre-check 3).
- `channel = 'telegram'` is set at link time (R1) and moves the rider's next offers to Telegram (live since R4).
- A rider whose row is re-created by Telegram sign-up starts `inactive` (D41): set `status = 'active'` before expecting offers.
- Relinking does not notify the old Telegram chat.
- The town list is whatever distinct values exist; a new town needs one operator row first.
- Ops alerts go through the existing WhatsApp `WALogger` (overwatch numbers).
