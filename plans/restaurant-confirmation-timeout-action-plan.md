# Restaurant confirmation timeout: auto-decline, longer window, more alerts, customer countdown (plan)

**Follow-up reversal (17 Nov 2026):** [Kitchen start signal](kitchen-start-signal-plan.md) restores the no-rider notice to restaurant admins on both channels for every delivery, including configured auto-accept; overwatch remains notified. ADR 0015 records the decision.

Status: **implemented and committed on `feature/restaurant-default-timeout` (16 Nov 2026); the owner has applied the migration; tests written but not yet run in CI/locally. Follow-ups after the STRK manual test: TEST3100 test orders skip the payment cancel; the cancelled order page says the payment was never collected; the delivery stepper is Looking for a rider → Rider assigned → Preparing; "No rider found" now goes to overwatch only (the restaurant-admin notice is commented out). 17 Nov: an order an admin accepted but gave no pickup time is auto-accepted 15 seconds after the accept (fixed constant `c_pickup_grace`, no config key; `migrations/restaurant_accept_pickup_grace.sql`, owner applies).** Written 16 Nov 2026 after a grilling session with the owner (section 1).
Repos and branches (already checked out):

- OrdeloAgent, branch `feature/restaurant-default-timeout`, written against commit `b05ce6d`. The branch has uncommitted
  doc edits in `docs/delivery_process.md` and `docs/pickup_time_logic.md`; build on them, do not revert them.
- restaurant-frontend, branch `feature/waiting-on-restaurant`, written against commit `1fe4351`.
- restaurant-agents: **no change.**

**The owner applies all SQL himself. Do not run migrations or config SQL against the shared database.**
The SQL in 4.1, 4.2 and the insert in 4.6 was run on a scratch Postgres 16 (cut-down tables) and gave the expected
rows: decline + unanswered → `auto_decline` / `declined`; decline + accepted → `restaurant_timedout`; no key → `restaurant_timedout`.
All Python and TypeScript in this plan is unrun.

Read first: `CLAUDE.md` (RPC pattern, cross-references), `agents.md` "ordelo_datamodels SQL standard", `CONTEXT.md`
(Configured auto-accept, Timeout auto-accept, Order-card reminders), `docs/pickup_time_logic.md`,
`docs/live-order-test-harness.md`, `ordelo_datamodels/telegram/t_order_alerts.sql`.

---

## 0. What we are building, in one paragraph

Today an order nobody answers is **always auto-accepted** when the confirmation timeout passes, at every restaurant.
We add a per-restaurant setting, `{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION` (`accept` | `decline`, default `accept`).
With `decline`, an order that no admin answered is **auto-declined**: it becomes terminal, the payment is released, the
customer is told, the admins get one notice and overwatch gets one alert. The four web restaurants (STRK, CRDO, CRMS,
BNAT) get `decline`, a **3-minute** timeout and Telegram order-card reminders spread over the whole 3 minutes. The rider
search clock now starts when the order becomes dispatchable, not when it was created. The customer's tracking page shows
a countdown while it waits for a decline-mode restaurant.

The whole feature rests on one sentence, which the docs must state the same way everywhere:

> **`auto_accept` decides whether anyone is asked. `TIMEOUT_ACTION` decides what silence means.**

## 1. Decisions (owner, 16 Nov 2026)

| # | Decision | Answer |
|---|---|---|
| D1 | Setting | New key `{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION` = `accept` \| `decline`. Missing, blank or anything else = `accept`. **No global key** (a global `decline` would silently flip WhatsApp restaurants) |
| D2 | What is declined | Only orders still `restaurant_unconfirmed`. An order an admin **accepted but gave no pickup time** still auto-accepts with the default pickup time, in both modes |
| D3 | Rider clock | `process_delivery()` measures `DELIVERY_TIMEOUT_TIME` from when the order became dispatchable (`restaurant_update_dtts`), not from creation. Applies to every restaurant |
| D4 | Timeout | 3 minutes for the decline restaurants |
| D5 | Telegram reminders | `0,15,30,45,60,90,120,150,170` seconds (9 sends; the last is 10 s before the deadline) |
| D6 | WhatsApp admins | Unchanged: one prompt, no repeats, Decline button stays commented out |
| D7 | Auto-decline notices | Admins on WhatsApp and Telegram (one notice, card flips to "Auto-declined") **and** one overwatch alert |
| D8 | Countdown | Only for decline-mode restaurants. Timeout-accept restaurants keep today's text |
| D9 | Rollout | STRK, CRDO, CRMS and BNAT in the same config SQL |
| D10 | Design depth | SQL decides the timeout outcome. Decline is written atomically in SQL. **The timeout-accept path (`restaurant_timedout` → Python → `auto_accept`) is not touched** |
| D11 | Out of scope | Restructuring `ordelo_config`; WhatsApp reminders; overwatch warning before the decline; moving timeout-accept into SQL; the unused `job_restaurant_confirmation_timeout()` |

## 2. Facts this design depends on (verified in code)

