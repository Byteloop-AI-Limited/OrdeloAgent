# ADR 0018: Restaurant dashboard settings are audited, and closures and hidden items are enforced at order creation

## Status

Accepted 19 Nov 2026 (owner decisions of 18-19 Nov 2026). Built and applied to the live database on 19 Nov; the code is not deployed yet (`docs/to-do.md`, "Telegram portal links and restaurant dashboard"). Access to the dashboard itself is [ADR 0017](0017-portal-access-is-decided-per-request-in-sql.md).

## Context

The restaurant dashboard's Actions and Reports pages were placeholders ("Coming soon"). The owner asked for all of them: accepting orders (auto-accept and default pickup times), notification preferences, holiday / closed dates, menu visibility, and reports. Restaurant settings live in tables that live order creation reads (`restaurant_master`, `ordelo_config`, `service_hours_json`), and three separate readers interpret opening hours (the web backend, the storefront and the WhatsApp restaurant agent). The browser-side tenant client scopes named tables only, not functions.

## Decision

**Who may change what.** Any admin on a restaurant's `admins` list may change that restaurant's operating settings from the dashboard. Every change is recorded (who, when, through which surface, old and new value) and overwatch can undo it from the system dashboard.

**One audited write path.** Every dashboard write is a SQL function that takes the session id stamped by the frontend middleware, never a restaurant or phone from the browser. `rest_admin_session_actor()` re-derives the phone and restaurant and re-checks membership. `restaurant_setting_change()` writes the value and its `restaurant_settings_audit` row in one transaction. `restaurant_setting_revert()` re-applies the old value only while the current value is still what that change set ("changed since" otherwise), and the undo is itself recorded. Sys-admin edits of the two default pickup-time keys use the same audited path.

