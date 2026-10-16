# Gate 1 review: ordelo_datamodels organisation

Research for [the plan](ordelo-database-organisation-plan.md), phase 1. Read-only snapshot of the live Supabase database taken 16 Oct 2026, ~13:55 BST (Postgres 15.8), compared with every SQL file in `ordelo_datamodels/`, every Python module in OrdeloAgent, restaurant-frontend's Supabase calls and restaurant-agents' SQL and Python. **No repo SQL or database object has been changed.** Everything below is for your approval before Phase 2 starts.

## Gate 1 outcome (owner, 16 Oct 2026 17:16)

Approved. D1: orphan candidates go to `_orphans/<area>.sql`. D2: cron jobs are runnable `cron.schedule` statements (plus `cron.alter_job … active := false` for inactive jobs). D3: triggers live with the table they fire on. D4: `create_t_order_alerts.sql` is split into `t_order_alerts.sql`, `t_sent_messages.sql` and `t_housekeeping.sql`. D5 / section B: recorded as to-dos in [`docs/to-do.md`](../docs/to-do.md), not fixed in this branch.

## A. What is in the database

| | Live | Defined in OrdeloAgent today | After the change |
|---|---|---|---|
| Tables (public) | 68 | 41 (2 of them not live) | 45 OrdeloAgent-owned files, rest referenced |
| Views | 5 (+2 PostGIS) | 3 | 5 |
| Functions | 110 | 96 distinct (1 not live) | every live function has exactly one home |
| Triggers | 11 | 13 (4 not live) | 11 |
| pg_cron jobs | 16 (12 active) | 0 (only in comments) | 16, each in its job's file |

Ownership of the 192 live public objects:

- **146 owned by OrdeloAgent** → 75 files in 14 capability folders (section F).
- **14 owned by restaurant-agents** (`food_order`, `order_item`, `thread` and its 5 RPCs in two overloads each, `reservation`, `get_next_daily_seq`, legacy `foodorder`/`orderitem`) → referenced, not copied.
- **9 library-managed** (LangGraph checkpoints, langchain PGVector, PostGIS) → listed only.
- **24 orphan candidates**: live, but nothing calls them (no code, trigger, cron, other function, view, frontend or restaurant-agents reference). Nothing is dropped.

Function drift is small: 90 of 98 repo function copies match live exactly. The real gaps are tables with ALTER-added columns, missing cron definitions, and objects that only exist live.

## B. Findings that need your attention (not fixed by this work)

These came out of the research. The organisation work will document them, not change them. Each is a candidate follow-up.

1. **`job_payment_init_reconciler` is not scheduled.** `migrations/ordelo_agg_r1.sql` says to schedule it every 2 minutes; `cron.job` has no such job. Payment-init reconciliation is not running.
2. **`t_housekeeping` is not scheduled.** Telegram inbox/ledger retention (`tgram_inbox_retention_days`, `tgram_ledger_retention_days`) never runs. Tables are small today (≤ 100 rows).
3. **`t_invites_normalize_phone` trigger is missing live.** The function exists, the trigger does not, so `t_invites.phone_number` is not normalised to digits on insert.
4. **`job_restaurant_confirmation_timeout` is not scheduled**, although `docs/delivery_process.md` and `.specify/design/*` describe it. The 10-second `process_restaurant_confirmation` job appears to have replaced it. It will be documented as "not scheduled".
5. **Migration `add_stale_thread_dispatch_index.sql` was never applied** (`idx_thread_active_rest_ref_last_access` is missing), and neither were the two `rider_location` indexes in `location.sql`. Low impact at current volumes.
6. **Row-level security is off on most tables**, including `rider_master`, `restaurant_master`, `customer_master`, `delivery_*` and `takeaway_summary`. The frontend reads several of them with the publishable (anon) key. Only `t_*`, `web_*`, `wa_location_*` and `order_access_grant` have RLS. This is worth a separate security review.
7. **The docs disagree with live.** `docs/delivery_process.md` names cron jobs that don't exist (`manage_delivery_detail`, `create_dispatch_for_unassigned_orders`, `assign_delivery_for_accepted_jobs`). The `init_delivery` header says it eagerly calls `process_delivery`, but live `init_delivery` doesn't: dispatch preparation is the 5-second `process_delivery` job. These are corrected in Phase 5.
8. **Some Python is dead.** `ordelo/agent_app_handlers.py::process_dispatch_response_from_rider_sync` (the only caller of `dispatch_accept_func`) is never called. `misc_sql/drop_dispatch_accept_func.sql` was never run. Several modules still query the legacy `foodorder`/`orderitem` tables, which have never received a row.