| Fact | Where | Why it matters |
|---|---|---|
| The timeout job marks orders `restaurant_timedout` when `rcs IN ('restaurant_unconfirmed','restaurant_accept') AND pickup_time IS NULL` and age since `dtts` exceeds `{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` → global → 5 | `ordelo_datamodels/restaurant_admin/process_restaurant_confirmation.sql` | The one place the outcome is decided. Cron every 10 s |
| Python then always auto-accepts | `watomation/routers/delivery_hooks.py` `_handle_restaurant_timedout` (line 1514); `watomation/routers/takeaway_hooks.py` `_handle_restaurant_timedout` (line 290) | Left as is (D10) |
| `auto_decline` is already allowed by both CHECK constraints but **nothing writes it** | `delivery/delivery_summary.sql` line 183; `takeaway/takeaway_summary.sql` line 97 | No constraint change needed |
| The restaurant triggers do **not** fire for `auto_decline` | `delivery_summary.sql` trigger `trigger_restaurant_updates` (line 201) and the `IF ... IN (...)` inside `restaurant_updates_whook()` (line 268); `takeaway_summary.sql` trigger (line 245) and `IF` (line 151) | Both the `WHEN` list and the inner `IF` need `auto_decline` |
| A manual decline sets `status = 'declined'` in the same UPDATE as the decision | `restaurant_admin/restaurant_order_decision.sql` `restaurant_order_decide()` | Auto-decline does the same, so the order is never dispatchable |
| A late tap after the timeout answers `already_decided` | `restaurant_order_decide()` only updates `restaurant_unconfirmed` rows; `tests/sql/test_restaurant_decision_sql.py::test_decide_after_timeout_is_already_decided` | No new race handling |
| The decline handlers already cancel the payment, queue a web release and tell the customer | `delivery_hooks._handle_restaurant_decline` (line 1426); `takeaway_hooks._handle_restaurant_decline` (line 225) | Reused for auto-decline |
| The delivery decline handler's guarded update only matches `rcs = 'restaurant_decline'` | `delivery_hooks.py` lines 1446-1455 | It is a no-op for `auto_decline` (SQL already set `declined`). Leave it |
| `delivery_hooks.restaurant_confirmation_flow` returns an error for **every** trigger reason when the restaurant has no admins | `delivery_hooks.py` lines 1679-1688 | An auto-decline must still refund the customer when `admins` is empty. Takeaway already limits the check to `restaurant_unconfirmed` / `restaurant_accept` (`takeaway_hooks.py` line 372) |
| The Telegram card maps `auto_decline` to `declined`, but `Card.from_snapshot` needs a decider for `declined`; without one it logs "incomplete snapshot" and **draws the awaiting card with live buttons** | `telegram/t_order_alerts.sql` `t_order_card_status()` (line 162); `channels/telegram/rest_admin/order_cards/model.py` lines 165, 236-245 | Auto-decline needs its own card status `auto_declined` |
| Reminders are seeded only for `restaurant_unconfirmed` orders younger than 15 min and cancelled the moment the order is no longer unconfirmed | `t_order_alerts.sql` `job_t_order_alerts()` SEED / CANCEL (lines 580-642) | Works unchanged for a 3-minute window; offsets past the deadline never fire |
| Per-restaurant offsets win over the global ones | `t_order_alerts.sql` line 615 (`parse_alert_offsets(rest_ref \|\| '_TGRAM_ORDER_ALERT_OFFSETS_SECS')`) | Config only |
| The rider timeout uses `COALESCE(ds.redispatch_dtts, ds.dtts)` | `delivery/process_delivery.sql` (`update_summary` CTE) | D3 changes this one expression |
| `restaurant_update_dtts` is set: at creation for configured auto-accept (`init_delivery.sql` line 184); when the pickup time is chosen (`restaurant_order_decision.sql` lines 273/285); when the timeout job fires (`process_restaurant_confirmation.sql` line 55). The +10/+20 adjustment also overwrites it (`restaurant_ready_adjust_notices.sql` line 316) but only on orders that already have a rider | as listed | It is a correct "became dispatchable" time for every `unassigned` order |
| Configured auto-accept suppresses the "No Rider Found" admin message through `rest_confirmation_method = 'configured_auto'` | `delivery_hooks.py` line 836 | Documented in section 8, not changed |
| The order view derives `waiting_for_restaurant`; it returns no deadline | `utils_common/web_ordering/customer_order_view.py` `derive()` / `get_view()` | New optional field |
| Both the Ordelo endpoint and the Next route build the ETag from the whole view | `watomation/routers/web_hooks.py` line 147; `restaurant-frontend/app/api/web/orders/[orderNumber]/route.ts` | The new field must not change between polls: an absolute `deadline_at`, **never** `server_time` or `seconds_left` |
| A web order's summary row is created after Stripe authorises, with `dtts = CURRENT_TIMESTAMP` | `web_checkout.py` line 371 comment; `init_delivery.sql` line 107 | The clock the customer sees starts after payment |
| The page polls every 15 s when visible, 60 s hidden | `restaurant-frontend/components/order-status/OrderPage.tsx` | The countdown must trigger its own poll at the deadline |

## 3. Design

### 3.1 The modules

```
ordelo_config ──► restaurant_confirmation_policy(rest_ref)        NEW, the only reader of the two keys
                    │  (timeout_minutes, timeout_action)
        ┌───────────┴────────────┐
        ▼                        ▼
process_restaurant_confirmation()   customer_order_view.get_view()
  unanswered + decline → auto_decline + declined     → view.confirmation.deadline_at
  everything else      → restaurant_timedout (as today)
        │ trigger (reason = NEW.restaurant_confirmation_status)
        ▼
restaurant_confirmation_flow()  (delivery_hooks / takeaway_hooks)
  restaurant_timedout → _handle_restaurant_timedout        unchanged
  auto_decline        → _handle_restaurant_decline(timed_out=True)   existing handler + AutoDeclined notice + ops alert
```

Why this shape (terms from the codebase-design vocabulary):

- **One deep module for the policy.** `restaurant_confirmation_policy()` has a two-column interface and hides the key
  names, the fallback chain, the default and the validation. Its two callers (the cron job and the order view) cannot
  disagree, so the deadline the customer sees is the deadline that is enforced (**locality**). Today the lookup is
  copy-pasted twice inside the job.
- **The seam for the outcome stays where it already is:** the `restaurant_confirmation_status` value written by SQL.
  Python reads the trigger reason and performs side effects. No new seam, no Python branch on config.
- **No new Python wrapper module.** The policy has one Python caller, and `customer_order_view` already reads the
  database through `web_ordering.common.one()`. A wrapper would be a pass-through (it fails the deletion test).
- **Decline reuses the existing decline handlers** instead of a third handler per router: the customer-facing work is
  identical, only the admin notice differs.

### 3.2 State changes

```
restaurant_unconfirmed ──tap──► restaurant_accept ──pickup──► (pickup_time set, 'unassigned' / 'pickup_confirmed')
        │                             │
        │ timeout, action = accept    │ timeout (either action)
        ├────────────────────────────►┴──► restaurant_timedout ──Python──► auto_accept + default pickup time
        │
        │ timeout, action = decline
        └──► auto_decline + status 'declined'   (terminal; payment released; customer, admins, overwatch told)
```

## 4. Database changes (OrdeloAgent)

Each owner file below is edited so it shows the new live shape (SQL standard rule 2), **and** all statements are also
collected in one runnable file for the owner: `ordelo_datamodels/migrations/restaurant_confirmation_timeout_action.sql`
(header `-- MIGRATION (history; do not edit the statements below)`, sections `Applied to live`, `Current definitions now
live in`, `Purpose`). Format with `python scripts/datamodels/format_sql.py`; rebuild the guide with
`python scripts/datamodels/build_guide.py`.

### 4.1 NEW `ordelo_datamodels/restaurant_admin/restaurant_confirmation_policy.sql`

Standard 13-section header. `CALLED BY`: sql `process_restaurant_confirmation()`; python
`utils_common/web_ordering/customer_order_view.py: get_view()`. `TESTS`: `tests/sql/test_restaurant_confirmation_timeout_sql.py`.

