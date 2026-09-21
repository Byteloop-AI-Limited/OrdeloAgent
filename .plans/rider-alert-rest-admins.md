# Pickup alerts — `rest_admins` as a third audience

**Status: DONE, not yet run.** All code/SQL/test/doc changes below are applied.
Full suite: **400 passing**, same single pre-existing failure as before this
change (`test_restaurant_master_get_admins_fetches_live_column`, unrelated).
`ruff` on the four touched Python files: 8 findings, all pre-existing, none in
the new code. Both mutation checks in §4 verified fail-then-pass. **The SQL has
not been executed** — I do not run SQL; the user runs it by hand, starting from
§6's housekeeping (already done for the plan files, still pending for the
database itself) and the runbook in the SQL file, per the original directive
that all SQL changes land in one file the user executes manually.

## Context

The pickup-alert ledger (`rider_pickup_alert`, `job_rider_pickup_alerts()`) has
two audiences: `rider` (via the agent) and `ops` (a single message fanned out to
**both** the `overwatch_list` and the restaurant's admins by
`notify_ops_rider_alert`). The restaurant therefore only ever hears about a late
rider at the ops schedule (+10 / +30), in overwatch's 🚨 wording, and cannot be
given its own schedule.

This change makes restaurant admins their own audience, `rest_admins`, with
their own config keys and restaurant-facing wording, and narrows `ops` to
**overwatch only** so nobody is messaged twice on one tick.

Decisions taken in the grill (settled, not to be re-opened):

| Question | Answer |
|---|---|
| What happens to `ops`? | Overwatch only. The admin loop leaves `notify_ops_rider_alert`. |
| `rider_alert_to_rest_admins_pickup_intervals` default | `-10,2,7` — a heads-up before pickup, two chases after |
| `rider_alert_to_rest_admins_delivery_intervals` default | `''` — wired end to end but inactive |
| Wording | Restaurant-oriented, sign-aware, derived from the **real** delta (see §3) |
| Suppress for `configured_auto` restaurants? | No. Alert every restaurant; the config key is the off switch. |
| Which SQL file | `ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql` is canonical; delete the `migrations/` copy |
| Audience value | `rest_admins` (the user's word; fits `VARCHAR(20)`; sits fine next to the payload's `rest_admins` phone array) |

**Precondition:** neither SQL copy has been executed. The table is `CREATE TABLE
IF NOT EXISTS`, so the `CHECK` edit below only lands on a fresh run. If it turns
out the file *was* run, the one-liner is
`ALTER TABLE rider_pickup_alert DROP CONSTRAINT rider_pickup_alert_audience_check, ADD CONSTRAINT rider_pickup_alert_audience_check CHECK (audience IN ('rider','ops','rest_admins'));`.
I do not execute SQL; the user runs it by hand.

## Why `''` is the inactive default (verified against `parse_alert_offsets`)

`string_to_array('', ',')` unnests to zero matching rows → `array_agg` → NULL →
`unnest(NULL)` seeds nothing. Step (a)'s junk-config NOTICE loop has
`AND btrim(c.config_value) <> ''`, so a blank key is silent. Any *placeholder*
(`'off'`, `'-'`) would also seed nothing but would `RAISE NOTICE ... contains no
valid integers` **every 2 minutes forever**. Blank is the documented switch
("Blank any key to switch off just that bucket"); the config row's `description`
will say so explicitly so nobody later "fixes" the blank.

## 1. SQL — `ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql`

Executable changes, in file order:

1. **§1 ledger** — `CHECK (audience IN ('rider', 'ops', 'rest_admins'))`.
2. **§2 config** — two new rows in the same `INSERT ... ON CONFLICT DO NOTHING`:
   ```sql
   ('rider_alert_to_rest_admins_pickup_intervals',
    '-10,2,7',
    'Signed minutes around delivery_summary.pickup_time at which to message the restaurant''s admins about the rider; negative = heads-up before pickup, positive = chase after. Blank disables.'),
   ('rider_alert_to_rest_admins_delivery_intervals',
    '',
    'Minutes after delivery_summary.pickup_time at which to tell the restaurant''s admins a collected order is still undelivered. BLANK ON PURPOSE = inactive; set e.g. 30 to enable. Do not use a placeholder word.')
   ```
   Rewrite the two `rider_alert_to_overwatch_*` descriptions to drop
   "and restaurant admins" — they are overwatch-only now.
