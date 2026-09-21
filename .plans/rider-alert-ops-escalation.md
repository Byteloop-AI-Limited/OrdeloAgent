# Ops escalation for late pickups and slow deliveries

## Context

The rider alert system (`.plans/rider-alert.md`, implemented) nudges the **rider**
at configurable checkpoints around `delivery_summary.pickup_time`. Nobody else
hears anything. If the rider ignores every nudge, the first sign of trouble is a
customer complaint.

This adds a second audience — **overwatch and the restaurant's admins** — at
exactly two moments:

| # | Moment | Condition | Default offset |
|---|---|---|---|
| 1 | Rider has not collected | dispatch still `assigned` | `+10` past pickup time |
| 2 | Collected but not delivered | dispatch `pickedup` | `+30` past pickup time |

Both are measured from `delivery_summary.pickup_time`, the same anchor
everything else uses.

**Confirmed with the user:** point 1 fires *only* while the rider has not
collected. A rider who collects on time never triggers it, so ops hears once
about a slow delivery rather than twice about a merely late one.

Consequence worth naming: an order the rider *never* collects escalates once at
`+10` and then goes quiet, because point 2 requires collection. That is the
"exactly two points" the request asked for; a third checkpoint would just be
another row in the config.

## Design

The existing machine already has the right shape. This adds **one dimension**,
`audience`, and changes nothing about phases, collapse-to-max, the 2xx marking,
or the reschedule trigger.

```
ledger row = (dispatch_id, phase, audience, offset_minutes)
                            │        │
        DeliveryProgress ───┘        └─── 'rider' | 'ops'
        the delivery must be in
```

Four config keys — one per (audience, phase) pair:

| Audience | Phase | Config key | Default |
|---|---|---|---|
| `rider` | `awaiting_pickup` | `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` | `-15,-5,2,5,7` |
| `rider` | `picked_up` | `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` | `30,45` |
| `ops` | `awaiting_pickup` | `rider_alert_to_overwatch_pickup_intervals` | `10` |
| `ops` | `picked_up` | `rider_alert_to_overwatch_delivery_intervals` | `30` |

> The two new keys are **lowercase**, matching the `overwatch_list` key they sit
> beside (`config/params.py:179`) and the name in the request. Deliberately
> inconsistent with the uppercase rider keys, and settled — not revisited at
> implementation time.

Each key stays an independent kill switch. Blank the two `ops` keys and
escalation stops without touching rider alerts.

### Ranking partitions by audience

Collapse-to-max currently partitions by `dispatch_id`, guaranteeing one alert
per rider per tick. It becomes `PARTITION BY (dispatch_id, audience)`, so one
rider alert **and** one ops alert can fire on the same tick — they are different
conversations and must not suppress each other.

### Delivery: direct sends, not the rider agent

Rider alerts run through the rider graph, per the standing rule that every
rider-facing delivery touchpoint must be visible in the agent's thread. **That
rule does not apply here** — ops escalations never reach the rider, so there is
no thread to keep faithful. They are direct WhatsApp sends, matching
`_process_admin_availability` and `_handle_restaurant_timedout`.

Two recipient sets, one message:

- **Overwatch** — `await (await get_wa_logger()).critical(text)`
  (`config/params.py:260`). `WALogger` already fans out to every number in
  `overwatch_list` and prefixes 🔴 (`config/waba_setting.py:197-238`). Reuse it
  rather than threading overwatch numbers through the payload.
- **Restaurant admins** — `restaurant_master.admins` for the order's `rest_id`,
  carried in the SQL payload exactly as `enquire_admin_availability` and
  `restaurant_updates_whook` already do, then a plain `send_message` per admin.

### The gate is unchanged

Ops alerts run through the same `check_delivery_progress` identity check as
rider alerts — `progress is not DeliveryProgress(phase)` means skip. An order
already delivered or cancelled must not escalate.

## Migration file

**`ordelo_datamodels/migrations/add_rider_pickup_alerts.sql`** — rewritten in
place, still one file, still a clean first install (nothing has been executed
yet, so `audience` is simply part of the table from the first line; no `ALTER`s).

### 1. Table

Add to the existing definition:

```sql
    audience       VARCHAR(20)  NOT NULL
                   CHECK (audience IN ('rider', 'ops')),
    ...
    PRIMARY KEY (dispatch_id, phase, audience, offset_minutes)
```