```sql
-- function restaurant_confirmation_policy(p_rest_ref text) -> (timeout_minutes numeric, timeout_action text)
--   What silence means for one restaurant: how long admins have to answer, and what happens if nobody does.
--   timeout_minutes: <REF>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else 5.
--   timeout_action : 'decline' only when <REF>_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION is 'decline' (any case, trimmed);
--                    everything else, including a missing key, is 'accept'. There is deliberately NO global action key.
--   Always returns exactly one row. Reads ordelo_config. Not consulted for configured auto-accept restaurants
--   (restaurant_master.auto_accept): their orders are never unconfirmed.
CREATE OR REPLACE FUNCTION public.restaurant_confirmation_policy (p_rest_ref text, OUT timeout_minutes numeric, OUT timeout_action text)
    LANGUAGE sql
    STABLE
    AS $$
    SELECT
        COALESCE((
            SELECT config_value::numeric FROM public.ordelo_config
            WHERE config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (
            SELECT config_value::numeric FROM public.ordelo_config
            WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5),
        CASE WHEN lower(btrim(COALESCE((
            SELECT config_value FROM public.ordelo_config
            WHERE config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION' LIMIT 1), ''))) = 'decline' THEN
            'decline'
        ELSE
            'accept'
        END
$$;

COMMENT ON FUNCTION public.restaurant_confirmation_policy (text) IS 'Confirmation timeout policy for one restaurant: minutes to answer and what silence means (accept | decline).';
```

Notes for the implementer:

- OUT parameters (not `RETURNS TABLE`) so callers can write `(public.restaurant_confirmation_policy(x)).timeout_action`
  inside an `UPDATE ... SET`, where a LATERAL join to the target table is not allowed.
- The numeric cast keeps today's behaviour (a non-numeric timeout value raises, as it does now). Do not "improve" it here.
- Grants: copy what `resolve_initial_restaurant_acceptance.sql` does. The callers are pg_cron and the app's psycopg
  pool (`config/pg_setting.py`), not the anon REST client. Before choosing `REVOKE ... FROM PUBLIC, anon, authenticated`,
  check which role the pool connects as; if it is not the owner or `service_role`, add the matching `GRANT EXECUTE`.

### 4.2 `ordelo_datamodels/restaurant_admin/process_restaurant_confirmation.sql`

Replace the function body. The two inline `COALESCE((SELECT ... ), (SELECT ...), 5)` blocks go away.

```sql
CREATE OR REPLACE FUNCTION process_restaurant_confirmation ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH delivery_timedout_confirmations AS (
        UPDATE
            delivery_summary ds
        SET
            -- Never answered + the restaurant declines on silence -> terminal decline, in this same UPDATE.
            -- Everything else (timeout action 'accept', or an admin accepted but chose no pickup time) -> as before.
            restaurant_confirmation_status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
                AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
                'auto_decline'
            ELSE
                'restaurant_timedout'
            END,
            status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
                AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
                'declined'
            ELSE
                ds.status
            END,
            restaurant_update_dtts = NOW()
        WHERE
            ds.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
            AND ds.pickup_time IS NULL
            AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_minutes
        RETURNING
            'Delivery order ' || ds.order_number || ' (' || ds.rest_ref || ') → restaurant_confirmation_status set to ' || ds.restaurant_confirmation_status AS action
),
takeaway_timedout_confirmations AS (
    -- identical, on takeaway_summary ts, message prefix 'Takeaway order '
    ...
)
SELECT dc.action FROM delivery_timedout_confirmations dc
UNION ALL
SELECT tc.action FROM takeaway_timedout_confirmations tc;
END;
$$;
```

- In `SET`, `ds.restaurant_confirmation_status` is the **old** value, so the CASE is correct. If a tap commits first, the
  row no longer passes the `WHERE` (Postgres re-checks it after the row lock), exactly like today.
- Keep the `cron.schedule('process_restaurant_confirmation', '10 seconds', ...)` line and the `COMMENT ON` (reword it:
  "... 'restaurant_timedout', or 'auto_decline' + status 'declined' where the restaurant declines on silence ...").
- Header: update `OBJECTS`, `REQUIRES` (`restaurant_admin/restaurant_confirmation_policy.sql`), `SIDE EFFECTS`,
  `HOW IT FITS`, `LIFECYCLE`, `TESTS`, `SEE ALSO`.

### 4.3 Triggers: let `auto_decline` reach Python

`ordelo_datamodels/delivery/delivery_summary.sql`

```diff
 CREATE TRIGGER trigger_restaurant_updates
     AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON delivery_summary
     FOR EACH ROW
-    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'restaurant_pickuptime_adjusted'::character varying]::text[]))
+    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_decline'::character varying, 'restaurant_pickuptime_adjusted'::character varying]::text[]))
     EXECUTE FUNCTION restaurant_updates_whook ();
```

and inside `restaurant_updates_whook()` (line 268):

```diff
-        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'restaurant_pickuptime_adjusted') THEN
+        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'auto_decline', 'restaurant_pickuptime_adjusted') THEN
```

`ordelo_datamodels/takeaway/takeaway_summary.sql`: the same two edits on `trigger_takeaway_restaurant_updates` (line 245)
and the `IF` in `takeaway_restaurant_updates_whook()` (line 151). Update both files' `LIFECYCLE` header lines
(`... | restaurant_timedout | auto_decline (timeout, restaurants that decline on silence)`), the "for the five statuses"
comment above the delivery trigger, and the phase-2 line in `HOW IT FITS`.

`auto_accept` stays **out** of both lists on purpose: configured auto-accept inserts must not call the confirmation webhook.

### 4.4 `ordelo_datamodels/delivery/process_delivery.sql` (rider clock, D3)

```diff
-        AND (EXTRACT(EPOCH FROM (NOW() - COALESCE(ds.redispatch_dtts, ds.dtts))) / 60) > COALESCE((
+        -- Clock starts when the order became dispatchable: last pre-pickup cancellation, else the restaurant's
+        -- decision / timeout (restaurant_update_dtts), else creation. The time admins took to answer is not counted.
+        AND (EXTRACT(EPOCH FROM (NOW() - COALESCE(ds.redispatch_dtts, ds.restaurant_update_dtts, ds.dtts))) / 60) > COALESCE((
```

Update the header `LIFECYCLE` / `GOTCHAS` and the comment on `redispatch_dtts` in `delivery_summary.sql` (lines 167-171).
Effect on existing restaurants: riders get the full `DELIVERY_TIMEOUT_TIME` after acceptance, so "No Rider Found" can
arrive later than today by however long the restaurant took to answer. No config value changes.

### 4.5 `ordelo_datamodels/telegram/t_order_alerts.sql` (card status)

```diff
-        WHEN p_rcs IN ('restaurant_decline', 'auto_decline') THEN
+        WHEN p_rcs = 'restaurant_decline' THEN
             'declined'
+        WHEN p_rcs = 'auto_decline' THEN
+            'auto_declined'
```