3. **§4 (a) read config** — `DECLARE v_rest_admins_pickup int[]; v_rest_admins_delivery int[];`
   read via `parse_alert_offsets(...)`; **add both keys to the hardcoded
   `config_key IN (...)` list of the NOTICE loop** (otherwise a typo'd
   rest_admins value disables the bucket with no diagnostic); extend the
   all-NULL short-circuit to six.
4. **§4 (b) seed** — two rows in the VALUES bucket table:
   ```sql
   ('rest_admins'::varchar, 'awaiting_pickup'::varchar, 'assigned'::varchar, v_rest_admins_pickup),
   ('rest_admins'::varchar, 'picked_up'::varchar,       'pickedup'::varchar, v_rest_admins_delivery)
   ```
   Nothing else in (b)–(e) changes: NOT EXISTS is already scoped per
   `(dispatch, phase, audience)`, ranking already partitions by
   `(dispatch_id, audience)`, the payload already carries `rest_admins`,
   `rest_ref`, `rest_name`, `rider_name`, and the trigger already reschedules
   every audience. The `picked_up` row seeds zero rows while the key is blank.

Documentation changes (comments only; verify with the comment-stripping diff
that executable lines change only where listed above):

- Title → "RIDER, OPS & RESTAURANT-ADMIN PICKUP ALERTS"; object map "6 rows in
  ordelo_config"; "six BUCKETS"; audience legend gains
  `rest_admins -> the restaurant's admins`, and `ops -> overwatch` (drop
  "+ admins").
- Bucket table gains two rows (`rest_admins / awaiting_pickup / ... / -10,2,7`
  and `rest_admins / picked_up / ... / (blank = off)`).
- Worked example: add `11:50 rest_admins: "rider due to collect at 12:00"`,
  `12:02 rest_admins: "not yet collected, 2 min past"` and a `12:07` line, and
  note the **12:07 / 12:10** cluster now shows three audiences.
- "(a) read the four config keys" → six; "Blank all four" → six; §5 comment
  "all four buckets" → "all six".
- **Runbook**:
  - 0b: `config_key LIKE 'rider_alert_to_%'` (the old `_overwatch_%` pattern
    misses the new family). "All six keys present."
  - 3: also expect ONE rest_admins message ("due to collect ... in ~4 min");
    rest_admins −10 sent, 2/7 pending.
  - 5: rest_admins 2 fires ("6 min past"), −10 superseded, 7 pending.
  - **6 becomes THE SHARPEST CHECK** (label moves off step 7): at +11 expect
    **three** messages from one run — rider 7 via the agent, overwatch 🔴 from
    ops 10, restaurant admins ⏰ from rest_admins 7 — and note rider and
    rest_admins fire at the **same `offset_minutes` = 7**, which is the case the
    4-column PK and `PARTITION BY dispatch_id, audience` exist for. Drop
    "AND the restaurant's admins" from the ops expectation.
  - 7: "one to overwatch" (not "+ admins"); rest_admins/picked_up has no rows
    because its key is blank — say so.
  - 8: blank `rider_alert_to_%` (all four non-rider keys), restore values
    `10`, `30`, `-10,2,7`, `''`.
  - 8b (new): enable the inactive bucket — set the delivery key to `30`, re-run
    at +31 on a `pickedup` dispatch, expect the admins' 🛵 "collected but not
    delivered" message, then blank it again. This is the only end-to-end
    exercise the `picked_up` branch of the new sender will ever get.
  - 11: "Blank all six".

## 2. Router — `watomation/routers/delivery_hooks.py`

`_process_rider_pickup_alerts` (≈line 1159): add a branch between `ops` and
`rider`:

```python
elif audience == "rest_admins":
    await notify_rest_admins_rider_alert(
        phase=str(required),
        order_number=order_number,
        pickup_time=alert.get("pickup_time"),
        rider_id=rider_id,
        rider_name=alert.get("rider_name"),
        rest_ref=alert.get("rest_ref"),
        rest_admins=alert.get("rest_admins"),
    )
```

The `ops` branch drops its `rest_admins=` kwarg. Unknown-audience and
missing-audience-defaults-to-rider behaviour is unchanged. Update the function
docstring ("'ops' → overwatch; 'rest_admins' → the restaurant's admins") and the
module header bullet (≈line 15–18, "two audiences ... overwatch plus the
restaurant's admins" → three audiences). Import the new sender next to
`notify_ops_rider_alert` (≈line 96).

Admin numbers come from the **payload** (`restaurant_master.admins`, read by
the SQL at resolve time). Not `RestaurantMaster.get_admins_for()`: it is
sync/cached and would need `asyncio.to_thread`, and the payload is the fresher
read of the same column.

## 3. Senders — `utils_common/waba_utils/wa_senders.py`

### `notify_ops_rider_alert` → overwatch only

- Drop the `rest_admins` parameter and the admin loop. Keep `rest_ref` (label
  fallback). Return `{"overwatch": "sent" | "failed"}`.
- Docstring: "Escalates ... to overwatch." Remove the "two audiences are
  isolated" paragraph; the `get_overwatch_list()`-raises note stays (it is still
  why the try/except exists).