Like `phase`, `audience` gets no `DEFAULT` — the seeding INSERT is the only
writer and always names it.

### 2. Config

Extend the existing `INSERT ... ON CONFLICT DO NOTHING` to four rows, adding:

```sql
  ('rider_alert_to_overwatch_pickup_intervals', '10',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a rider has still not collected. Blank disables.'),
  ('rider_alert_to_overwatch_delivery_intervals', '30',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a collected order is still undelivered. Blank disables.')
```

### 3. `job_rider_pickup_alerts()`

**(a) Parse four keys** instead of two, via the existing `parse_alert_offsets`
helper, keeping the per-key `RAISE NOTICE` when a key exists but yields nothing.
Bail only when all four are `NULL`.

**(b) Seed** — the phase VALUES list grows an audience column and two rows:

```sql
CROSS JOIN (VALUES
    ('rider'::varchar, 'awaiting_pickup'::varchar, 'assigned'::varchar, v_rider_pickup),
    ('rider'::varchar, 'picked_up'::varchar,       'pickedup'::varchar, v_rider_delivery),
    ('ops'::varchar,   'awaiting_pickup'::varchar, 'assigned'::varchar, v_ops_pickup),
    ('ops'::varchar,   'picked_up'::varchar,       'pickedup'::varchar, v_ops_delivery)
) AS ph(audience, phase, gate_status, offsets)
```

`NOT EXISTS` becomes scoped per `(dispatch_id, phase, audience)`, preserving
snapshot semantics within each bucket.

**(c) Rank** — `PARTITION BY a.dispatch_id, a.audience`; carry `a.audience` into
the payload. Two extra joins so the payload can carry `rest_name`,
`rest_admins` and `rider_name` — an ops message naming the restaurant and rider
is far more useful than one naming a dispatch id:

```sql
LEFT JOIN restaurant_master rm  ON rm.rest_id   = ds.rest_id
LEFT JOIN rider_master      rdr ON rdr.rider_id = a.rider_id
```

`LEFT`, not inner: a missing `restaurant_master` or `rider_master` row must
degrade the message, never drop the alert. Both fields are harmless for rider
rows, which ignore them.

**These joins belong to (c) only.** The step-(e) supersede CTE deliberately
carries just `phases` / `delivery_inflight` / `delivery_dispatch` — it needs no
`delivery_summary`, `restaurant_master` or `rider_master`, because it selects
nothing from them. Do not "sync" the two CTEs; the existing comment in (e)
explains why the divergence is safe.

**(d) POST** — payload items gain `audience`, `rest_name`, `rest_admins`,
`rider_name`.

**(e) Mark** — both `UPDATE`s additionally match on `audience`, now that it is
part of the key. **Supersede first** — the existing ordering comment still
applies.

### 4. Reschedule trigger — no change

It updates every row for the `order_number` regardless of audience, and all four
buckets hang off the same anchor.

## Python changes

### `utils_common/waba_utils/wa_senders.py` — new sender

`notify_ops_rider_alert(*, phase, order_number, rest_name, rider_name, pickup_time, minutes_past, rest_admins)`:

- builds one message, phrased from the **real** minutes past pickup rather than
  the configured offset (the same rule the rider tool follows):
  - `awaiting_pickup` → `🚨 Order *{order_number}* at {rest_name}: rider {rider_name} has still not collected — {n} min past the {time} pickup time.`
  - `picked_up` → `🚨 Order *{order_number}* at {rest_name}: {rider_name} collected but has not delivered — {n} min past the {time} pickup time.`
- sends it to overwatch via `(await get_wa_logger()).critical(text)`
- sends it to each admin in `rest_admins` via `_async_wa_client.send_message`
- reuses `fmt_uk_time` (`utils_common/tz_utils.py:15`) for the displayed time

**The two audiences must be isolated from each other**, each in its own
`try/except`, because by the time this runs the SQL has already marked the
checkpoint `sent` on the 2xx — anything that escapes here is an escalation lost
permanently, not retried on the next tick. Two specific ways that happens:

- **No `overwatch_list` config row.** `get_overwatch_list()` *raises
  `ValueError`* rather than returning `[]` (`config/params.py:191`), and
  `get_wa_logger()` calls it unguarded. Uncaught, that would take the admin
  fan-out down with it. Catch it, log it, and still notify the admins — they are
  the more actionable audience anyway.