## C. How objects are placed (rules applied in section F)

- A **table file** holds the table's DDL (regenerated from live), indexes, RLS/policies and grants, and **every trigger that fires on that table together with its trigger function**. Columns that another feature added carry `-- used by <file>`.
- **Entry-point or workflow functions** that span tables (`init_delivery`, `restaurant_order_ready` …) get their own file in the folder of the flow they start, or stay in their existing workflow file (`restaurant_admin/`).
- **Each pg_cron job** goes in the file of the function it runs, with its live schedule.
- **Small shared helpers** go with the thing they read: `parse_alert_offsets` reads `ordelo_config` offsets for two jobs, so it lives in `core/ordelo_config.sql`.
- **Restaurant confirmation** (`process_restaurant_confirmation`, `resolve_initial_restaurant_acceptance`, the timeout job, `enquire_admin_availability`) is grouped in `restaurant_admin/`. It covers both delivery and takeaway.
- **New folder `byteloop_agent/`** holds `businesses` and the `documents` RAG table and functions used by `ordelo/agents/byteloop_agent.py` and `config/pg_setting.py`.

## D. Questions for this gate

1. **Orphans folder.** The plan said orphan candidates keep a flagged file in their capability folder. I now recommend a separate `_orphans/<area>.sql` (6 files), so the capability folders contain only live, used logic, and the orphans tab of the guide reads from one place. Agree?
2. **Cron statements.** Should each job file contain a runnable `SELECT cron.schedule('<job>', '<schedule>', $$…$$);`, plus `SELECT cron.alter_job(jobid, active := false) FROM cron.job WHERE jobname = '…';` for inactive jobs? That makes the file the full truth and re-running it changes nothing. Or should they stay commented as "operator SQL"? I recommend runnable.
3. **Triggers with the table they fire on.** This puts `rider_pickup_alert_reschedule` (which writes `rider_pickup_alert`) in `delivery/delivery_summary.sql`, cross-linked from `dispatch/rider_pickup_alert.sql`. Agree?
4. **Telegram split.** `create_t_order_alerts.sql` becomes `t_order_alerts.sql` (table, job and card functions), `t_sent_messages.sql` (ledger table and mark/sent RPCs) and `t_housekeeping.sql`. Agree?
5. **Section B findings.** Are they recorded as follow-ups only (my recommendation), or do you want any of them fixed in this branch?

## E. File-by-file move map

Every current file under `ordelo_datamodels/` (80 SQL + 2 stray JSON). Moves use `git mv` so history follows; splits keep history on the largest piece.

