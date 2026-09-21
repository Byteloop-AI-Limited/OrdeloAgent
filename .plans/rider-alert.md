# Rider pickup & delivery alerts

## Context

Riders get **no proactive nudge** around pickup time. Once `delivery_inflight`
is created the rider agent goes quiet until the rider speaks, the restaurant
taps "Ready", or an admin adjusts the pickup time. A rider who forgets, or is
running late, is invisible until the customer complains — and once they have
collected the food, a slow delivery run is equally invisible.

We want configurable **checkpoints** measured against
`delivery_summary.pickup_time`, in two phases:

| Phase | Dispatch status | Config key | Example |
|---|---|---|---|
| **Awaiting pickup** | `assigned` | `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` | `-15,-5,2,5,7` |
| **In transit** (collected, not delivered) | `pickedup` | `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` | `30,45` |

A pg_cron job sweeps every 2 minutes, resolves entirely in SQL which single
checkpoint (if any) is due per rider, and calls the FastAPI endpoint **only when
there is something to send**.

> **Status:** the awaiting-pickup phase is already implemented and tested (last
> change). This plan adds the in-transit phase; sections below are marked
> *(built)* or *(new)*.

### Sign convention

Comma-separated signed integers. **Negative = minutes TO pickup, positive =
minutes AFTER pickup.** Checkpoint `k` comes due at `pickup_time + k minutes`.

### Decisions taken

- **Both phases share one anchor: `delivery_summary.pickup_time`** (user's
  call). Not the actual collection moment. One anchor keeps a single `due_dtts`
  formula, lets the existing reschedule trigger cover both phases for free, and
  avoids the naive-`TIMESTAMP` handling that `delivery_dispatch.status_update_dtts`
  would need. Accepted consequence: a rider who collects *very* late (say 50
  minutes past pickup time) finds both `30` and `45` already passed, so
  collapse-to-max fires one immediate "52 min past pickup time" nudge and then
  nothing further.
- **The ledger is a persistent table, not `AgentState`** *(built)* — follows the
  precedent `ordelo/delivery_progress.py` set: durable operational facts live in
  the delivery tables, because graph state reads back `NULL` once
  `thread.is_active` flips.
- **All scheduling logic lives in the DB function** *(built)*. Python is a thin
  adapter: gate, then drive the agent.
- **All SQL ships as one migration file the user executes manually.** *I run no
  SQL.* **The earlier version was never applied**, so the file is rewritten as a
  single clean install with `phase` present from the start — no `ALTER`s, no
  primary-key rebuild, no backfill. It stays re-runnable
  (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`,
  `ON CONFLICT DO NOTHING`) purely so a half-finished run can be repeated.
- **An adjusted `pickup_time` reschedules every checkpoint** for the order, via
  trigger *(built — covers both phases unchanged, because they share the anchor)*.
- **The configured list is the complete schedule.** Each checkpoint fires once;
  nothing repeats past the largest offset. Extend the list to nag harder.
- **No `{REST_REF}_` per-restaurant override.**

## Design

The in-transit phase is the same machine with one extra parameter. `phase`
becomes a column, and everything else — collapse-to-max, the 2xx marking, the
reschedule trigger, the endpoint, the agent tool — is reused as-is.

**Phase names are deliberately the `DeliveryProgress` values**
(`ordelo/delivery_progress.py:29`): `'awaiting_pickup'` and `'picked_up'`. That
makes the Python gate a one-line identity check instead of a lookup table, and
means the SQL gate and the Python gate are provably the same concept.

| Phase (= required `DeliveryProgress`) | SQL gate | Config |
|---|---|---|
| `awaiting_pickup` | `dd.status = 'assigned'` | `..._PICKUP_ALERT_INTERVALS` |
| `picked_up` | `dd.status = 'pickedup'` | `..._DELIVERY_ALERT_INTERVALS` |

A dispatch is only ever in one phase, so at most one checkpoint can fire per
rider per tick — but the ranking still partitions by `dispatch_id` alone rather
than `(dispatch_id, phase)`, so that invariant holds structurally rather than by
argument.

### Unchanged rules *(built)*

- **Collapse to max**: when several checkpoints are due, only the largest fires;
  the rest are marked `superseded`. It is the most-recently-passed checkpoint and
  therefore the truest description of *now*.
- **Marking only on 2xx**: the sweep is one transaction, so a failed POST leaves
  rows `pending` and the next tick retries.
- **Wording from the real delta, never the offset.**
- **Cadence ≤ smallest gap between consecutive offsets** → `*/2`. The in-transit
  list matters here too: `30,45` has a gap of 15, so `*/2` is comfortable.

## Migration file changes *(new)*

**`ordelo_datamodels/migrations/add_rider_pickup_alerts.sql`** — rewritten in
place as **one clean install**. Nothing has been applied yet, so there is no
upgrade path to carry: `phase` is simply part of the table and its key from the
first line.

### 1. Table

```sql
CREATE TABLE IF NOT EXISTS rider_pickup_alert (
    dispatch_id    INTEGER      NOT NULL
                   REFERENCES delivery_dispatch(dispatch_id) ON DELETE CASCADE,
    phase          VARCHAR(20)  NOT NULL
                   CHECK (phase IN ('awaiting_pickup', 'picked_up')),
    offset_minutes INTEGER      NOT NULL,
    order_number   VARCHAR(100) NOT NULL,
    rider_id       VARCHAR(12)  NOT NULL,
    status         VARCHAR(20)  NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'sent', 'superseded')),
    due_dtts       TIMESTAMP WITH TIME ZONE NOT NULL,
    sent_dtts      TIMESTAMP WITH TIME ZONE,
    dt             DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dispatch_id, phase, offset_minutes)
);
CREATE INDEX IF NOT EXISTS rider_pickup_alert_due_idx
    ON rider_pickup_alert (status, due_dtts);