- Finding #5 (`"sent"` reported when `overwatch_list` is empty) stays
  **deferred** — same reasoning as before: fix it visibly, not buried here.

### New `notify_rest_admins_rider_alert`

```python
async def notify_rest_admins_rider_alert(
    *,
    phase: str,
    order_number: str,
    pickup_time: str,
    rider_id: str,
    rider_name: Optional[str] = None,
    rest_ref: Optional[str] = None,
    rest_admins: Optional[List[str]] = None,
) -> dict:  # {"admins_notified": int, "admins_failed": int}
```

- Delta: `round((now_utc - parse_db_iso(pickup_time)).total_seconds() / 60)` —
  `pickup_time` here **is** an ISO string from the SQL payload (unlike the
  rider tool's graph-state case that caused finding #1), so `parse_db_iso` is
  correct; `fmt_uk_time` for the display time. Same as the ops sender.
- Three texts, chosen by `phase` then sign of the real delta:
  - `picked_up`: `🛵 Order *{n}*: rider {r} collected but has not delivered — {k} min past the {t} pickup time.`
  - `awaiting_pickup`, delta `< 0`: `🛵 Order *{n}*: rider {r} is due to collect at {t} (in ~{|k|} min). Please have it ready.`
  - `awaiting_pickup`, delta `>= 0`: `⏰ Order *{n}*: rider {r} has not yet collected — {k} min past the {t} pickup time.`
  A −10 checkpoint that fires late (cron lag) lands in the chase branch and says
  the truth; collapse-to-max already prefers the +2 row when both are due.
- Recipients: `list(dict.fromkeys(a for a in rest_admins or [] if a))` — the
  dedupe idiom from `customer_hooks._notify_feedback_admins`. Empty → one
  `logger.warning(... no admins on record for rest_ref=...)` and return zeros;
  it is not an error, restaurants without admins exist.
- Per-number isolation: the existing `for admin in ...: try/except` loop moves
  here from the ops sender, unchanged.
- No rider graph involvement — same rationale as the ops sender.

Update the module header list (line 26) to describe both senders.

## 4. Tests

### `tests/utils_common/waba_utils/test_wa_senders.py`

Five existing ops tests — two updated, three **relocated** (not deleted):

| Test | Action |
|---|---|
| `..._awaiting_pickup_reaches_overwatch_and_admins` | rename `..._reaches_overwatch`; drop `rest_admins=` and the admin-send assertions; expect `{"overwatch": "sent"}` |
| `..._picked_up_chases_the_delivery` | drop `rest_admins=`; otherwise as is |
| `..._survives_missing_overwatch_list` | premise ("admins must still be told") dies with the split. Reduce to: returns `{"overwatch": "failed"}`, does not raise |
| `..._warns_and_continues_without_admins` | **move** to the new sender: `rest_admins=None` → `{"admins_notified": 0, "admins_failed": 0}`, no send |
| `..._isolates_a_failing_admin` | **move** to the new sender, same flaky-number stub, `notified == 1, failed == 1` |

New for `notify_rest_admins_rider_alert`:

- heads-up: `pickup_time` 9.8 min in the **future** → text contains
  "due to collect", "in ~10 min", "Please have it ready"; same text to every
  admin; `notified == len(admins)`.
- chase: 6.2 min past → "has not yet collected", "6 min past", no "due to".
- `picked_up`: 31.2 min past → "collected but has not delivered". **This
  branch is config-disabled, so no runbook step or integration path exercises
  it; this unit test is the only thing standing there.**
- dedupe: `["ADMIN01", "ADMIN01", "", "ADMIN02"]` → exactly two sends.

### `tests/watomation/routers/test_delivery_hooks.py`

- `test_process_rider_pickup_alerts_ops_audience_escalates_instead_of_running_agent`:
  delete the `escalations[0]["rest_admins"] == ["ADMIN01"]` line.
- `_capture_escalations` fake returns `{"overwatch": "sent"}`.
- New `_capture_rest_admin_alerts(monkeypatch)` helper mirroring it.
- New tests:
  - `..._rest_admins_audience_messages_admins_not_agent_or_overwatch` — one
    `rest_admins`/`awaiting_pickup`/offset 7 alert → new sender called once with
    `rest_admins == ["ADMIN01"]`, `rider_id` from the **live** progress row,
    zero agent calls, zero ops calls.
  - `..._rest_admins_audience_skipped_on_phase_mismatch` — progress
    `PICKED_UP`, alert phase `awaiting_pickup` → no send.
  - `..._three_audiences_on_one_tick_are_all_delivered` — rider 7, ops 10,
    rest_admins 7 for the same order in one payload → one agent call, one ops
    call, one rest_admins call. Mirrors runbook step 6.

Mutation check before declaring done: comment out the `elif audience ==
"rest_admins"` branch → the first new router test must fail via the
unknown-audience path; swap the `<`/`>=` in the wording branch → the heads-up
test must fail.

Existing tests that must stay green untouched: the 25 in `test_rider_agent.py`
(rider path is not changed).

## 5. Docs

- `CONTEXT.md` "Pickup alert": audience bullet gains `rest_admins`; `ops`
  becomes "overwatch list" only; bucket table → six rows.
- `docs/delivery_process.md` (≈lines 601–650): "two audiences = four buckets"
  → "three audiences = six buckets"; table → six rows; "ops alerts go to the
  overwatch_list via ... and the restaurant's admins" → split into two lines.
- `ordelo/agents/rider_agent_prompt.md`: no change (rider path untouched).

## 6. File housekeeping (cannot be done in plan mode; first implementation step) — DONE

1. ✅ Deleted `ordelo_datamodels/migrations/add_rider_pickup_alerts.sql`
   (byte-identical duplicate; `jobs_n_functions/` is canonical).
2. ✅ Deleted `.plans/rider-alert.md` — described a 3-column PK and two config
   keys; superseded twice over.
3. ✅ Kept `.plans/rider-alert-review-fixes.md` as the record; this file was
   the byte-identical duplicate and is now the rest_admins plan, at
   `.plans/rider-alert-rest-admins.md`.
4. ✅ `.plans/rider-alert-ops-escalation.md` kept as the record of the ops
   design, with a note at its top: "Superseded in part by
   rider-alert-rest-admins.md: ops is now overwatch-only."

## Verification

1. ✅ `uv run pytest` — baseline was **393 passing + 1 pre-existing failure**
   (`test_restaurant_master_get_admins_fetches_live_column`). Actual:
   **400 passing**, same single pre-existing failure. Net +7: wa_senders tests
   14 → 18 (5 ops tests became 3 ops + 6 new rest_admins, net +4), delivery_hooks
   tests 37 → 40 (+3 new). Matches the plan's prediction exactly.
2. ✅ `uvx ruff check` on the four touched Python files (2 source + 2 test) —
   8 findings, all pre-existing (F821 `waba_cat_settings`, F841 unused locals,
   F401 unused imports — none inside code added by this change).
3. ✅ Comment-stripped diff against `git show HEAD:...job_rider_pickup_alerts.sql`
   (HEAD turned out to hold a tracked prior version) — confirmed the diff is
   confined to exactly the five spots listed in §1: the `CHECK`, the config
   `INSERT`, the `DECLARE`, step (a)'s reads/NOTICE-list/null-check, and the
   seed `VALUES`. Steps (c)/(d)/(e) and §5's reschedule trigger are
   byte-identical to the pre-change version.
4. ✅ Runbook step 3's expected wording was wrong on first pass ("in ~10 min",
   conflating the checkpoint offset with the real delta) — caught in review,
   corrected to "in ~4 min" per the code's actual rule (wording always comes
   from the real minutes-to/past-pickup, never the offset that triggered the
   checkpoint). Steps 5/6/7 were checked by hand against the same rule and are
   correct as written.
3. The two mutation checks in §4 actually fail, then pass on revert.
4. Comment-stripped diff of the SQL: executable lines change **only** in the
   `CHECK`, the config `INSERT`, the `DECLARE`, step (a), and the seed
   `VALUES`. Steps (c)–(e) and §5 byte-identical.
5. By hand (user, not me): run the SQL once, confirm six config rows and
   `overwatch_list`; walk runbook 0 → 12 with **step 6 as the gate** — three
   messages, three senders, one `SELECT job_rider_pickup_alerts();`. Then 8b to
   prove the dormant delivery bucket wakes on config alone. Schedule the cron
   last.