Update every list of status keys in that file (lines 9, 53, 145, the `COMMENT ON FUNCTION` at 753):
`awaiting | accepted | pickup_set | declined | auto_accepted | auto_declined | gone`. `t_order_cards_stale()` compares the
drawn status with the current one, so existing copies redraw on the next 5-second sweep without further change; confirm
that by reading it, and check `telegram/t_sent_messages.sql` for any hard-coded status list.

### 4.6 Config SQL (owner runs after the code is deployed)

NEW `notebooks/db_queries/restaurant_queries/confirmation_timeout_action_rollout.sql`:

```sql
-- 0. Preflight (read only). Expect auto_accept = false and at least one Telegram destination per restaurant.
SELECT rm.rest_ref, rm.auto_accept, cardinality(rm.admins) AS wa_admins,
       (SELECT count(*) FROM public.t_alert_destinations ('rest_admin', rm.rest_ref)) AS telegram_chats,   -- bot key: use REST_ADMIN_BOT_KEY's value
       p.timeout_minutes, p.timeout_action
FROM public.restaurant_master rm, public.restaurant_confirmation_policy (rm.rest_ref::text) p
WHERE rm.rest_ref IN ('STRK', 'CRDO', 'CRMS', 'BNAT');

SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key ~ '^(STRK|CRDO|CRMS|BNAT)_(RESTAURANT_CONFIRMATION_TIMEOUT_(TIME|ACTION)|TGRAM_ORDER_ALERT_OFFSETS_SECS|DELIVERY_TIMEOUT_TIME)$'
ORDER BY 1;   -- keep this output: it is the rollback

-- 1. Apply.
INSERT INTO public.ordelo_config (config_key, config_value, description)
SELECT r || k.suffix, k.val, k.descr
FROM unnest(ARRAY['STRK', 'CRDO', 'CRMS', 'BNAT']) AS r,
     (VALUES
        ('_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '3', 'Minutes admins have to answer a new order before the timeout action applies; checked every 10 seconds'),
        ('_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION', 'decline', 'What silence means at the confirmation timeout: accept (default, auto-accept with the default pickup time) or decline (order cancelled, payment released). Orders an admin accepted without a pickup time always auto-accept'),
        ('_TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45,60,90,120,150,170', 'Seconds after a new order at which the Telegram order card is (re)sent while unanswered; must end before the confirmation timeout')
     ) AS k (suffix, val, descr)
ON CONFLICT (config_key) DO UPDATE
    SET config_value = EXCLUDED.config_value, description = EXCLUDED.description, updated_at = now();

-- 2. Verify: rerun query 0. Expect timeout_minutes 3, timeout_action decline.
-- Rollback (instant, no deploy): DELETE the four *_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION rows (owner approval needed for a
-- DELETE), or UPDATE them to 'accept'.
```

`{REF}_DELIVERY_TIMEOUT_TIME` is deliberately left alone (D3 makes it independent of the confirmation timeout).
BNAT: confirm with the owner that its admins are linked on Telegram before running; a decline-mode restaurant with only
WhatsApp admins gets one prompt and no way to decline other than the timeout.

Also update the onboarding bundles so new web-only restaurants start right: add the two keys to
`notebooks/db_queries/restaurant_queries/onboarding_new_restaurant.sql`, the `onboarding_crdo` / `onboarding_crms` /
`onboarding_strk` `02_ordelo_config_*_keys.sql` files, and the key table in `docs/onboarding-web-only-restaurant.md`.

## 5. Python changes (OrdeloAgent)

### 5.1 `utils_common/notify/restaurant_notifier.py`: new notice `AutoDeclined`

```python
@dataclass(frozen=True)
class AutoDeclined:
    """Nobody answered in time at a restaurant that declines on silence: the order was auto-declined."""

    order_number: str
    order_type: Literal["delivery", "takeaway"]
    admins: list[str]
    rest_ref: str


Notice = KitchenReceipt | TakeawayReceipt | AutoAccepted | AutoDeclined | RiderAlert | DeliveryCompleted | Feedback
```

WhatsApp adapter (after the `AutoAccepted` branch):

```python
        elif isinstance(notice, AutoDeclined):
            await wa_senders.admin_auto_decline_notice(notice.admins, notice.order_number)
```

Telegram adapter:

```python
        elif isinstance(notice, AutoDeclined):
            text = (
                f"⏱ <b>{escape(notice.order_number)}</b> auto-declined (no answer in time). "
                "The customer has been told and will not be charged."
            )
            await self._notices_for_bot().send(
                notice.rest_ref, text, notice="auto_declined",
                order=OrderRef(notice.order_number, notice.order_type), reply_to="card",
            )
```

Update the module docstring (notice list, mapping table, callers). `notice=` is a free string in
`channels/telegram/rest_admin/notices.py`; confirm `t_sent_messages` has no CHECK on it.

### 5.2 `utils_common/waba_utils/wa_senders.py`

Next to `admin_auto_accept_notice` (line 152), same shape, and add it to the module docstring list:

```python
async def admin_auto_decline_notice(admins: List[str], order_number: str) -> None:
    """Tell each admin an order was auto-declined because nobody answered in time (delivery and takeaway).

    One admin at a time: a bad contact is logged and never costs the others their message."""
    text = (
        f"Order {order_number} auto-declined: no response before the confirmation timeout. "
        "The customer has been told and will not be charged."
    )
    for admin in admins:
        try:
            await _async_wa_client.send_message(to=admin, text=text)
        except Exception as e:
            logger.error(f"Auto-decline notice for {order_number} failed for admin {admin}: {e}")
```

### 5.3 `watomation/routers/delivery_hooks.py`

Imports: add `AutoDeclined` to the `restaurant_notifier` import (line 87) and
`from channels.telegram.ops_alerts import alert_ops`.

`_handle_restaurant_decline` (line 1426): new optional arguments, and one block before the final `return`.

```diff
 async def _handle_restaurant_decline(
     delivery_summary: DeliverySummaryData,
     food_order: FoodOrder,
+    restaurant_admins: Optional[List[str]] = None,
+    timed_out: bool = False,
 ) -> dict:
```

```python
    if timed_out:
        # Auto-decline (restaurant_confirmation_policy 'decline'): SQL already made the order terminal. Admins and
        # overwatch are told AFTER the customer work, so a failed send cannot stop the refund.
        rest_ref = delivery_summary.rest_ref or order_number.split("-")[0]
        await restaurant_notifier.notify(AutoDeclined(order_number, "delivery", restaurant_admins or [], rest_ref))
        await alert_ops(
            f"⏱ {order_number} auto-declined: {delivery_summary.rest_name} did not answer in time. "
            f"Customer told; payment {'cancelled' if cancel_result is not None else 'not cancelled here (pay at restaurant or release queued)'}."
        )
```