CREATE INDEX IF NOT EXISTS rider_pickup_alert_order_idx
    ON rider_pickup_alert (order_number);
```

`phase` has no `DEFAULT`: every writer is the seeding INSERT, which always names
it, and omitting the default means a future caller that forgets `phase` fails
loudly instead of silently landing in the awaiting-pickup bucket.

`ON DELETE CASCADE` earns its place: `cleanup_delivery_order`
(`cleanupDeliveryOrder.sql:62`), `dispatch_cancel_before_pickup`
(`dispatch_cancel_before_pickup.sql:79`) and the test-reset scripts all
`DELETE FROM delivery_dispatch`, so the ledger cleans itself up. Rows for
completed deliveries are deliberately kept as the audit trail.

### 2. Config — both keys in one statement

```sql
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS', '-15,-5,2,5,7',
   'Signed minutes around delivery_summary.pickup_time at which to alert a rider who has not yet collected; negative = before pickup. Blank disables awaiting-pickup alerts.'),
  ('ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS', '30,45',
   'Minutes after delivery_summary.pickup_time at which to chase a rider who has collected but not delivered. Blank disables in-transit alerts.')
ON CONFLICT (config_key) DO NOTHING;
```

Each key is an independent kill switch: blank the delivery key and only the
in-transit phase stops.

### 3. `job_rider_pickup_alerts()` — parameterise by phase

**(a) Parse both keys.** Factor the existing parse into a helper so it is not
written twice:

```sql
CREATE OR REPLACE FUNCTION parse_alert_offsets(p_config_key text)
RETURNS int[] LANGUAGE sql STABLE AS $$
    SELECT array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
      FROM ordelo_config c
     CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t(x)
     WHERE c.config_key = p_config_key
       AND btrim(t.x) ~ '^-?\d+$';
$$;
```

Bail only when **both** come back `NULL`.

The helper collapses three cases to `NULL` — key absent, key blank, key present
but all-garbage — which is right for seeding but loses v1's diagnostic. Keep a
`RAISE NOTICE` per phase in the caller when a key *exists* but yields no
offsets, naming the offending value. That is the message ops will want the first
time a rider doesn't get alerted.

**(b) Seed** — one INSERT covering both phases, driven by a phase table:

```sql
-- Plain CROSS JOIN, not LATERAL: the VALUES list depends on plpgsql variables,
-- not on the row to its left, so there is no lateral dependency to express.
-- Cast the literals so ph.gate_status meets dd.status as varchar rather than text.
CROSS JOIN (VALUES
    ('awaiting_pickup'::varchar, 'assigned'::varchar, v_pickup_offsets),
    ('picked_up'::varchar,       'pickedup'::varchar, v_delivery_offsets)
) AS ph(phase, gate_status, offsets)
CROSS JOIN unnest(ph.offsets) AS k(offset_minutes)
WHERE dd.status = ph.gate_status
  AND ds.pickup_time IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM rider_pickup_alert a
                   WHERE a.dispatch_id = di.dispatch_id
                     AND a.phase       = ph.phase)
```

`NOT EXISTS` is now scoped **per phase**, which is what makes in-transit
checkpoints seed lazily at the moment the dispatch flips to `pickedup` — and
preserves snapshot semantics within each phase. A `NULL` offsets array makes
`unnest` yield no rows, so a blank config seeds nothing for that phase.

**(c) Rank** — join the same phase VALUES list so each row is gated on its own
phase's dispatch status; carry `a.phase` into the payload. Partition by
`a.dispatch_id` only.

**(d) POST** — unchanged; payload items gain `"phase"`.

**(e) Mark** — unchanged, except both `UPDATE`s must match on `phase` as well as
`(dispatch_id, offset_minutes)` now that it is part of the key. **Supersede
first** — the existing ordering comment still applies.

### 4. Reschedule trigger — no change

It updates every row for the `order_number`, and both phases hang off the same
`pickup_time`, so it already re-times and reopens both.

Note what this means for checkpoints the rider has moved past: an
`awaiting_pickup` row still `pending` when the rider collects stays `pending`
forever, and a later `pickup_time` adjustment reopens it along with everything
else. **The phase gate is what keeps it inert** — the dispatch is now
`pickedup`, so that row can never match `dd.status = 'assigned'` again. This is
by design, not accident; the rows are also a useful record of which warnings
were never needed.

## Python changes *(new)*

### `watomation/routers/delivery_hooks.py` — the phase-aware gate

This is the one place a naive extension would silently break: the current gate
requires `DeliveryProgress.AWAITING_PICKUP`, which would reject **every**
in-transit alert. Because phase names are `DeliveryProgress` values it becomes:

```python
try:
    required = DeliveryProgress(alert.get("phase", DeliveryProgress.AWAITING_PICKUP))