| Current file | Destination | Note |
|---|---|---|
| `auth_sessions.sql` | `admin_dashboard/auth_sessions.sql` | move |
| `dashboard_sessions.sql` | `_archive/dashboard_sessions.sql` | table not live |
| `db_config.sql` | `_archive/db_config.sql` | app_config not live; its job_create_dispatch copy is stale (16% similar) |
| `debug_log.sql` | `core/debug_log.sql` | move |
| `delivery_models.sql` | `delivery/delivery_pricing_detail.sql` | rename; DDL regenerated from live (2 live-only, 5 repo-only columns) |
| `delivery_option.sql` | `delivery/delivery_option.sql` | move; drop repo-only dt/dtts (not live) |
| `detail.sql` | `delivery/delivery_detail.sql` | rename |
| `dispatch.sql` | `dispatch/delivery_dispatch.sql` | rename |
| `dispatch_bulk.sql` | `_archive/dispatch_bulk.sql` | trigger not live; function body differs from live |
| `elas_stats.sql` | `_archive/queries/elas_stats.sql` | ad-hoc analytics queries, no objects |
| `fly_config.sql` | `platform/fly_post.sql` | merged with fly_post (its only reader) |
| `get_latest_state.sql` | `agent_threads/get_latest_state.sql` | move |
| `inflight.sql` | `dispatch/delivery_inflight.sql + dispatch/notify_missed_dispatches.sql` | split |
| `location.sql` | `rider_location/rider_location.sql + rider_location/rider_location_event.sql` | split; 2 repo indexes not live |
| `masterdata.sql` | `core/rider_master.sql + core/restaurant_master.sql + core/customer_master.sql` | split; restaurant_master gains 2 live-only columns |
| `menu.sql` | `core/menus.sql` | plus 6 live per-restaurant menu tables captured |
| `ordelo_config.sql` | `core/ordelo_config.sql` | its trigger/fn (trg_app_config_updated) is not live -> dropped from file, kept in _archive |
| `order_notification_customer_event_outbox.sql` | `notifications/{order_notification_subscription,order_customer_event,notification_outbox}.sql` | split |
| `payment_event.sql` | `payment/payment_event.sql` | + record_payment_authorised |
| `sbase_queues_from_order.sql` | `_archive/sbase_queues_from_order.sql` | marked deprecated in file |
| `summary.sql` | `delivery/delivery_summary.sql` | + kitchen columns from restaurant_admin, admin indexes, rider_pickup_alert_reschedule trigger; repo-only column rest_confirmed_at is not live |
| `takeaway_summary.sql` | `takeaway/takeaway_summary.sql` | move |
| `wa_location.sql` | `rider_location/wa_location.sql` | move |
| `waba_es.sql` | `core/waba_es.sql` | move |
| `jobs_n_functions/_tbd_handle_restaurant_confirmation.sql` | `_archive/` | live copy differs; live body captured in _orphans/restaurant_admin.sql |
| `jobs_n_functions/archive_process_delivery.sql` | `_archive/` | superseded by process_delivery.sql (live match) |
| `jobs_n_functions/cleanupDeliveryOrder.sql` | `test_support/cleanup_delivery_order.sql` | used by the /reset WhatsApp utility command |
| `jobs_n_functions/create_food_order_with_items.sql` | `ordering/create_food_order_with_items.sql` | move (4 identical copies in migrations stay frozen) |
| `jobs_n_functions/dispatch_cancel_before_pickup.sql` | `dispatch/dispatch_cancel_before_pickup.sql` | move |
| `jobs_n_functions/dispatch_complete_func.sql` | `dispatch/dispatch_complete_func.sql` | move |
| `jobs_n_functions/enquire_admin_availability.sql` | `restaurant_admin/enquire_admin_availability.sql` | + cron |
| `jobs_n_functions/enquire_shift_availability.sql` | `dispatch/enquire_shift_availability.sql` | + cron |
| `jobs_n_functions/fly_post.sql` | `platform/fly_post.sql` | move |
| `jobs_n_functions/get_rider_payout_report.sql` | `admin_dashboard/get_rider_payout_report.sql` | called by sys-admin router |
| `jobs_n_functions/init_delivery.sql` | `delivery/init_delivery.sql` | move; fix header claim that it calls process_delivery |
| `jobs_n_functions/init_delivery_detail_tbd.sql` | `_archive/` | live but unused -> captured in _orphans/delivery.sql |
| `jobs_n_functions/init_takeaway.sql` | `takeaway/init_takeaway.sql` | move |
| `jobs_n_functions/insert_delivery_detail.sql` | `_orphans/delivery.sql` | only called by orphan functions |
| `jobs_n_functions/job_assign_dispatch.sql` | `dispatch/job_assign_dispatch.sql` | + cron |
| `jobs_n_functions/job_awsrunner_switch.sql` | `platform/job_awsrunner_switch.sql` | + 2 inactive crons |
| `jobs_n_functions/job_close_thread.sql` | `agent_threads/job_close_thread.sql` | body replaced with live (r3 copy matches live) |
| `jobs_n_functions/job_create_dispatch.sql` | `dispatch/job_create_dispatch.sql` | + cron; its order_has_test_item copy removed (lives in ordering/) |
| `jobs_n_functions/job_null_or_outdated_location.sql` | `rider_location/job_null_or_outdated_location.sql` | body replaced with live (92% similar); cron inactive |
| `jobs_n_functions/job_payment_init_reconciler.sql` | `payment/job_payment_init_reconciler.sql` | move |
| `jobs_n_functions/job_process_owntracks.sql` | `rider_location/job_process_owntracks.sql` | + cron |
| `jobs_n_functions/job_restaurant_confirmation_timeout.sql` | `restaurant_admin/job_restaurant_confirmation_timeout.sql` | body replaced with live (96%); NOT scheduled live |
| `jobs_n_functions/job_rider_pickup_alerts.sql` | `dispatch/rider_pickup_alert.sql + dispatch/job_rider_pickup_alerts.sql` | split table/job; parse_alert_offsets -> core/ordelo_config.sql |
| `jobs_n_functions/job_terminate_stale_active_threads.sql` | `agent_threads/job_terminate_stale_active_threads.sql` | + old inactive variant captured from live |
| `jobs_n_functions/notify_missed_dispatches_tbd.sql` | `_archive/` | stale copy; for_order variant -> _orphans/dispatch.sql |
| `jobs_n_functions/ordelo_post.sql` | `platform/ordelo_post.sql` | no live caller found (listed in orphans tab, file kept) |
| `jobs_n_functions/order_has_test_item.sql` | `ordering/order_has_test_item.sql` | move |
| `jobs_n_functions/process_delivery.sql` | `delivery/process_delivery.sql` | + cron |
| `jobs_n_functions/process_restaurant_confirmation.sql` | `restaurant_admin/process_restaurant_confirmation.sql` | + cron (writes delivery and takeaway summaries) |
| `jobs_n_functions/record_payment_authorised.sql` | `payment/payment_event.sql` | merged with its table |
| `jobs_n_functions/resolve_initial_restaurant_acceptance.sql` | `restaurant_admin/resolve_initial_restaurant_acceptance.sql` | shared by init_delivery and init_takeaway |
| `jobs_n_functions/test_reset_order_and_dispatch.sql` | `test_support/` | move |
| `jobs_n_functions/test_reset_takeaway_order.sql` | `test_support/` | move |
| `jobs_n_functions/result_export.json` | `_archive/` | stray export |
| `migrations/*.sql (12 files)` | `migrations/ (frozen)` | definitions extracted; header "Current definitions now live in: …" added |
| `misc_sql/drop_dispatch_accept_func.sql` | `_archive/` | never run: dispatch_accept_func is still live |
| `misc_sql/get_ddl_for_table.sql` | `test_support/get_ddl_for_table.sql` | operator helper |
| `misc_sql/result_export.json` | `_archive/` | stray export |
| `misc_sql/test_create_t_order_alerts.sql` | `test_support/` | move |
| `misc_sql/test_magic_link.sql` | `test_support/` | move |
| `misc_sql/test_restaurant_notices.sql` | `test_support/` | move (referenced by CLAUDE.md + live-order harness doc) |
| `misc_sql/testing_scripts.sql` | `test_support/clear_dispatch.sql` | rename; used by /reset command |
| `restaurant_admin/restaurant_order_decision.sql` | `restaurant_admin/restaurant_order_decision.sql` | stays; ALTERs on delivery/takeaway summaries move to table files |
| `restaurant_admin/restaurant_ready_adjust_notices.sql` | `restaurant_admin/restaurant_ready_adjust_notices.sql` | stays; 6 delivery_summary columns + t_sent_messages index move to table files |
| `telegram/create_t_inbox.sql` | `telegram/t_inbox.sql` | rename |
| `telegram/create_t_invites.sql` | `telegram/t_invites.sql` | rename; phone-normalise trigger is NOT live |
| `telegram/create_t_order_alerts.sql` | `telegram/t_order_alerts.sql + telegram/t_sent_messages.sql + telegram/t_housekeeping.sql` | split by owner table; t_housekeeping not scheduled live |