Return `"action": "auto_declined" if timed_out else "declined"`. Docstring: say the handler serves `restaurant_decline`
and `auto_decline`, and that the guarded update is a no-op for `auto_decline`.

`restaurant_confirmation_flow` (line 1633):

```diff
-        # Validate admin contacts exist
-        if not restaurant_master.admins or len(restaurant_master.admins) == 0:
+        # Admin contacts are only required where admins are prompted. A decline or timeout must still be processed
+        # (customer told, payment released) for a restaurant with no admins. Same rule as takeaway_hooks.
+        if trigger_reason in {"restaurant_unconfirmed", "restaurant_accept"} and not restaurant_master.admins:
```

```diff
-        elif trigger_reason == "restaurant_decline":
+        elif trigger_reason in ("restaurant_decline", "auto_decline"):
             background_tasks.add_task(
-                _handle_restaurant_decline, delivery_summary, food_order
+                _handle_restaurant_decline, delivery_summary, food_order,
+                restaurant_master.admins or [], trigger_reason == "auto_decline",
             )
         elif trigger_reason == "restaurant_timedout":
             background_tasks.add_task(
-                _handle_restaurant_timedout, delivery_summary, restaurant_master.admins
+                _handle_restaurant_timedout, delivery_summary, restaurant_master.admins or []
             )
```

The relaxed admin check is a small behaviour fix for `restaurant_timedout` too (today an order of a restaurant with no
admins stays `restaurant_timedout` forever). Say so in the PR. Update the route docstring (`Handles:` list, payload
`trigger_reason` values) and the module docstring line 55.

### 5.4 `watomation/routers/takeaway_hooks.py`

Same change: `_handle_restaurant_decline(takeaway_summary, food_order, restaurant_admins=None, timed_out=False)`, the
`timed_out` block with `AutoDeclined(food_order.order_number, "takeaway", ...)` and `alert_ops`, and the route:

```diff
-        elif trigger_reason == "restaurant_decline":
+        elif trigger_reason in ("restaurant_decline", "auto_decline"):
             background_tasks.add_task(
                 _handle_restaurant_decline,
                 takeaway_summary,
                 food_order,
+                restaurant_master.admins or [],
+                trigger_reason == "auto_decline",
             )
```

Its handler's unconditional `status = 'declined'` update is harmless (already declined). Update the module docstring.

### 5.5 Telegram order card: `channels/telegram/rest_admin/order_cards/model.py`

```diff
-Status = Literal["awaiting", "accepted", "pickup_set", "declined", "auto_accepted", "gone"]
-TERMINAL: frozenset[str] = frozenset({"pickup_set", "declined", "auto_accepted", "gone"})
+Status = Literal["awaiting", "accepted", "pickup_set", "declined", "auto_accepted", "auto_declined", "gone"]
+TERMINAL: frozenset[str] = frozenset({"pickup_set", "declined", "auto_accepted", "auto_declined", "gone"})
```

```python
@dataclass(frozen=True)
class AutoDeclined:
    pass


Event = Reminded | Accepted | Declined | PickupChosen | AutoAccepted | AutoDeclined | Vanished
```

```diff
     "restaurant_decline": "declined",
-    "auto_decline": "declined",
+    "auto_decline": "auto_declined",
```

`Card.apply` (only an awaiting card can be auto-declined, D2):

```python
        if isinstance(event, AutoDeclined) and s == "awaiting":
            return replace(self, status="auto_declined")
```

`Card.from_snapshot`, before the `snap.status != "awaiting"` check:

```python
        if snap.status == "auto_declined":
            return card.apply(AutoDeclined())
```

`_status_line`:

```python
            case "auto_declined":
                return "⏱ Auto-declined (no answer in time)"
```

`toast` (a late tap on an old copy):

```diff
         word = {
             "declined": "declined",
             "auto_accepted": "auto-accepted",
+            "auto_declined": "auto-declined",
         }.get(outcome.status or "", "accepted")
-        return (f"Already {word}" if word == "auto-accepted" else f"Already {word} by {who}"), False
+        return (f"Already {word}" if word.startswith("auto-") else f"Already {word} by {who}"), False
```

`_keyboard` already returns no buttons for any status other than `awaiting` / `accepted`. Then
`grep -rn "auto_accepted" channels/ tests/` and add `auto_declined` wherever statuses are enumerated (store parsing,
test fakes, the status list in the `t_order_alerts.sql` header).

### 5.6 Order view: `utils_common/web_ordering/customer_order_view.py`

In `get_view`, after the `pickup_time` block (around line 178), before `if detail_level == "full":`:

```python
    # Countdown for restaurants that decline on silence (restaurant_confirmation_policy, D8). deadline_at is absolute
    # and constant while the order waits, so the ETag stays stable between polls. Never add "now" or seconds-left here.
    if (
        status == "waiting_for_restaurant"
        and summary.get("restaurant_confirmation_status") == "restaurant_unconfirmed"
        and summary.get("dtts")
    ):
        policy = await one(
            "SELECT timeout_minutes, timeout_action FROM public.restaurant_confirmation_policy(%s)", (rest_ref,)
        )
        if policy and policy.get("timeout_action") == "decline":
            view["confirmation"] = {
                "deadline_at": iso(summary["dtts"] + timedelta(minutes=float(policy["timeout_minutes"]))),
                "on_timeout": "decline",
            }
```

Module docstring: add `restaurant_confirmation_policy (function, ordelo_datamodels/restaurant_admin/restaurant_confirmation_policy.sql): calls (SQL)`
to the `Database objects` block. The field is present at both detail levels (it reveals nothing private).

`derive()` needs no change: SQL sets `summary.status = 'declined'`, so the view is `cancelled` / `restaurant_declined` as
soon as the job runs, before the webhook publishes the customer event.

### 5.7 `utils_common/order_management/restaurant_decision.py`

`describe()` already returns "auto-declined". Change it to `"auto-declined (no answer in time)"` to match the
auto-accept wording, and update its test.

## 6. Frontend changes (restaurant-frontend)

### 6.1 `lib/web/types.ts`

```diff
   pickup_time?: { at: string; is_estimate: boolean; updated: boolean }
+  /** Only while waiting for a restaurant that declines on silence: when the order is auto-declined if nobody answers. */
+  confirmation?: { deadline_at: string; on_timeout: 'decline' }
```

### 6.2 NEW `components/order-status/ConfirmCountdown.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'