except ValueError:
    logger.error(...)      # unknown phase from SQL -> skip, do not guess
    continue

progress, _row = await check_delivery_progress(order_number=order_number)
if progress is not required:
    ...skip...
```

Default to `AWAITING_PICKUP` when `phase` is absent, so a v1 payload still works
if the app is deployed ahead of the migration. Pass `pickup_alert_phase` through
in `state_update_dict` alongside `pickup_alert_offset`.

### `ordelo/agents/rider_agent.py`

- `AgentState`: add `pickup_alert_phase: str` (primitive, so still SQL-readable).
- `notify_pickup_reminder`: add the in-transit branch. The existing two branches
  are unchanged, and the delta is still computed from `pickup_time`, not the
  offset.
  - `picked_up` → `🛵 {rider_name}, you collected order *{order_number}* — it's now about {n} min past the pickup time ({time}). Please get it to the customer as soon as you can.`
- Clear `pickup_alert_phase` alongside `pickup_alert_offset` when the tool
  completes, so a later unrelated turn cannot re-fire with a stale phase.

### `ordelo/agents/rider_agent_prompt.md`

Extend the `notify_pickup_reminder` entry: it now covers both "go collect" and
"finish the delivery" reminders, still **only** on a system-message cue.

### Docs

- `CONTEXT.md` — extend the **Pickup alert** entry with the two phases and the
  shared anchor.
- `docs/delivery_process.md` — add the second config key and the `phase` field
  to the documented payload.

## Tests *(new)*

Extending the suites written last change:

- `tests/watomation/routers/test_delivery_hooks.py`
  - in-transit alert runs the agent when progress is `PICKED_UP`
  - in-transit alert is **skipped** when progress is `AWAITING_PICKUP` — the
    inverse of the existing case, and the regression test for the gate
  - awaiting-pickup alert still skipped when `PICKED_UP` *(exists)*
  - unknown `phase` string skips rather than guessing
  - missing `phase` defaults to awaiting-pickup
  - `state_update_dict` carries both offset and phase
- `tests/ordelo/agents/test_rider_agent.py`
  - in-transit wording, driven by the real delta
  - phase cleared alongside offset on completion
  - keep test times off `.5` rounding boundaries (the existing `_pickup_time_in`
    docstring explains why)

## Verification

*The user runs all SQL manually; I execute none of it.*

1. `uvx ruff check` on the changed files (expect no new findings) and
   `uv run pytest`. Note
   `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`
   already fails on a clean tree — unrelated.
2. Apply `add_rider_pickup_alerts.sql` — a first-time install, nothing to
   upgrade. **Run it twice** to confirm it is re-runnable: it must succeed both
   times and leave the ledger unchanged on the second run. Then check both
   config keys landed:
   `SELECT config_key, config_value FROM ordelo_config WHERE config_key LIKE 'ORDELO_APP_RIDER_%_ALERT_INTERVALS';`
3. Awaiting-pickup phase — walk the numbered steps in the file's trailing
   comment block (4-minutes-to-pickup fires `-5` with `-15` superseded, re-run
   is silent, past-pickup fires the next one, reschedule works both directions,
   kill switch returns `false`).
4. In-transit phase, on a test dispatch. **Blank
   `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` for the duration of this step** so
   awaiting-pickup checkpoints cannot fire mid-run and muddy the trace (step 6
   proves that isolation works); restore it afterwards.
   - set `pickup_time = now() - interval '20 minutes'` and drive the dispatch to
     `pickedup` by verifying the restaurant code through the agent, so
     `status_update_dtts` is set the real way
   - `SELECT job_rider_pickup_alerts();` → **no** alert yet (`30` not due)
   - set `pickup_time = now() - interval '32 minutes'`, re-run → one alert
     worded "about 32 min past the pickup time"; the `picked_up` row for `30` is
     `sent`, `45` is `pending`
   - re-run immediately → no second message
5. Late-collection case the anchor decision accepted: with `pickup_time` 50
   minutes ago and the dispatch newly `pickedup`, one run fires **once** (offset
   `45`, with `30` superseded) and nothing after.
6. Phase isolation: blank `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` and
   confirm awaiting-pickup alerts still fire; blank the pickup key and confirm
   the reverse.
7. Confirm no POST at all when nothing is due in either phase.
8. Only then (re)register the cron:
   `SELECT cron.schedule('job_rider_pickup_alerts', '*/2 * * * *', $$SELECT job_rider_pickup_alerts()$$);`
