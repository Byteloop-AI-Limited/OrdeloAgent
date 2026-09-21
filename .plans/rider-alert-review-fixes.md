# Code review findings — rider & ops pickup alerts

## Context

`/code-review high` ran against the uncommitted working tree (the rider/ops
pickup-alert feature). It returned five findings, one HIGH. This document
records all five and plans the fix for the HIGH one.

**Status: DONE.** Findings #1-#4 are fixed, the tree is green (393 passing, plus
the pre-existing `test_restaurant_master_get_admins_fetches_live_column`
failure). #5 remains deferred. What follows is the record of what was found and
what was changed.

| File | Already changed | For finding |
|---|---|---|
| `utils_common/tz_utils.py` | new `to_utc_aware()` helper | #1 |
| `ordelo/agents/rider_agent.py` | tool uses `to_utc_aware` instead of `parse_db_iso` | #1 |
| `ordelo/agents/agent_runner.py` | new `clear_pickup_alert_cue()`; `init_ordelo_graph` seeds the cue clean | #3 |
| `watomation/routers/delivery_hooks.py` | live `rider_id` from the progress row; `order_number`/`pickup_time` sourced from the payload; `finally: clear_pickup_alert_cue` | #2, #3, #4 |
| `tests/watomation/routers/test_delivery_hooks.py` | autouse `cue_clears` fixture; one assertion updated | test support |

Those two red tests are now repaired (see "Repairing the red tree"), and the
regression tests for #1 are written and mutation-verified. Nothing has been
applied for #5.

## The findings

### #1 — HIGH. `notify_pickup_reminder` raises on the normal path; every rider alert is silently lost

`ordelo/agents/rider_agent.py`, in `notify_pickup_reminder`.

**This was introduced in this session, not surfaced from older code.** The tool
was written to parse the timestamp directly while the sibling tool next to it
(`notify_pickup_time_adjusted`) went through `fmt_uk_time`, which coerces. Every
test written alongside it passed an ISO string, so the suite was green while the
feature was broken on the path it actually runs on.

The tool called `parse_db_iso(pickup_time)`, whose comment claimed the value
"originates from a timestamptz column". It does not — it comes from **graph
state**, and `init_ordelo_graph` (`ordelo/agents/agent_runner.py:240`) writes
`DeliverySummary.pickup_time`, which is `Optional[datetime]`
(`ordelo_datamodels/delivery_pymodels.py:82`). `parse_db_iso` does
`iso.replace("Z", "+00:00")`, which on a `datetime` calls
`datetime.replace(year="Z", ...)`.

Verified directly in the project venv:

```
TypeError: 'str' object cannot be interpreted as an integer
```

Why it is severe rather than merely broken:

- LangGraph's `ToolNode` defaults to `handle_tool_errors=True`, so the exception
  becomes a `ToolMessage` rather than propagating. The router's `try/except`
  never fires and it **logs "Pickup alert sent"** — the log actively lies.
- The SQL has already marked the checkpoint `sent` on the 2xx, so the alert is
  **lost permanently**, not retried on the next tick.

Why the new tests missed it: every test passes an ISO **string**. The sibling
path `_handle_restaurant_pickuptime_adjusted` writes `DeliverySummaryData.pickup_time`,
declared `Optional[str]`, so the tool only works on threads where an admin has
already adjusted the pickup time. On a fresh delivery it always fails.

### #2 — MEDIUM. Rider alert reads `order_number` / `pickup_time` from stale graph state

`watomation/routers/delivery_hooks.py`, `_process_rider_pickup_alerts`.

Only `pickup_alert_offset` / `pickup_alert_phase` were pushed into state; the
tool then read `order_number` and `pickup_time` from whatever the thread last
stored. `_handle_restaurant_pickuptime_adjusted` refreshes state `pickup_time`
**only** while progress is `AWAITING_PICKUP`, so a pickup-time change after
collection leaves the thread stale — SQL reschedules `due_dtts` off the new
time while the `picked_up` reminder quotes the old one.

### #3 — MEDIUM. The `pickup_alert_offset` cue is never disarmed when the tool doesn't run

`run_rider_agent_w_custom_msg` writes the cue via `aupdate_state` *before*
`ainvoke`. If the LLM replies with text instead of calling the tool, the offset
stays in state, and the tool's own guard (`if alert_offset is None`) then
*permits* the call on an unrelated turn hours later — a bogus "you're N min past
pickup". Compounds with #1: because the crash happens before the
`Command(update=...)` that clears the cue, it is left armed on **every** alert
today. `clear_wa_location_request` is the existing precedent for this.

### #4 — LOW. Alert can be sent to a replaced rider

The recipient came from the payload, not from the `row` that
`check_delivery_progress` returns. If the original rider declines pre-pickup
between the sweep's POST and the background task running, the order is
re-dispatched and the old rider gets "please collect ASAP" for a job they no
longer have. `_handle_restaurant_pickuptime_adjusted` already uses
`row["rider_id"]`.

### #5 — LOW. `notify_ops_rider_alert` reports `overwatch: "sent"` when nothing was sent

`utils_common/waba_utils/wa_senders.py`. `WALogger._send` uses
`asyncio.gather(..., return_exceptions=True)` (`config/waba_setting.py:237`) and
never raises, and an empty `overwatch_list` produces zero sends. So `"sent"` is
recorded unless `get_wa_logger()` itself raises — an empty or entirely-failing
overwatch list still reads as success. Given the function's own premise that a
lost escalation is lost for good, the return value cannot be used for alerting.