/**
 * Time the restaurant has left to accept (decline-on-silence restaurants only). `skewMs` is server time minus
 * browser time, so a wrong phone clock does not move the deadline. Calls onExpired once, a little after zero,
 * because the server-side timeout job runs every 10 seconds.
 */
export default function ConfirmCountdown({ deadlineAt, restaurant, skewMs, onExpired }: { deadlineAt: string; restaurant: string; skewMs: number; onExpired: () => void }) {
  const [left, setLeft] = useState<number | null>(null) // null until mounted: no server/browser mismatch
  useEffect(() => {
    const deadline = new Date(deadlineAt).getTime()
    const tick = () => setLeft(Math.max(0, Math.ceil((deadline - (Date.now() + skewMs)) / 1000)))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [deadlineAt, skewMs])
  const expired = left === 0
  useEffect(() => {
    if (!expired) return
    const timer = setTimeout(onExpired, 4000)
    return () => clearTimeout(timer)
  }, [expired, onExpired])

  if (left === null) return null
  if (expired) return <p className="mt-3 rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-800">Checking with {restaurant}…</p>
  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
  return (
    <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
      <p>
        {restaurant} has{' '}
        <span role="timer" aria-live="off" className="font-semibold tabular-nums">{mmss}</span> left to accept.
      </p>
      <p className="mt-0.5 text-amber-800">If they don’t, your order is cancelled and you won’t be charged.</p>
    </div>
  )
}
```

`aria-live="off"`: a screen reader must not announce every second. The status change itself is already announced by
`OrderPage`'s live region. Check the wording and colours against the page with the `impeccable` skill before merging.

### 6.3 `components/order-status/StatusHeader.tsx`

Add an optional slot and render it under the description:

```diff
-export default function StatusHeader({ view }: { view: CustomerOrderView }) {
+export default function StatusHeader({ view, extra }: { view: CustomerOrderView; extra?: React.ReactNode }) {
 ...
       <p className="mt-1 text-gray-700">{statusDescription(view)}</p>
+      {extra}
```

### 6.4 `components/order-status/OrderPage.tsx`

```diff
-export default function OrderPage({ initial }: { initial: CustomerOrderView }) {
+export default function OrderPage({ initial, serverNow }: { initial: CustomerOrderView; serverNow?: number }) {
```

```tsx
  // Server clock minus browser clock. First guess from the server render, refined from each poll's Date header.
  const [skewMs, setSkewMs] = useState(0)
  useEffect(() => { if (serverNow) setSkewMs(serverNow - Date.now()) }, [serverNow])
  // Bumped when the countdown reaches zero: restarts the poll effect with an immediate poll.
  const [kick, setKick] = useState(0)
  const onCountdownExpired = useCallback(() => setKick((k) => k + 1), [])
```

Inside `poll()`, right after the `fetch` resolves (covers 200 and 304):

```tsx
        const serverDate = response.headers.get('Date')
        if (serverDate) setSkewMs(new Date(serverDate).getTime() - Date.now())
```

Poll effect: first schedule and dependency list.

```diff
-    schedule(interval())
+    schedule(kick > 0 ? 0 : interval())
 ...
-  }, [terminal, view.order_number, view.display_status])
+  }, [terminal, view.order_number, view.display_status, kick])
```

Render:

```diff
-      <StatusHeader view={view} />
+      <StatusHeader
+        view={view}
+        extra={view.display_status === 'waiting_for_restaurant' && view.confirmation ? (
+          <ConfirmCountdown deadlineAt={view.confirmation.deadline_at} restaurant={view.restaurant.name} skewMs={skewMs} onExpired={onCountdownExpired} />
+        ) : null}
+      />
```

If the poll after zero still says `waiting_for_restaurant`, the component keeps showing "Checking with …" and the normal
15-second polling carries on. Import `useCallback` and `ConfirmCountdown`.

### 6.5 `app/(web)/town/[town]/orders/[orderNumber]/page.tsx`

```diff
-  return <OrderPage initial={outcome.view} />
+  return <OrderPage initial={outcome.view} serverNow={Date.now()} />
```

### 6.6 `lib/web/status.ts`

`statusDescription`, `waiting_for_restaurant`: when `view.confirmation` is set return the short
`` `Waiting for ${r} to accept your order.` `` so the sentence does not repeat the countdown box. Otherwise unchanged.

### 6.7 `lib/web/fixtures/index.ts` (line 429)

While the fixture order is `waiting_for_restaurant`, add
`confirmation: { deadline_at: new Date(paidAt + 185_000).toISOString(), on_timeout: 'decline' }` to the returned view so
the countdown can be seen in fixtures mode. Keep it a pure function of `paidAt` (the ETag must stay stable).

Do not touch `tests/goldens/__goldens__` (WhatsApp checkout contract).

## 7. Tests

### 7.1 Offline, OrdeloAgent

| File | Cases |
|---|---|
| NEW `tests/sql/test_restaurant_confirmation_timeout_sql.py` (pattern: `test_restaurant_decision_sql.py`; load the SQL with `sql_path` / `migration_sql` from `tests/sql/conftest.py`, and see how `test_rider_offer_alerts_sql.py` loads a job file that ends in `cron.schedule`) | **Policy:** no keys → `(5, 'accept')`; global timeout key; restaurant key wins; action `decline`, `' DECLINE '`, `Decline` → `decline`; `accept`, blank, `nonsense` → `accept`; a global `RESTAURANT_CONFIRMATION_TIMEOUT_ACTION` row is ignored. **Job, delivery and takeaway (parametrised):** accept mode + unanswered + overdue → `restaurant_timedout`, `status` unchanged; decline mode + unanswered + overdue → `auto_decline`, `status = 'declined'`, `restaurant_update_dtts` set; decline mode + `restaurant_accept` + no pickup → `restaurant_timedout`; not yet due → untouched; pickup time set → untouched; another restaurant's key does not leak. **Trigger:** `trigger_log` (minimal schema) has reason `auto_decline`. **Late tap:** `restaurant_order_decide` after auto-decline → `already_decided`, state `auto_decline` |
| `tests/sql/test_order_cards_sql.py` | `t_order_card_status('auto_decline', NULL)` = `auto_declined`; `restaurant_decline` still `declined`; a drawn `awaiting` copy of an auto-declined order is reported stale |
| NEW `tests/sql/test_process_delivery_timeout_sql.py` | Same order, all vehicle types timed out: not `timedout` while `restaurant_update_dtts` is recent even though `dtts` is old; `timedout` once `restaurant_update_dtts` is older than the timeout; `redispatch_dtts` still wins; NULL `restaurant_update_dtts` falls back to `dtts`. Needs `delivery_option` / `delivery_detail` in the scratch schema; if `minimal_schema.sql` cannot carry them cleanly, say so in the PR and rely on the live check in 7.3 |
| `tests/watomation/routers/test_delivery_hooks.py`, `test_takeaway_hooks.py` | route: `auto_decline` schedules `_handle_restaurant_decline(..., admins, True)`; `restaurant_decline` schedules it with `False`; `auto_decline` and `restaurant_timedout` are processed when `admins` is empty, `restaurant_unconfirmed` still errors. Handler with `timed_out=True`: payment cancel attempted, web customer gets `restaurant_declined` event / WhatsApp customer gets the text, **then** exactly one `AutoDeclined` notice and one `alert_ops` call; `timed_out=False` sends neither. **All existing timed-out and decline tests pass unchanged** |
| notifier tests (find with `grep -rn "AutoAccepted" tests/`) | `AutoDeclined` → `wa_senders.admin_auto_decline_notice(admins, order_number)`; Telegram `Notices.send(..., notice="auto_declined", reply_to="card")`; one channel failing does not stop the other |
| order-card model tests (find with `grep -rn "auto_accepted" tests/`) | snapshot `auto_declined` → terminal card, text "Auto-declined", no keyboard; `AutoDeclined` ignored unless awaiting; toast "Already auto-declined" |
| `tests/utils_common/web_ordering/test_web_contract.py` | `get_view`: waiting + unconfirmed + policy `decline` → `confirmation.deadline_at == dtts + 3 min`; policy `accept` → no field; `restaurant_accept` → no field; policy lookup returns `None` (existing fakes) → no field, no crash; two calls give an identical dict (ETag stable) |
| `tests/sql/test_restaurant_notices_script_sql.py` | new stages listed and run (7.3); scoping test still green |
| `tests/test_datamodels_standard.py` | new file header passes; guide rebuilt |

Run: `pytest`, `ruff check .`, and the SQL tests through the `ordelo-sql-test-db` skill
(`ORDELO_TEST_DB_URI=... pytest tests/sql -q`).

### 7.2 Offline, restaurant-frontend

- NEW `components/order-status/ConfirmCountdown.test.tsx` (Vitest fake timers): shows `2:59`-style time; applies
  `skewMs`; at zero shows "Checking with …" and calls `onExpired` once after 4 s; a deadline already in the past
  renders the checking state immediately.
- NEW `lib/web/status.test.ts`: `statusDescription` with and without `confirmation`.
- `npm test`, `npm run lint`, `npm run build`.

### 7.3 Live, with fake rows (owner's phone is customer, admin and rider; town `dummy`)

Use `ordelo_datamodels/test_support/test_restaurant_notices.sql`; no new test SQL file. Changes to the script (and, in
the same commit, to `tests/sql/test_restaurant_notices_script_sql.py` and `docs/live-order-test-harness.md`):

| Stage | Change | Expect once STRK is `decline` / 3 min |
|---|---|---|
| NEW **1b: SILENCE (read only; run after STAGE 1 instead of tapping)** | Selects `restaurant_confirmation_policy('STRK')`, the order's `t_order_alerts` rows and its summary row. Re-run while waiting | 9 checkpoints at 0…170 s; one live Telegram card with "reminder n of 9"; one WhatsApp prompt, no repeats. After ~3:00-3:10: row `auto_decline` / `declined`; card "⏱ Auto-declined"; auto-decline notice on WhatsApp **and** Telegram (reply to the card); one overwatch line; customer text "could not be accepted"; no dispatch offer; a late Accept tap answers "Already auto-declined" |
| **9** (existing, order 1 hour old, unanswered) | Retitle "TIMEOUT, NEVER ANSWERED (outcome follows STRK's timeout action)"; add the policy to its final SELECT | `decline`: auto-declined on the next sweep, notices as above, no card (older than the 15-minute seed window). With the key removed: auto-accept exactly as before |
| NEW **9b: TIMEOUT, ACCEPTED WITHOUT PICKUP TIME** | Copy of stage 9 with `restaurant_confirmation_status = 'restaurant_accept'`, `restaurant_admin = '447448440754'` | Always **auto-accept** with the default pickup time and the existing auto-accept notice, in both modes. This is the accept-path regression check |

Every INSERT stays `STRK-TEST-%`, town `dummy`, with the `TEST3100` item; the script still never writes `ordelo_config`.

Further live checks:

1. **WhatsApp regression pass** from `docs/live-order-test-harness.md` (stages 1-4, 8): prompt text, Accept, pickup
   buttons, kitchen receipt and takeaway receipt unchanged.
2. **Rider clock:** stage 1, accept at about 2:30, pick a time, run 2b. The offer must stay open for the full
   `STRK_DELIVERY_TIMEOUT_TIME` after acceptance (before this change it would have had about half that).
3. **Countdown, real endpoint:** on `restaurant-test.ordelo.app` place a STRK **web** order whose basket contains the
   `TEST3100` item (test payment mode, `docs/test-orders.md`), and do not answer. Expect the countdown from about 3:00,
   "Checking with …" at zero, then "Order cancelled · Strikers Sports Bar couldn't accept your order" within ~15 s and
   the payment shown as released. Repeat once and accept on Telegram at ~1:00: the countdown disappears on the next poll.
   Repeat with the phone clock set 5 minutes wrong: the countdown is still right.
4. **Timeout-accept restaurant untouched:** `SELECT * FROM restaurant_confirmation_policy('ELAS')` → `accept`, and the
   order view of a waiting ELAS order has no `confirmation` field.

## 8. Documentation

The owner asked for the difference between `auto_accept` and the timeout flow to be unmistakable. Put this table at the
top of `docs/pickup_time_logic.md` under a new heading **"Three confirmation modes"**, and link to it (do not copy it)
from the other docs.

| | **Configured auto-accept** | **Manual, silence = accept** (default) | **Manual, silence = decline** |
|---|---|---|---|
| Switch | `restaurant_master.auto_accept = true` | `auto_accept = false`, no action key (or `accept`) | `auto_accept = false`, `{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION = decline` |
| Question it answers | Is anyone asked? **No** | Asked; silence means **yes** | Asked; silence means **no** |
| Order starts as | `auto_accept`, pickup time set, `rest_confirmation_method = 'configured_auto'`; delivery `unassigned`, takeaway `pickup_confirmed` | `restaurant_unconfirmed` | `restaurant_unconfirmed` |
| Admin prompt (WhatsApp Accept, Telegram card with buttons) | Not sent | Sent | Sent |
| Telegram reminders | None | Until decided or timed out | Until decided or timed out |
| Timeout job | Never involved | → `restaurant_timedout` → Python → `auto_accept` + default pickup time | never answered → `auto_decline` + `declined`; accepted without pickup time → as the default mode |
| Admin notices on the outcome | none (admins get the receipts) | "auto-accepted" notice | "auto-declined" notice + overwatch alert |
| Admin messages it suppresses | confirmation prompt, reminders, and delivery's "No Rider Found" | none | none |
| Customer page | "Preparing" straight away | "Waiting for the restaurant" | "Waiting…" **with countdown**, then preparing or cancelled (payment released) |
| Timeout keys used | none (`{REF}_DEFAULT_*_PICKUP_TIME` only) | `..._TIMEOUT_TIME`, `{REF}_DEFAULT_*_PICKUP_TIME` | `..._TIMEOUT_TIME`, `..._TIMEOUT_ACTION` |

Below it, three short rules: `auto_accept = true` makes the action key irrelevant; the action key has no global form;
an accepted order is never auto-declined.

| File | Change |
|---|---|
| `docs/pickup_time_logic.md` | The table above; section A.3 / B.3 "Timeout path" rewritten around `restaurant_confirmation_policy()`; new A.4b / B.4b "Auto-decline on timeout" |
| `docs/delivery_process.md` | status table row for `auto_decline` (no longer "internal use"); 2b handler table (`auto_decline` → `_handle_restaurant_decline(timed_out=True)`); 2d rewritten (policy function, two outcomes, STRK 3 min); 3a rider clock (`COALESCE(redispatch_dtts, restaurant_update_dtts, dtts)`, replacing the uncommitted "does not start when…" note); state diagram (~line 692 and the Mermaid block ~line 770); config table: new action key row, reworded `DELIVERY_TIMEOUT_TIME` row; file table: new SQL file |
| `CONTEXT.md` | Reword **Timeout auto-accept** ("the default timeout action"); add **Timeout action** and **Timeout auto-decline**; **Order-card reminders**: replace "not about restaurants that decline" with the auto-decline sentence and the STRK offsets |
| `docs/alerts-and-notifications.md` (+ `.html`, `alerts-and-notifications-architecture.json` if they are maintained by hand; check for a generator first) | inventory rows: auto-decline admin notice (both channels), overwatch alert, customer `restaurant_declined` from a timeout; "What the customer actually sees": countdown |
| `docs/telegram-layer.md` (+ HTML companion) | card status `auto_declined`; database-object row for the policy function; notice `auto_declined` |
| `docs/onboarding-web-only-restaurant.md`, `.claude/skills/ordelo-restaurant-onboarding/` | the two keys and the recommended web-only values (3 / decline / offsets); "Telegram-linked admins required" |
| `docs/live-order-test-harness.md` | stages 1b, 9, 9b |
| `docs/to-do.md` | note that `job_restaurant_confirmation_timeout()` (old keys without `_TIME`) is now a second, unused timeout implementation: orphan candidate for the owner |
| NEW `docs/adr/0014-restaurant-silence-policy-is-decided-in-sql.md` | Records D1, D2, D10 and why there is no global action key, so later reviews do not re-suggest a Python branch |
| SQL headers | all touched files; then `python scripts/datamodels/build_guide.py`; add the new file to `ordelo_datamodels/guide_content.json` if capabilities list files |
| restaurant-frontend `docs/alerts-and-notifications.md` | "What the customer actually sees": countdown, decline-mode only |

Also save this plan as `plans/restaurant-confirmation-timeout-action-plan.md` (done) and keep its status line current.

## 9. Order of work and rollout

Everything is inert until the config rows exist, so each step is safe on its own.

1. OrdeloAgent: SQL files + offline SQL tests (4, 7.1).
2. OrdeloAgent: Python + tests (5, 7.1). Docs (8).
3. restaurant-frontend: countdown + tests (6, 7.2).
4. **Owner applies** `migrations/restaurant_confirmation_timeout_action.sql`, then runs
   `python scripts/datamodels/drift_check.py`. Without config rows the only visible change is the rider clock (D3).
   The SQL must be live **before** the OrdeloAgent deploy: `get_view` calls the new function.
5. Deploy OrdeloAgent, then restaurant-frontend (order between these two does not matter: the field is optional).
6. Live pass in accept mode: harness stages 9 and 9b both auto-accept; WhatsApp regression pass.
7. **Owner runs** `confirmation_timeout_action_rollout.sql` (all four restaurants, D9).
8. Live pass in decline mode: stages 1 + 1b, 9, 9b, and checks 2-4 of section 7.3.

Rollback at any point after step 7: set the action rows to `accept` (or delete them, with approval). No deploy needed.

## 10. Risks and things to watch

| Risk | Mitigation |
|---|---|
| A decline-mode restaurant whose admins are not on Telegram loses every order after 3 minutes with one WhatsApp prompt | Preflight query (4.6) shows `telegram_chats`; do not enable where it is 0 |
| The auto-decline webhook is lost (app down at that moment): the order is `declined` in the database but the customer event and payment cancel did not run | The order page still shows "cancelled" (it reads `summary.status`). The payment authorisation needs releasing: check how `utils_common/web_ordering/lifecycle.py` sweeps `declined` orders without a release; if it does not, add `auto_decline` orders to that sweep or record it in `docs/to-do.md`. The same gap exists today for a manual decline |
| Rider timeouts now run later for every restaurant | Intended (D3). Mention in the release note; watch "No Rider Found" timing on the first live day |
| Policy function evaluated several times per candidate row | Only rows that are unanswered with no pickup time, a handful at any moment |
| `0,…,170` reminders with a 3-minute timeout: the last reminder and the decline are 10-20 s apart | Intended (D5). If the timeout is shortened later, shorten the offsets too; note this in the key description |
| Countdown shows a few seconds more than the truth on first paint (page load time) | The first poll's `Date` header corrects it; the page says "Checking…" rather than "cancelled" until the server confirms |

## 11. Definition of done

- [ ] `restaurant_confirmation_policy()` is the only reader of the timeout keys in SQL and Python (grep proves it; the two Python `_get_*_pickup_default_minutes` helpers read different keys and stay).
- [ ] With no action key, every existing test passes unchanged and harness stages 1-10 behave as before, except the rider clock.
- [ ] With `decline`: unanswered → auto-declined with customer, admins (both channels) and overwatch told once each; accepted-without-pickup → auto-accepted.
- [ ] Telegram card shows "Auto-declined" with no buttons; late tap answers "Already auto-declined".
- [ ] Order page shows the countdown only for decline-mode restaurants, survives a wrong device clock, and resolves within ~15 s of zero.
- [ ] Docs carry the three-mode table in one place; SQL headers, Python docstrings and the generated guide agree; drift check is clean after the owner applies the SQL.
