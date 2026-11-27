# ADR 0019: Scheduled work is owned by pg_cron

## Status

Accepted 27 Nov 2026 (owner decision in the scheduling design session). Built on branch `feature/pgcron-schedules` (phases 1 and 2: four jobs, no `lifespan` loop left); the job SQL is not applied to live yet. The plan is [`plans/telegram-rider-invite-alert-schedule.md`](../../plans/telegram-rider-invite-alert-schedule.md), and the rule for contributors is in `agents.md` ("Add scheduled or retried work").

## Context

About 15 jobs already run as pg_cron → SQL `job_*()` → `http_post` to `{ORDELO_APP_URL}/<area>-hooks/<name>` → a thin FastAPI route using `BackgroundTasks`. Examples are rider offer reminders, pickup alerts, Telegram order cards, the pause sweep and the location checks. Two exceptions run as `asyncio` loops started in the FastAPI `lifespan`:

- `customer_notifier.run_sweeper`, every 60 s. It covers customer outbox recovery, the web-order lifecycle (including the release of held payments) and the daily price audit.
- The new rider invite alert worker, every 10 s.

Those loops caused four problems:

- **Duplicate loops.** Gunicorn runs up to 3 workers, so each loop ran up to 3 times.
- **Laptops doing production work.** A local server pointed at the shared production database also took production work, such as alerts and payment releases. Work started by cron goes only to the server named in `ORDELO_APP_URL`.
- **Pauses.** The loops stopped while the Fly machine was suspended. A cron POST wakes the machine.
- **No visibility.** The loops did not appear in `cron.job` or `cron.job_run_details`, and they could not be paused with `cron.unschedule`.

## Decision

- **Postgres owns every timer.** All scheduled, retried or swept work is a pg_cron job, one `ordelo_datamodels/<capability>/job_*.sql` per job. FastAPI never starts a polling loop.
- **The job decides when work is due.** It POSTs to the app only when something is due, through `app_hook_post(path, payload)` (`platform/app_hook_post.sql`). That helper owns the URL lookup, the fallback and the timeout. Either the job marks rows only after a 2xx answer, or the hook claims rows through an RPC (`FOR UPDATE SKIP LOCKED` with a lease) and the job only wakes it.
- **The route is thin.** It answers at once, does the I/O in `BackgroundTasks`, re-checks the database before every send, and has a `Called by database:` line.
- **Triggers do not schedule.** A database trigger handles an immediate reaction to a row change. It is never the retry schedule, because the synchronous `http` extension would block the writing transaction.
- **One job per kind of work.** Unrelated sweeps do not share a job, so one failure cannot block another, and each job can be paused and inspected on its own.

## Consequences

- The rider invite alerts move to `job_rider_invite_alerts` (every minute). The customer notifier loop becomes three jobs: outbox sweep and web lifecycle sweep every minute, and the price audit hourly at :05, which POSTs only when today's London audit is due (no `web_monitor_run` row for that date yet), so a failed audit is retried within the hour. The `lifespan` keeps only client setup.
- **Temporary exception.** The two per-minute customer jobs (outbox and web lifecycle, not the price audit) wake the app every minute even when nothing is due (option B), because their Python sweeps are unchanged for now. Moving their SQL-only steps into the jobs is in `docs/to-do.md`.
- Existing functions that build the hook URL inline move to `app_hook_post` when they are next edited (`docs/to-do.md`).
- An alert can wait up to one cron interval longer than with a 10-second loop. That is accepted.

## Considered and rejected

- **In-process loops in the FastAPI `lifespan`.** They have the problems listed under Context.
- **A trigger on the queue row.** It blocks the claim transaction on HTTP, makes the webhook handler call its own app before the commit, and still needs a retry schedule.
- **Adding invite alerts to `job_rider_offer_alerts`.** Turning offer reminders off (blank offsets) would silence invite alerts too, and the two would share failures.