## F. Target files and what each one defines


**admin_dashboard/**

| File | Objects (live) | Cron |
|---|---|---|
| `auth_sessions.sql` | table `auth_sessions` | – |
| `get_rider_payout_report.sql` | fn `get_rider_payout_report` | – |
| `v_admin_orders.sql` | view `v_admin_order_items`, view `v_admin_orders`, view `v_admin_orders_daily`, view `v_admin_orders_monthly` | – |

**agent_threads/**

| File | Objects (live) | Cron |
|---|---|---|
| `get_latest_state.sql` | fn `get_latest_state`, fn `get_latest_state_by_thread` | – |
| `job_close_thread.sql` | fn `job_close_thread` | – |
| `job_terminate_stale_active_threads.sql` | fn `job_terminate_stale_active_threads`, fn `job_terminate_stale_active_threads_new` | `jobTerminateStaleActiveThreadsNew` * * * * *; `job_terminate_stale_active_threads` */3 * * * * (inactive) |

**byteloop_agent/**

| File | Objects (live) | Cron |
|---|---|---|
| `businesses.sql` | table `businesses` | – |
| `documents.sql` | table `documents`, fn `match_documents`, fn `search_documents` | – |

**core/**

| File | Objects (live) | Cron |
|---|---|---|
| `cust_rest_map.sql` | table `cust_rest_map` | – |
| `customer_master.sql` | table `customer_master` | – |
| `debug_log.sql` | table `debug_log` | – |
| `menus.sql` | table `bnat_menu`, table `chks_menu`, table `crms_menu`, table `elas_menu`, table `sfcs_menu`, table `strk_menu`, table `vavi_menu` | – |
| `ordelo_config.sql` | table `ordelo_config`, fn `parse_alert_offsets` | – |
| `restaurant_master.sql` | table `restaurant_master` | – |
| `rider_master.sql` | table `rider_master` | – |
| `rider_registrations.sql` | table `rider_registrations` | – |
| `waba_es.sql` | table `waba_es` | – |

**delivery/**

| File | Objects (live) | Cron |
|---|---|---|
| `delivery_detail.sql` | table `delivery_detail` | – |
| `delivery_option.sql` | table `delivery_option` | – |
| `delivery_pricing_detail.sql` | table `delivery_pricing_detail` | – |
| `delivery_summary.sql` | table `delivery_summary`, fn `delivery_summary_timedout_whook`, fn `restaurant_updates_whook`, fn `rider_pickup_alert_reschedule`, trg `trigger_delivery_summary_timedout`, trg `trigger_pickup_time_reschedule`, trg `trigger_restaurant_updates` | – |
| `init_delivery.sql` | fn `init_delivery` | – |
| `process_delivery.sql` | fn `process_delivery` | `process_delivery` 5 seconds |

**dispatch/**

| File | Objects (live) | Cron |
|---|---|---|
| `delivery_dispatch.sql` | table `delivery_dispatch`, fn `delivery_dispatch_whook_statement`, trg `trigger_delivery_dispatch_whook` | – |
| `delivery_inflight.sql` | table `delivery_inflight`, fn `delivery_inflight_whook`, trg `trigger_delivery_inflight_whook` | – |
| `dispatch_cancel_before_pickup.sql` | fn `dispatch_cancel_before_pickup` | – |
| `dispatch_complete_func.sql` | fn `dispatch_complete_func` | – |
| `enquire_shift_availability.sql` | fn `enquire_shift_availability` | `enquire_shift_availability` 0 11 * * * |
| `job_assign_dispatch.sql` | fn `assign_accepted_dispatch`, fn `job_assign_dispatch` | `job_assign_dispatch` 5 seconds |
| `job_create_dispatch.sql` | fn `get_available_riders`, fn `job_create_dispatch` | `job_create_dispatch` 5 seconds |
| `job_rider_pickup_alerts.sql` | fn `job_rider_pickup_alerts` | `job_rider_pickup_alert` */5 * * * * |
| `notify_missed_dispatches.sql` | fn `notify_missed_dispatches` | – |
| `rider_pickup_alert.sql` | table `rider_pickup_alert` | – |