**Accepting orders.** The acceptance policy (`restaurant_master.auto_accept` and the restaurant's default delivery / collection pickup minutes) is changed atomically with a version check, so a stale edit from another admin is refused. Minutes are whole numbers from 1 to 180, or empty to inherit the global default. Auto-accept cannot be switched on unless both effective defaults resolve, because order creation would otherwise fail ([ADR 0001](0001-configured-restaurant-auto-accept.md)). A change affects new orders only. The dashboard reads the effective minutes with `restaurant_default_pickup_minutes()`, which repeats the lookup inside `resolve_initial_restaurant_acceptance()`; a SQL test keeps the two identical, so the live order-creation function was not changed.

**My alerts.** The dashboard changes the signed-in admin's alert channels and pauses new Telegram alerts for one restaurant through the same SQL rules as the restaurant bot's `/channels`, `/off` and `/on`, including the last-admin guard ([ADR 0013](0013-pauses-have-a-mandatory-end-and-are-computed.md)). Channels belong to the person; a pause belongs to the person and the restaurant.

**Closed dates live in the service hours.** A closed date is a one-date override inside `restaurant_master.service_hours_json`:

```
{"mon": [["12:00","22:00"]], ..., "dates": {"2026-12-25": [["00:00","00:01"]], "2026-12-24": [["12:00","18:00"]]}}
```

- A date is a London calendar date. Its list replaces that weekday's hours on that date only, and clearing it restores the weekly rule.
- `[["00:00","00:01"]]` (the owner's all-day marker) and `[]` both mean closed all day.
- An early close keeps the earlier intervals, cuts the one containing the chosen time, and drops later ones.
- Yesterday's past-midnight hours never spill into an overridden date. An override's own hours may run past midnight unless the next day is overridden too.
- The dashboard offers "Change hours for one date" (closed all day, close early, special hours) and "Edit regular weekly hours". The sys-admin weekly editor keeps stored dates when it saves.
- Every reader applies the same rule: SQL `service_hours_open()`, the web backend `availability.opening()`, the storefront `resolveServiceHoursForWeek()` and restaurant-agents `WeeklySchedule`.

**Hidden items.** An admin hides a menu item until an admin explicitly shows it again. Hiding is stored in `menu_item_hidden`, separate from the bulk-replaced `<rest_ref>_menu` tables, so a menu refresh keeps it and the item's stock status is untouched. The key is the normalised item title (lower case, single spaces), because not every menu table has a SKU and every order line has a product name. The storefront drops hidden items from the menu.

**Enforcement at order creation.** `create_food_order_with_items()` first asks `order_intake_block()`, for both channels. It refuses with SQLSTATE `P0C01` when a date override has closed a time the weekly hours had open, and `P0C02` when the basket has a hidden item. Nothing is written when it refuses. It refuses only on a positive decision: with no override and no hidden row the old behaviour is unchanged, any error inside the guard allows the order, and the weekly opening hours are still not enforced in the database. The restaurant is the order number's prefix (CHKS orders are numbered ELAS). Callers map the refusals to `restaurant_closed` and `items_unavailable`; an idempotent web retry of an order created earlier is answered before the insert.

**Reports.** Reports show operational measures first, plus the existing sales figures (by day or month, with CSV export):

- Orders are counted on the London date they were created. Test orders (`TEST3100`) are left out.
- Acceptance is split into manual, configured auto-accept, timeout fallback, declined and no answer.
- Manual acceptance time is first decision minus creation. The first decision is captured in `order_milestone` by a trigger from 19 Nov 2026; older orders count only while their timestamp was never overwritten. No historical backfill.
- Delivery pickup uses the verified `food_collected` event. It reports minutes from creation to collection, and minutes early (−) or late (+) against two benchmarks:
  - the original promise: `pickup_time_initial`, or `pickup_time` if never adjusted
  - the latest promise in force at collection: `pickup_time`

  For example, collected at 18:45 with an original promise of 18:30 and a latest promise of 18:50 gives +15 and −5. Medians are per measure, with the number of orders measured.

**Rollout gate for closed dates.** Dashboard hours writes are refused unless `ordelo_config.REST_DASHBOARD_HOURS_EDITS` lists the restaurant (`all` or a comma list; empty = off). The restaurant agent's old schedule parser rejects any non-weekday key, so ELAS / CHKS, BNAT and SFCS must not be listed until the new restaurant-agents is deployed.

## Consequences

- Restaurant staff can run their own operating settings; overwatch can see and reverse every change.
- A closed date or hidden item is refused at order creation even from a stale storefront tab or an old WhatsApp menu link.
- The WhatsApp menu itself (the external `MENU_API_URL` service) does not hide items until its owner filters them; the order check is the backstop.
- In the restaurant agent, overwatch numbers bypass opening hours but the database check has no bypass, so an overwatch tester on a closed date reaches checkout and is then refused.
- Operational report accuracy for manual acceptance grows from 19 Nov 2026 onward.

## Considered and rejected

- A separate closure table: rejected by the owner in favour of date overrides inside the service hours, which every reader already loads.
- Keying hidden items by SKU: `elas_menu` has no SKU column.
- Letting restaurant admins use the sys-admin configuration endpoint: it writes arbitrary keys, unaudited.
- Refactoring the live `resolve_initial_restaurant_acceptance()` to share the pickup lookup: an agreement test was preferred to changing a live order-creation function.
- Reporting acceptance from `restaurant_update_dtts` alone: later actions overwrite it.
- Enforcing weekly opening hours in the database: out of scope; the check refuses only what an override or a hidden item adds.

## Implementation and verification (19 Nov 2026)

SQL owners: `restaurant_admin/restaurant_settings.sql`, `restaurant_admin/rest_admin_dashboard_alerts.sql`, `restaurant_admin/restaurant_service_hours.sql`, `ordering/menu_item_visibility.sql`, `ordering/order_intake_guard.sql`, `ordering/create_food_order_with_items.sql`, `admin_dashboard/rest_admin_reports.sql` (applied with `migrations/restaurant_settings_p1.sql`, `rest_admin_alerts_p1.sql`, `order_intake_guard_p1.sql`, `rest_admin_reports_p1.sql`).

Frontend:
- `app/rest-admin/actions/_components/*` and `app/rest-admin/reports/*`
- `app/api/rest-admin/settings/*` and `app/api/rest-admin/reports/*` over `lib/rest-admin-rpc.ts`
- `lib/hiddenMenuItems.ts` and `utils/openingHours.ts`
- sys-admin `RecentChanges` and the `changes` routes

Readers: OrdeloAgent `utils_common/web_ordering/availability.py`; restaurant-agents `services/service_hours/{parsing,schedule}.py`.

Verified on 19 Nov:
- Offline and on an isolated database: `tests/sql/test_restaurant_settings_sql.py`, `test_rest_admin_dashboard_alerts_sql.py`, `test_restaurant_service_hours_sql.py`, `test_order_intake_guard_sql.py`, `test_rest_admin_reports_sql.py`, plus the frontend and restaurant-agents unit tests.
- Live, through the local services:
  - Acceptance change and sys-admin undo on STRK.
  - Dashboard pause ended by the bot's `/on`.
  - A closed and an early-closed date on STRK: the SQL, backend and restaurant-agents readers agreed, then STRK was restored exactly.
  - Hiding an item removed it from the storefront.
  - A rolled-back order showed normal orders still created and a hidden item refused.
  - Reports on ELAS data.
- The owner then confirmed orders, access removal, reports, menu hiding and the sys-admin edits.
- Still to test: closed dates end to end and WhatsApp `/login` / `/sysadmin` (`docs/to-do.md`).
