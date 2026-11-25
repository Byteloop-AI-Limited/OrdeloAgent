# Web storefront controls and audit alignment

24 November 2026 · Implementation plan

## Owner decisions

| Restaurant | Configured auto-accept | When an unanswered order expires | Pickup defaults at the last live check, delivery / collection |
| --- | --- | --- | --- |
| BNAT · Burger Nation | On | Configured auto-accept bypasses confirmation | 30 / 20 min |
| CRDO · Crispy Dosa | Off | Auto-decline after two minutes | 30 / 30 min |
| CRMS · Creams | Off | Auto-decline after two minutes | 17 / 17 min |
| STRK · Strikers | Off | Auto-decline after two minutes | 30 / 30 min |

- Implement **inherit global** first. The pickup durations above provide a baseline. Changing a restaurant's duration or switching its stored override to inheritance is an independent dashboard action.
- An unanswered order remains eligible for Accept until the timeout sweep wins the decision. For example, an Accept at 2:03 succeeds if the sweep has yet to decide the order. The tracking countdown reaches zero after two minutes and the page waits for the authoritative result. Manual and timeout declines share the existing “couldn't accept your order” copy.
- Align the price audit with the 5% offer at **BNAT, CRDO, CRMS, STRK, ELAS and SFCS**.
- STRK remains the test restaurant. Its city, opening hours and `TEST3100` item stay as configured for testing. Commercial STRK preparation, payment service changes, delivery pricing service changes, and staff and rider readiness are in the [to-do](../docs/to-do.md#web-storefront-launch-24-nov-2026).

The [glossary](../GLOSSARY.md#restaurant-decisions-and-kitchen) defines timeout action separately from a restaurant decision. [ADR 0001](../docs/adr/0001-configured-restaurant-auto-accept.md) covers configured auto-accept. [ADR 0014](../docs/adr/0014-restaurant-silence-policy-is-decided-in-sql.md) covers unanswered orders and the separate pickup-time grace after Accept. These decisions use those existing concepts.

## 1. Resolve inherited pickup defaults in both timeout handlers

### Existing behaviour

The acceptance dashboard writes an empty `ordelo_config.config_value` when an existing restaurant pickup override is cleared. [restaurant_settings.sql](../ordelo_datamodels/restaurant_admin/restaurant_settings.sql) already exposes `restaurant_default_pickup_minutes(rest_ref, kind)`, returning `minutes` and `inherited`. It uses a valid restaurant override first, then a valid mode-specific global key. [resolve_initial_restaurant_acceptance.sql](../ordelo_datamodels/restaurant_admin/resolve_initial_restaurant_acceptance.sql) resolves the same policy when configured auto-accept initializes an order. The delivery and takeaway timeout handlers each parse the first config row directly. An empty value raises before the order gets a pickup time.

### Proposed code

- Use the existing SQL lookup as the seam for both timeout handlers. Add one small async adapter, `default_pickup_minutes(rest_ref: str, order_type: OrderType) -> int`, in [restaurant_decision.py](../utils_common/order_management/restaurant_decision.py). Call the existing service-role RPC via its `_rpc` helper, with `p_rest_ref` and `p_kind`. Supabase returns a list for this table-returning function. Require one row with either a positive integer `minutes` or an explicit null. Preserve the existing 30-minute timeout fallback on null and log the ref and order type so ops can correct configuration. Treat RPC failure or an invalid result shape as an operational error.
- Replace `_get_delivery_pickup_default_minutes` in [delivery_hooks.py](../watomation/routers/delivery_hooks.py) and `_get_pickup_default_minutes` in [takeaway_hooks.py](../watomation/routers/takeaway_hooks.py) with calls to that adapter. Pass `'delivery'` or `'takeaway'`. The scheduled pickup remains summary `dtts + timedelta(minutes=minutes)`. Preserve the notice, hook response and transition for each mode.
- Give the delivery update the same compare-and-set protection as collection: require `restaurant_confirmation_status = 'restaurant_timedout'` and null `pickup_time`. Only the successful update sends the auto-accepted notice. Test a replay and a previously set pickup time. This matters because two webhook deliveries can both resolve the defaults before either writes.
- Keep the configured-auto initializer and the dashboard contract stable. [ADR 0018](../docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md) deliberately kept the live initializer independent and verifies agreement through SQL tests. The adapter removes duplicate raw configuration parsing from both handlers without changing order initialization. Add the Python/SQL cross-references and update the timeout-default section in [pickup_time_logic.md](../docs/pickup_time_logic.md).

```python
minutes = await restaurant_decision.default_pickup_minutes(rest_ref, "delivery")
pickup_time = parse_db_iso(summary.dtts) + timedelta(minutes=minutes)
# Advance only the timed-out order whose pickup time is still unset.
```

### Verification

- Extend [test_restaurant_decision.py](../tests/utils_common/order_management/test_restaurant_decision.py) for the RPC contract, the 30-minute fallback, and error propagation. Extend the existing [delivery hook tests](../tests/watomation/routers/test_delivery_hooks.py) and [collection hook tests](../tests/watomation/routers/test_takeaway_hooks.py) to verify resulting state, the scheduled time and one notice across duplicate deliveries.
- Use [test_restaurant_settings_sql.py](../tests/sql/test_restaurant_settings_sql.py) to verify, for both modes, a populated override, a blank override after dashboard clearing, a missing override, bad restaurant text with a valid global value, and no usable global value. Check configured-auto agreement for supported settings and preserve its existing failure behaviour for invalid configuration.
- On STRK, rehearse the dashboard's Inherit global action with test orders after the fix is deployed. For delivery and collection, accept and skip pickup selection. Observe the default taking effect after the existing grace or ordinary timeout, whichever comes first. Restore the captured STRK settings after the test. Include an explicit pickup selection to verify that the fallback leaves the chosen time intact.

**Database migration:** no DDL expected. Confirm the existing function and service-role execute grant live before deploying the Python code. If they are missing, apply the existing SQL definition first.

## 2. Configure timeout auto-decline and verify tracking

### Proposed changes

- Prepare a standalone operator SQL file under [restaurant query runbooks](../notebooks/db_queries/restaurant_queries), for example `web_storefront_confirmation_policy.sql`. Snapshot precisely `restaurant_master.auto_accept` for the four refs and the two timeout keys for CRDO, CRMS and STRK. Set BNAT true if needed, and CRDO, CRMS and STRK false. Use the audited acceptance write path for changes to `auto_accept` so current pickup overrides and dashboard history are retained. Inspect `restaurant_acceptance_apply` in [restaurant_settings.sql](../ordelo_datamodels/restaurant_admin/restaurant_settings.sql) and reuse the sys-admin route where appropriate.
- Upsert `<REF>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME='2'` and `<REF>_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION='decline'` for **CRDO, CRMS and STRK**. Show the exact effective result from [restaurant_confirmation_policy.sql](../ordelo_datamodels/restaurant_admin/restaurant_confirmation_policy.sql) and the current auto-accept value in the verification output. Include a rollback from the before-state and record any keys absent before the change. Avoid rerunning the [historical three-minute switch](../notebooks/db_queries/restaurant_queries/confirmation_timeout_action_rollout.sql), which includes BNAT and uses retired invite-based roster checks. Add a pointer from that script to its replacement.
- Use the current [admin roster](../ordelo_datamodels/restaurant_admin/admin_roster.sql) and the alert and pause rules to confirm who can receive and act on an order. Check effective `<REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS` or global offsets from [t_order_alerts.sql](../ordelo_datamodels/telegram/t_order_alerts.sql). Retain existing offsets that fall below 120 seconds. Surface any longer offsets for an operator decision. Stage changes per restaurant in a quiet window after outstanding confirmations have settled, because the sweep reads the current policy for pending orders.
- Retain first-decision-wins in [process_restaurant_confirmation.sql](../ordelo_datamodels/restaurant_admin/process_restaurant_confirmation.sql) and [restaurant_order_decision.sql](../ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql). The two-minute interval starts at the summary `dtts`, when the restaurant confirmation starts. On a normal 10-second schedule, the sweep can commit shortly after the nominal deadline. When it wins, it atomically writes `auto_decline` and `declined`. A staff Accept that wins first follows the ordinary pickup-time flow, including the existing 15-second grace. The timeout applies to both delivery and collection.
- Keep the existing tracking interface in [customer_order_view.py](../utils_common/web_ordering/customer_order_view.py). While unconfirmed under a decline policy, it sends an absolute `confirmation.deadline_at`. [ConfirmCountdown.tsx](../../restaurant-frontend/components/order-status/ConfirmCountdown.tsx) shows “Checking with …” at zero and [OrderPage.tsx](../../restaurant-frontend/components/order-status/OrderPage.tsx) polls for the decision. Once SQL declines, use `display_status='cancelled'` and `cancel_reason='restaurant_declined'` with the shared copy in [status.ts](../../restaurant-frontend/lib/web/status.ts). Continue polling through `release_pending`. Show release only once the release evidence arrives. A late Accept that wins the race removes the countdown and advances normally.
- Preserve decline side effects in delivery and takeaway hooks and [lifecycle.py](../utils_common/web_ordering/lifecycle.py). A declined delivery becomes ineligible for dispatch, and a declined collection never reaches pickup or capture. Verify customer and ops notices and the payment-release result independently from the terminal order status.

### Verification

| Scenario | Expected result |
| --- | --- |
| CRDO, CRMS, STRK silence | Waiting with countdown → checking if the sweep hasn't decided yet → cancelled with the shared decline message. Release pending → released when confirmed. |
| Accept at 2:03, before the sweep wins | Accept succeeds and the page proceeds. The next sweep follows accepted-order pickup grace rules. |
| Accept after the sweep wins | Already decided. Declined status remains and there is no pickup or dispatch. |
| Admin taps Decline before two minutes | Same terminal tracking message. Backend decision metadata still identifies the manual decline. |
| Admin accepts without selecting pickup | The restaurant accepted, so the pickup fallback runs. Cover an inherited global default. |
| BNAT configured auto-accept | No undecided confirmation or countdown. Both modes start with their effective pickup defaults. |

Extend the existing [timeout SQL tests](../tests/sql/test_restaurant_confirmation_timeout_sql.py), [decision SQL tests](../tests/sql/test_restaurant_decision_sql.py) and [tracking contract tests](../tests/utils_common/web_ordering/test_web_contract.py). In the frontend, use [ConfirmCountdown.test.tsx](../../restaurant-frontend/components/order-status/ConfirmCountdown.test.tsx) and [status.confirmation.test.ts](../../restaurant-frontend/lib/web/status.confirmation.test.ts) for the waiting, checking and cancellation copy, plus a tracking fixture that switches from `release_pending` to `released`. Keep the existing status values unless a test exposes a contract defect. Refresh [pickup time logic](../docs/pickup_time_logic.md) and the [Telegram change log](../docs/telegram-layer.md) with the effective policy and the race behaviour.

The operator verification should include:

```sql
SELECT r.rest_ref, r.auto_accept, p.timeout_minutes, p.timeout_action
FROM public.restaurant_master AS r
CROSS JOIN LATERAL public.restaurant_confirmation_policy(r.rest_ref::text) AS p
WHERE r.rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
ORDER BY r.rest_ref;
```

Expect `true` for BNAT and `false, 2, decline` for CRDO, CRMS and STRK. Report BNAT's stored timeout values for context since configured auto-accept bypasses them.

**Database migration:** no DDL expected. This phase is a configuration update. Isolated SQL tests cover the existing workflow before applying rows. End-to-end provider capture and release still depend on the relevant merchant or Wren payment route.

## 3. Align all six storefronts with the nightly price audit

### Proposed changes

- Use [config/restaurants.ts](../../restaurant-frontend/config/restaurants.ts) and [offers.ts](../../restaurant-frontend/lib/storefront/offers.ts) as the sources for the configured storefront offer. [pricing.ts](../../restaurant-frontend/lib/storefront/pricing.ts) applies the 5% to the restaurant selling price and rounds each unit before multiplying by quantity.
- Prepare `web_offer_audit_alignment.sql` under [restaurant query runbooks](../notebooks/db_queries/restaurant_queries). Preflight the six `<REF>_WEB_MAX_DISCOUNT_PERCENT` keys, preserving values and row presence. Upsert `5` for the six exact refs and verify each value. Preserve existing 5% values where present. Provide a rollback procedure from the preflight values. This configuration controls the audit threshold. The frontend offer still controls what the customer pays.
- Verify the OrdeloAgent release includes the existing [menu-floor fix](../utils_common/web_ordering/monitoring.py), which selects a valid `discounted_price` as the selling price and uses `price` when no offer price exists. If the production revision lacks it, release that fix with its [existing tests](../tests/utils_common/web_ordering/test_price_audit_floor.py). Raising the allowance alone would still flag legitimate direct-menu savings if the deployed audit compares against the delivery-app reference price.
- Keep the daily claim and alert flow local to `monitoring.sweep()`. Reuse `below_floor` for pence tolerance. Keep missing menu matches reviewable. Avoid introducing a shared runtime offer source across repos for this alignment. Instead add a preflight comparison of the six configured allowances with the six web offers. Server-side menu and modifier repricing remains a separate project.

### Verification

- Test against a selling price lower than the delivery-app comparison price, a regular-only item, a 5%-discounted unit rounded to pence, a price below the floor by more than the tolerance, and a missing menu match. Run the [frontend pricing tests](../../restaurant-frontend/lib/storefront) and the existing [backend contract cases](../tests/utils_common/web_ordering/test_web_contract.py).
- Run a read-only audit query over recent order lines with the proposed allowance before rollout. Report distinct causes such as a previous reference-price comparison, a missing menu match, or a price genuinely below the floor. Historical orders compared against today's menu are diagnostic evidence.
- Verify the next natural [web_monitor_run](../ordelo_datamodels/ordering/web_monitor_run.sql) completes and check for unexpected flags. Use the read-only preview for same-day verification if today's audit has already run.

**Database migration:** no DDL expected. The live change is six configuration rows.

## Release order and evidence

1. Ship and verify the pickup-default fix first. Keep its diff reviewable alongside existing local checkout-resume work.
2. Review the two standalone SQL bundles. Verify the current SQL functions, grants, confirmation cron cadence, current config and pending-order counts. Apply the restaurant policy per venue once its test window is agreed. Apply audit alignment once the selling-price floor is verified on the running backend.
3. Record offline Python and frontend results, isolated Postgres results, and live STRK evidence separately. Verify visible chat outcome, backend processing and read-only database state. Use authorized `TEST3100` flow and avoid relying on the storefront hostname to select test payment. Leave merchant captures for the provider test once the colleague's work is ready.

```sh
# OrdeloAgent, after standard local shell preparation
python -m pytest -q tests/utils_common/order_management/test_restaurant_decision.py \
  tests/watomation/routers/test_delivery_hooks.py tests/watomation/routers/test_takeaway_hooks.py \
  tests/utils_common/web_ordering
# Run with the throwaway Postgres from the ordelo-sql-test-db skill.
python -m pytest -q tests/sql/test_restaurant_settings_sql.py \
  tests/sql/test_restaurant_confirmation_timeout_sql.py tests/sql/test_restaurant_decision_sql.py

# restaurant-frontend
NODE_OPTIONS=--no-experimental-webstorage npm test -- \
  lib/storefront lib/web/status.confirmation.test.ts components/order-status/ConfirmCountdown.test.tsx
```

The plan's code and test sketches describe proposed implementation. Production configuration changes and deployments are separate steps.