**notifications/**

| File | Objects (live) | Cron |
|---|---|---|
| `notification_outbox.sql` | table `notification_outbox` | – |
| `order_customer_event.sql` | table `order_customer_event` | – |
| `order_notification_subscription.sql` | table `order_notification_subscription` | – |

**ordering/**

| File | Objects (live) | Cron |
|---|---|---|
| `create_food_order_with_items.sql` | fn `create_food_order_with_items` | – |
| `food_order_ordelo_columns.sql` | table `food_order@ordelo_columns`, trg `food_order_origin_immutable`, fn `forbid_food_order_origin_change` | – |
| `order_access_grant.sql` | table `order_access_grant` | – |
| `order_has_test_item.sql` | fn `order_has_test_item` | – |
| `web_monitor_run.sql` | table `web_monitor_run` | – |
| `web_order_request.sql` | table `web_order_request` | – |
| `web_payment_release.sql` | table `web_payment_release` | – |
| `web_rate_limit.sql` | table `web_rate_limit` | – |
| `web_session_meta.sql` | table `web_session_meta` | – |

**payment/**

| File | Objects (live) | Cron |
|---|---|---|
| `job_payment_init_reconciler.sql` | fn `job_payment_init_reconciler` | – |
| `payment_event.sql` | table `payment_event`, fn `record_payment_authorised` | – |

**platform/**

| File | Objects (live) | Cron |
|---|---|---|
| `app_url.sql` | table `app_url` | – |
| `cron_housekeeping.sql` | cols `cron:delete-job-run-details` | `delete-job-run-details` 0 12 * * * |
| `fly_post.sql` | table `fly_config`, fn `fly_post` | – |
| `job_awsrunner_switch.sql` | fn `job_awsrunner_switch` | `job_aws_runner_switch_pause` 0 23 * * * (inactive); `job_awsrunner_switch_resume` 0 6 * * * (inactive) |
| `ordelo_post.sql` | fn `ordelo_post` | – |

**restaurant_admin/**

| File | Objects (live) | Cron |
|---|---|---|
| `enquire_admin_availability.sql` | fn `enquire_admin_availability` | `enquire_admin_availability` 0 11 * * * |
| `job_restaurant_confirmation_timeout.sql` | fn `job_restaurant_confirmation_timeout` | – |
| `process_restaurant_confirmation.sql` | fn `process_restaurant_confirmation` | `process_restaurant_confirmation` 10 seconds |
| `resolve_initial_restaurant_acceptance.sql` | fn `resolve_initial_restaurant_acceptance` | – |
| `restaurant_order_decision.sql` | fn `restaurant_admin_label`, fn `restaurant_order_decide`, fn `restaurant_order_set_pickup`, fn `t_order_admin_phone`, fn `t_order_decide`, fn `t_order_set_pickup` | – |
| `restaurant_ready_adjust_notices.sql` | fn `job_t_receipt_refresh`, fn `restaurant_order_adjust_pickup`, fn `restaurant_order_ready`, fn `t_notice_sent`, fn `t_notice_targets`, fn `t_order_adjust_pickup`, fn `t_order_ready`, fn `t_receipt_sent`, fn `t_receipt_snapshot`, fn `t_receipt_status`, fn `t_receipts_stale`, fn `t_receipts_take` | `job_t_receipt_refresh` 5 seconds |

**rider_location/**

| File | Objects (live) | Cron |
|---|---|---|
| `job_null_or_outdated_location.sql` | fn `job_null_or_outdated_location` | `job_null_or_outdated_location` * * * * * (inactive) |
| `job_process_owntracks.sql` | fn `job_process_owntracks` | `job_process_owntracks` 30 seconds |
| `live_track.sql` | table `live-track` | – |
| `rider_location.sql` | table `rider_location` | – |
| `rider_location_event.sql` | table `rider_location_event`, fn `rider_location_event_update`, trg `trigger_rider_location_event_update` | – |
| `wa_location.sql` | table `wa_location_observation`, table `wa_location_request` | – |

**takeaway/**

| File | Objects (live) | Cron |
|---|---|---|
| `init_takeaway.sql` | fn `init_takeaway` | – |
| `takeaway_summary.sql` | fn `takeaway_pickup_time_whook`, fn `takeaway_restaurant_updates_whook`, table `takeaway_summary`, trg `trigger_takeaway_pickup_time_insert`, trg `trigger_takeaway_pickup_time_set`, trg `trigger_takeaway_restaurant_updates` | – |

**telegram/**

| File | Objects (live) | Cron |
|---|---|---|
| `t_housekeeping.sql` | fn `t_housekeeping` | – |
| `t_inbox.sql` | table `t_inbox`, fn `t_inbox_claim`, fn `t_inbox_finish` | – |
| `t_invites.sql` | fn `t_claim_invite`, fn `t_invite_preview`, table `t_invites`, fn `t_invites_normalize_phone`, view `t_invites_shareable`, fn `t_linked_restaurants`, fn `t_new_invite_code` | – |
| `t_order_alerts.sql` | fn `job_t_order_alerts`, table `t_order_alerts`, fn `t_order_card_destinations`, fn `t_order_card_row`, fn `t_order_card_snapshot`, fn `t_order_card_status`, fn `t_order_cards_stale`, fn `t_order_cards_take` | `job_t_order_alerts` 5 seconds |
| `t_sent_messages.sql` | fn `t_order_card_mark`, fn `t_order_card_sent`, table `t_sent_messages` | – |

**test_support/**

| File | Objects (live) | Cron |
|---|---|---|
| `cleanup_delivery_order.sql` | fn `cleanup_delivery_order` | – |
| `clear_dispatch.sql` | fn `clear_dispatch` | – |
| `test_reset_order_and_dispatch.sql` | fn `test_reset_order_and_dispatch` | – |
| `test_reset_takeaway_order.sql` | fn `test_reset_takeaway_order` | – |

**_orphans/** (proposed, see question D1): live objects with no caller found anywhere (code, other SQL, triggers, cron, frontend, restaurant-agents). Captured from live, one file per area, nothing dropped.

| Object | Kind | Area file |
|---|---|---|
| `overwatch_view` | fn | `_orphans/admin_dashboard.sql` |
| `elaivec` | table | `_orphans/byteloop_agent.sql` |
| `elas_menu_before_march` | table | `_orphans/core.sql` |
| `delivery_detail_bkp` | table | `_orphans/delivery.sql` |
| `delivery_detail_update_whook` | fn | `_orphans/delivery.sql` |
| `init_delivery_detail` | fn | `_orphans/delivery.sql` |
| `insert_delivery_detail` | fn | `_orphans/delivery.sql` |
| `manage_delivery_detail` | fn | `_orphans/delivery.sql` |
| `restaurant_confirmation_whook` | fn | `_orphans/delivery.sql` |
| `complete_dispatch` | fn | `_orphans/dispatch.sql` |
| `delivery_dispatch_whook` | fn | `_orphans/dispatch.sql` |
| `dispatch_accept_func` | fn | `_orphans/dispatch.sql` |
| `fake_delivery_dispatch_whook` | fn | `_orphans/dispatch.sql` |
| `handle_delivery_dispatch_changes` | fn | `_orphans/dispatch.sql` |
| `job_assign_delivery` | fn | `_orphans/dispatch.sql` |
| `notify_missed_dispatches_for_order` | fn | `_orphans/dispatch.sql` |
| `sync_delivery_inflight` | fn | `_orphans/dispatch.sql` |
| `order_item_v2` | table | `_orphans/ordering.sql` |
| `payment_details` | table | `_orphans/payment.sql` |
| `notify_http_endpoint` | fn | `_orphans/platform.sql` |
| `rec` | table | `_orphans/platform.sql` |
| `sbase_test_realtime` | table | `_orphans/platform.sql` |
| `trigger_notify_http` | trg | `_orphans/platform.sql` |
| `handle_restaurant_confirmation` | fn | `_orphans/restaurant_admin.sql` |
| `driver_location_event` | table | `_orphans/rider_location.sql` |

**Referenced, not copied**

| Object | Owner / defined in |
|---|---|
| `food_order` | restaurant-agents …/order_management/food_order.sql |
| `order_item` | restaurant-agents …/order_management/food_order.sql |
| `daily_seq_last_value` | restaurant-agents …/order_management/food_order.sql |
| `get_next_daily_seq` | restaurant-agents …/order_management/food_order.sql |
| `thread` | restaurant-agents …/thread_management/thread_mgmnt_ddl.sql |
| `create_thread` | (same) |
| `get_active_thread` | (same) |
| `get_or_create_thread` | (same) |
| `get_stale_active_threads` | (same) |
| `make_threads_inactive` | (same) |
| `retain_thread` | (same) |
| `reservation` | restaurant-agents …/reservation_management/reservation_ddl.sql |
| `foodorder` | restaurant-agents …/ordelo_service/datamodels/food_order.sql (legacy) |
| `orderitem` | (same, legacy) |
| `checkpoints` | library: LangGraph PostgresSaver |
| `checkpoint_blobs` | library: LangGraph |
| `checkpoint_writes` | library: LangGraph |
| `checkpoint_migrations` | library: LangGraph |
| `langchain_pg_collection` | library: langchain PGVector |
| `langchain_pg_embedding` | library: langchain PGVector |
| `spatial_ref_sys` | library: PostGIS |
| `geometry_columns` | library: PostGIS |
| `geography_columns` | library: PostGIS |
| schema `pgmq` (`q_owntracks`, `a_owntracks`) | pgmq extension; queue read by `job_process_owntracks` |
| schema `elas` (checkpoint tables, `temp_table`) | LangGraph checkpoints for the ELAS restaurant agent (restaurant-agents) |

## G. Drift report (repo vs live, 16 Oct 2026)

Functions are compared on their body with comments, case, quoting and whitespace removed. Tables are compared on column names (types and constraints are regenerated from live in Phase 3 anyway).

**Function copies that differ from live** (live wins; the losing copy goes to `_archive/`):

| Function | Repo copy | Result |
|---|---|---|
| `delivery_dispatch_whook_statement` | `dispatch_bulk.sql` | DIFFERS (76% similar) |
| `expire_wa_location_requests_on_inflight_delete` | `migrations/create_wa_location_tables.sql` | NOT LIVE |
| `handle_restaurant_confirmation` | `jobs_n_functions/_tbd_handle_restaurant_confirmation.sql` | DIFFERS (91% similar) |
| `job_close_thread` | `jobs_n_functions/job_close_thread.sql` | DIFFERS (98% similar) |
| `job_create_dispatch` | `db_config.sql` | DIFFERS (16% similar) |
| `job_null_or_outdated_location` | `jobs_n_functions/job_null_or_outdated_location.sql` | DIFFERS (92% similar) |
| `job_restaurant_confirmation_timeout` | `jobs_n_functions/job_restaurant_confirmation_timeout.sql` | DIFFERS (96% similar) |
| `notify_missed_dispatches` | `jobs_n_functions/notify_missed_dispatches_tbd.sql` | DIFFERS (82% similar) |
| `process_delivery` | `jobs_n_functions/archive_process_delivery.sql` | DIFFERS (90% similar) |
| `restaurant_confirmation_whook` | `migrations/add_restaurant_confirmation_fields.sql` | DIFFERS (21% similar) |

All other repo function copies (90) match live exactly, including the 5 copies of `create_food_order_with_items` and the 3 of `order_has_test_item`.

**Tables**

| Table | Live-only columns | Repo-only columns |
|---|---|---|
| `app_config` | table not live | – |
| `dashboard_sessions` | table not live | – |
| `delivery_option` | – | dt, dtts |
| `delivery_pricing_detail` | message, minimum_order_value | byteloop_cost, ddts, driver_payout, dt, rest_cost |
| `delivery_summary` | – | rest_confirmed_at |
| `food_order` | action, commission_rate, delivery_fee, final_order_value, notes, order_dt, order_dtts, order_id, order_number, payment_status, recipient, rest_cost, seq_id, service_charge, small_order_fee, thread_id, total_price | – |
| `restaurant_master` | collection_commission, service_hours_json | – |
| `web_session_meta` | postcode | – |

`food_order` is owned by restaurant-agents; OrdeloAgent only adds columns (origin_channel, storefront, payment_mode …), which go to `ordering/food_order_ordelo_columns.sql`.

**Triggers, indexes, cron**

- Triggers in repo, not live: `expire_wa_location_requests_on_inflight_delete`, `t_invites_normalize_phone`, `trigger_delivery_dispatch_whook_bulk`, `trigger_restaurant_confirmation_request`.
- Triggers live, not in repo: `trigger_notify_http` (orphan, on `sbase_test_realtime`).
- Indexes in repo, not live: `dashboard_sessions_cookie_hash_idx`, `dashboard_sessions_rest_ref_idx`, `dashboard_sessions_token_hash_idx`, `dashboard_sessions_wa_number_idx`, `idx_rider_location_dtts_desc`, `idx_rider_location_tst_desc`, `idx_thread_active_rest_ref_last_access`.
- Indexes live, not in repo: `checkpoint_blobs_thread_id_idx`, `checkpoint_writes_thread_id_idx`, `checkpoints_thread_id_idx`, `delivery_detail_pkey1`, `idx_live_track_created_at`, `idx_live_track_device`, `idx_live_track_user`, `idx_thread_agent_thread_id`, `ix_cmetadata_gin`, `ix_langchain_pg_embedding_id`, `notification_outbox_uq`, `order_customer_event_key_uq`, `payment_event_provider_event_id_uq`.
- Cron: **none of the 16 live jobs is defined in the repo** (some are in comments). Live jobs:

| Job | Schedule | Active | Runs | Command |
|---|---|---|---|---|
| `delete-job-run-details` | `0 12 * * *` | yes | 2 | `DELETE FROM cron.job_run_details WHERE end_time < now() - interval '1 ` |
| `enquire_admin_availability` | `0 11 * * *` | yes | 1 | `select enquire_admin_availability(ARRAY['ELAS', 'SFCS', 'BNAT']);` |
| `enquire_shift_availability` | `0 11 * * *` | yes | 1 | `SELECT public.enquire_shift_availability()` |
| `job_assign_dispatch` | `5 seconds` | yes | 17868 | `SELECT public.job_assign_dispatch()` |
| `job_aws_runner_switch_pause` | `0 23 * * *` | no | – | `SELECT job_awsrunner_switch('pause');` |
| `job_awsrunner_switch_resume` | `0 6 * * *` | no | – | `SELECT job_awsrunner_switch('resume');` |
| `job_create_dispatch` | `5 seconds` | yes | 17868 | `SELECT public.job_create_dispatch()` |
| `job_null_or_outdated_location` | `* * * * *` | no | – | `SELECT public.job_null_or_outdated_location()` |
| `job_process_owntracks` | `30 seconds` | yes | 2987 | `SELECT public.job_process_owntracks()` |
| `job_rider_pickup_alert` | `*/5 * * * *` | yes | 299 | `select job_rider_pickup_alerts();` |
| `job_terminate_stale_active_threads` | `*/3 * * * *` | no | – | `SELECT public.job_terminate_stale_active_threads()` |
| `jobTerminateStaleActiveThreadsNew` | `* * * * *` | yes | 1494 | `SELECT job_terminate_stale_active_threads_new();` |
| `job_t_order_alerts` | `5 seconds` | yes | 14096 | `SELECT public.job_t_order_alerts()` |
| `job_t_receipt_refresh` | `5 seconds` | yes | 10209 | `SELECT public.job_t_receipt_refresh()` |
| `process_delivery` | `5 seconds` | yes | 17868 | `SELECT public.process_delivery()` |
| `process_restaurant_confirmation` | `10 seconds` | yes | 8949 | `SELECT public.process_restaurant_confirmation()` |