- **`restaurant_master.admins` NULL or empty.** The column is nullable
  (`masterdata.sql:25`) and `restaurant_confirmation_flow` already treats a
  restaurant with no contacts as a real problem. Log a `warning` naming the
  `rest_ref` and carry on to overwatch; do not fail silently.

Each individual admin send is isolated too, so one bad number cannot cost the
others their alert.

### `watomation/routers/delivery_hooks.py` — branch on audience

`_process_rider_pickup_alerts` keeps its per-alert isolation and its phase gate,
then branches after the gate passes:

```python
audience = alert.get("audience") or "rider"        # absent => pre-audience payload
if audience == "ops":
    await notify_ops_rider_alert(...)
elif audience == "rider":
    await run_rider_agent_w_custom_msg(...)        # unchanged
else:
    logger.error(...); continue                    # skip, do not guess
```

Defaulting to `rider` keeps a pre-migration payload working if the app is
deployed first. Unknown audiences are skipped, mirroring the unknown-phase
handling.

### Docs

- `CONTEXT.md` — extend the **Pickup alert** entry with the audience dimension
  and the two escalation moments.
- `docs/delivery_process.md` — the four config keys, the widened ledger key, and
  `audience` in the documented payload.

## Tests

- `tests/watomation/routers/test_delivery_hooks.py`
  - ops alert calls `notify_ops_rider_alert` and does **not** run the agent
  - rider alert still runs the agent and does not escalate
  - ops alert skipped when progress does not match its phase
  - unknown audience skipped; absent audience defaults to `rider`
- `tests/utils_common/waba_utils/test_wa_senders.py` (existing file)
  - both phases' wording, driven by the real minutes past pickup
  - message reaches overwatch **and** every admin
  - one failing admin send does not prevent the others
  - `get_overwatch_list()` raising `ValueError` still delivers to admins
  - NULL / empty `rest_admins` still delivers to overwatch, and warns
- Keep test times off `.5` rounding boundaries — the `_pickup_time_in` docstring
  in `tests/ordelo/agents/test_rider_agent.py` explains why.

## Verification

*The user runs all SQL manually; I execute none of it.*

1. `uvx ruff check` on changed files (expect no new findings) and `uv run pytest`.
   `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`
   already fails on a clean tree — unrelated.
2. Run the migration's step-0 pre-flight (`parse_alert_offsets` signature check),
   then apply the file. **Run it twice** to confirm it is re-runnable. Check all
   four keys landed and that `overwatch_list` is populated — an empty overwatch
   list silently sends escalations to nobody but the admins.
3. Rider phases — walk the existing numbered steps in the file's trailing
   comment block; behaviour must be unchanged.
4. **Escalation point 1.** On a dispatch still `assigned`, set
   `pickup_time = now() - interval '11 minutes'` and run the job. Expect the
   overwatch numbers and the restaurant's admins to receive one 🔴 "still not
   collected" message, and `SELECT phase, audience, offset_minutes, status FROM
   rider_pickup_alert WHERE order_number = '<ORDER>' ORDER BY audience, phase,
   offset_minutes;` to show the `ops/awaiting_pickup/10` row `sent`. Re-run —
   silent.
5. **Escalation point 2.** Collect the order (verify the restaurant code through
   the agent) and set `pickup_time = now() - interval '31 minutes'`. Expect one
   "collected but not delivered" message to the same recipients, and the
   `ops/picked_up/30` row `sent`.
6. **Both audiences on one tick — the sharpest test in this set**, and the only
   one that proves the partition change. Both delivery keys default to offset
   `30`, so on a freshly collected dispatch at
   `pickup_time = now() - interval '31 minutes'` there are two separate ledger
   rows with the *same* `offset_minutes` differing only by `audience` — exactly
   what the widened primary key exists for. One run must produce **two**
   messages: one to the rider through the agent, one to ops. If the partition
   were still `dispatch_id` alone, only one would fire.
7. **Independent kill switches.** Blank both `rider_alert_to_overwatch_*` keys;
   rider alerts must still fire and no escalation goes out. Restore, then blank
   the two rider keys and confirm the reverse.
8. Escalations stop after delivery: complete the order and confirm a further run
   sends nothing, with any remaining rows left `pending` and inert.
9. Only then register the cron:
   `SELECT cron.schedule('job_rider_pickup_alerts', '*/2 * * * *', $$SELECT job_rider_pickup_alerts()$$);`