### Reported as considered-and-dismissed

- `rider_pickup_alert_reschedule` would violate `due_dtts NOT NULL` if
  `pickup_time` were ever cleared; the only path that nulls it
  (`test_reset_order_and_dispatch`) deletes `delivery_dispatch` first, so the
  ledger cascades away first. Latent only.
- Blocking `get_overwatch_list()` inside async `get_wa_logger()` violates the
  `asyncio.to_thread` rule in CLAUDE.md, but it is pre-existing, not this diff.

## Plan — fix the HIGH finding

### 1. `utils_common/tz_utils.py` — `to_utc_aware()` *(already applied)*

```python
def to_utc_aware(iso_or_dt: str | datetime) -> datetime:
    dt = _coerce(iso_or_dt)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
```

Reuses the existing `_coerce`, which is exactly the str-or-datetime absorber
`fmt_uk_time` already relies on — which is *why* `fmt_uk_time` never hit this
bug. Also normalises a naive value to UTC so the subtraction cannot raise
`TypeError: can't subtract offset-naive and offset-aware datetimes`.

### 2. `ordelo/agents/rider_agent.py` — use it *(already applied)*

`notify_pickup_reminder` computes the delta through `to_utc_aware(pickup_time)`.
The misleading comment is replaced with one naming both shapes state can hold.

### 3. Regression test that would have caught it *(written, mutation-verified)*

`tests/ordelo/agents/test_rider_agent.py`: call `notify_pickup_reminder` with
`pickup_time` as a **`datetime`**, the shape `init_ordelo_graph` actually
writes, and assert a message is sent. Every existing test passes a string, which
is why the suite was green while the normal path was broken.

Add the same for a **naive** datetime, since `to_utc_aware` now promises that
works.

### 4. Repairing the red tree

Both failures are consequences of the partial fixes, not new defects:

- `test_process_rider_pickup_alerts_in_transit_runs_agent_when_picked_up`
  asserts `state_update_dict == {offset, phase}`. It now also carries
  `order_number` and `pickup_time` (#2). **Update the expected dict** — same fix
  already applied to the sibling awaiting-pickup test.
- `test_process_rider_pickup_alerts_isolates_a_failing_alert` builds two alerts
  for RIDER01 and RIDER02, but the shared `_progress()` helper returns a fixed
  row `{"rider_id": "RIDER01"}` for *every* call, so the new live-rider lookup
  (#4) redirects RIDER02's alert to RIDER01. **Give the test a progress stub
  keyed by `order_number`**, which is what the real function does anyway — the
  fixture was papering over a distinction the code now depends on.

## Scope — settled

**Keep all four.** The #2 / #3 / #4 edits already in the working tree stay; #1 is
finished with its regression tests and the two red tests are repaired. Four
findings close in one pass.

**#5 is deferred**, deliberately. The honest fix is to inspect
`wa_logger.overwatch_list` and report `no_recipients` when it is empty, rather
than claiming `"sent"`. It is independent of everything above and is better done
on its own so the change is visible rather than buried in this diff.

### Work completed

1. **Regression tests for #1** — `test_notify_pickup_reminder_accepts_a_datetime_from_graph_state`
   and `..._accepts_a_naive_datetime_from_graph_state`. **Mutation-verified**:
   reverting `to_utc_aware` to `parse_db_iso` makes both fail with the exact
   production error (`TypeError: 'str' object cannot be interpreted as an
   integer`), and they pass again on revert.
2. **Both red tests repaired.** The `in_transit` one now expects the
   payload-sourced `order_number`/`pickup_time`; the isolation one uses a new
   `_progress_by_order()` stub keyed on `order_number`, since the flat helper
   returned one fixed rider for every call and masked the distinction #4
   introduced.
3. **Added `test_process_rider_pickup_alerts_sends_to_the_rider_on_the_live_inflight_row`** —
   #4 previously had only incidental coverage. Asserts an alert whose payload
   names `RIDER_OLD` reaches `RIDER_NEW` from the live progress row.
4. `pytest`: **393 passing**, 1 pre-existing failure. The count reconciles as
   381 before this round + 3 added here (2 datetime regression, 1 live-rider)
   + 9 from `tests/watomation/routers/test_sys_admin_auth_session.py`, an
   untracked file added outside this work.
5. `ruff`: 12 findings across the touched files, **all pre-existing**.
   `tz_utils.py` adds none (`All checks passed!` on its own), and the
   `agent_runner.py` one is at line 365 in `job_end_stale_conversations`, not in
   the helper added here. No stash baseline was taken this round on purpose —
   stashing would have swept up unrelated concurrent edits.

## Verification

1. `uv run pytest` — must be **381 passing, 1 pre-existing failure**
   (`test_restaurant_master_get_admins_fetches_live_column`, which fails on a
   clean stash). Anything else is regression.
2. `uvx ruff check` on changed files — compare against a `git stash` baseline;
   the count must be identical, not merely small.
3. The regression test from step 3 must **fail** if `to_utc_aware` is reverted to
   `parse_db_iso`. Verify by mutation, not by assuming — the whole point is that
   the previous suite passed while the feature was broken.
4. End-to-end, the check no automated test can make: on a **fresh** delivery
   (one where no admin has adjusted the pickup time, so state still holds a
   `datetime`), set `pickup_time = now() + interval '4 minutes'`, run
   `SELECT job_rider_pickup_alerts();` and confirm the rider actually receives
   the WhatsApp message. Before this fix that path produced a "Pickup alert
   sent" log line and no message.
