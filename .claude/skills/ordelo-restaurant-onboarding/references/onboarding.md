# Ordelo onboarding procedure

Paths below are relative to the OrdeloAgent repository root unless stated otherwise.

## Sources and precedence

Read the relevant files before preparing a new restaurant:

| Source | Use |
| --- | --- |
| `plans/onboard-crms-plan.md` | Historical D1–D13 decisions and CRMS data; distinguish restaurant-specific decisions from reusable mechanisms. |
| `docs/onboarding-web-only-restaurant.md` | Existing reusable runbook; contains obsolete gates described below. |
| `notebooks/db_queries/restaurant_queries/onboarding_crms/` | Worked SQL examples: `00_preflight_readonly`, `01_restaurant_master`, `02_ordelo_config_crms_keys`, `03_prod_test_enable`, `04_go_live`, `99_rollback`. |
| `onboarding_crms/result_export.json` in that folder | Historical query output, not current database state or an instruction to restore those keys. |
| `ordelo_datamodels/menu.sql` | CRMS menu schema to adapt into the new restaurant's `menu.sql`. |
| `utils_common/web_ordering/{common,availability,monitoring}.py`, `config/feature_flags.py` | Current registry, availability, pause and price-audit contracts. |
| `docs/test-orders.md` and `utils_common/order_management/test_order_dispatch.py` | Current per-order payment selection and test rider eligibility. |
| `ordelo_datamodels/restaurant_master_pymodel.py`, `watomation/fapp_ordelo_agent.py` | Restaurant cache and `/internal/cache/reset` contract. |

As checked when this skill was created (2026-10-11), the CRMS plan/runbook and
exports contain conflicting generations of configuration. Current implementation
and current test-orders guidance take precedence; recheck them when using this skill:

- `WEB_ORDERING_ENABLED_REST_REFS`, the old rollout flags, restaurant-wide payment
  selectors, and `{REF}_WEB_DELIVERY_PAUSED` are retired. Do not generate them.
- `{REF}_WEB_ORDERING_PAUSED=true` blocks new web orders; missing/false means open.
  The flag reader also treats lookup failure as false, so verify the pause at the
  deployed endpoint rather than assuming a written SQL file blocks checkout.
- Only an accepted item named exactly `TEST3100` selects test payment for a new
  order. URL parameters, customer status and temporary restaurant windows do not.
  A normal basket uses live payment even while staff are testing.
- The CRMS SQL examples include `BEGIN`/`COMMIT` and a placeholder `DO` guard;
  generated manual SQL must follow the repository's standalone-statement preference.
- CRMS's timings, commission, admin numbers, town, branding, both-mode launch and
  historical branches are restaurant-specific choices, not automatic defaults.

## Collect the restaurant inputs

Record agreed values and unresolved decisions in the new plan:

- Uppercase `rest_ref` (current schema: four characters); lowercase slug/menu API
  identifier; channel (web-only or WhatsApp too); town; desired fulfilment modes.
- `rest_id` (unique, nullable; verify actual type/length), name, email, public phone,
  address components, postcode and confirmed latitude/longitude for pricing.
- Per-day service intervals, delivery/takeaway cutoffs (web enforces at least 15
  minutes), collection commission, manual versus automatic acceptance, admin
  WhatsApp numbers in international format without `+`, temporary test admins if
  needed, pickup defaults, dispatch/confirmation timeouts and stale-thread timeout.
- Branding, supplied logo/hero URLs, offers and corresponding maximum discount.
- Menu source, item identifiers/SKUs, prices/currency, categories, descriptions,
  images, availability, dietary fields and the actual addon structure expected
  by the menu consumer. Separate schema creation from receipt of menu data.
- Payment account/payout destination, deployed test/live support, menu-service
  support, and delivery pricing/rider coverage where delivery is requested.

Do not borrow CRMS or another restaurant's admins, Stripe destination or menu
defaults. Unconfirmed commission, hours, prices or routing stay open decisions.

## Generate the SQL bundle

Use a new `notebooks/db_queries/restaurant_queries/onboarding_{slug}/` directory.
Use actual confirmed identifiers and escaped literals; validate the slug before
forming a SQL table name. Do not blindly replace strings in historical SQL.

| File | Required work |
| --- | --- |
| `00_preflight_readonly.sql` | Check `rest_ref`/`rest_id` collisions, actual schema/constraints, existing restaurant keys, menu-table existence, and order/dependency history if resuming onboarding. Use `to_regclass`/catalog checks before issuing queries against a missing menu table. |
| `01_restaurant_master.sql` | Insert the agreed row with columns below, `RETURNING` and a verification query. If a row already exists, compare values and update only the agreed onboarding fields; a blind upsert can overwrite operational settings. |
| `02_ordelo_config_{slug}_keys.sql` | Insert supported per-restaurant keys, initially paused, with scoped conflict handling and verification. |
| `menu.sql` | Create `public.{slug}_menu` from the current shared schema, adapting restaurant-specific defaults; add menu verification queries. |
| `menu_seed.sql` (when data is supplied) | Populate/import confirmed menu items using actual identifiers and consumer-compatible JSON. Establish the repeat-run strategy from real constraints; the reference schema has no primary/unique key. |
| `03_prod_test_enable.sql` | Unpause only for an authorized test window, verify the pause state and inspect recent orders/items/payment mode. Include a separate re-pause statement. This file does not make normal baskets test orders. |
| `04_go_live.sql` | Set confirmed operational admins and timeout, verify prerequisites, then unpause as a separate final statement. Omit executable writes for any unresolved value. |
| `99_rollback.sql` | Primary action: restore `{REF}_WEB_ORDERING_PAUSED=true` with verification. Put optional destructive removal in a separately labelled, non-executed section; inspect orders, references and sessions before deleting anything. |

Never generate a `result_export.json` as though queries ran. Save actual verified
output only after authorized execution, minimizing private information. Preserve
other restaurants' keys and global URLs.

### restaurant_master insertion

The CRMS example inserts these fields; inspect actual schema before adapting:

```text
rest_ref, rest_id, rest_name, rest_email, admins,
house_number, building_name, street_name, city, postcode, lat, lon,
rest_stale_active_threads_minutes, restaurant_start_time, restaurant_end_time,
service_hours_json, delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
collection_commission, auto_accept
```

`service_hours_json` is the web contract, for example
`{"mon": [["11:00", "24:00"]], ...}` with actual intervals for each day.
The legacy start/end columns use an h.mm convention; do not substitute them for
the web schedule. Follow the evaluator for closed days, overnight periods and
London time. Verify the commission's stored units against its consumer.

### ordelo_config insertion

Adapt these supported CRMS keys after checking their current readers:

```text
{REF}_DEFAULT_DELIVERY_PICKUP_TIME
{REF}_DEFAULT_COLLECTION_PICKUP_TIME
{REF}_DELIVERY_TIMEOUT_TIME
{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME
{REF}_WEB_MAX_DISCOUNT_PERCENT
{REF}_WEB_ORDERING_PAUSED = true
```

Use `(config_key, config_value, description)` and update `updated_at` when changing
existing keys. Confirm required keys for the requested modes. Keep discounts aligned
with frontend offers. Do not add `{REF}_APP_URL` for web-only onboarding.

### Creating menu.sql and menu data

The shared `ordelo_datamodels/menu.sql` currently defines:

```sql
CREATE TABLE public.crms_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP'::text,
    branch_link text DEFAULT 'https://www.creamscafe.com/our-stores/orpington/'::text,
    image_link text,
    branch_name text DEFAULT 'Orpington'::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);
```

Read it again for drift. Generate the new table name and confirmed branch defaults,
or omit unconfirmed optional defaults. Do not carry over the Creams link or branch.
Do not invent identity generation, a primary key or `ON CONFLICT(id)`—none exists
in this source. If these are needed, reconcile with the actual importer and menu
service before proposing a constraint. `CREATE TABLE IF NOT EXISTS` alone does not
prove an existing table has the right columns: inspect and compare its schema.

Keep the `{slug}_menu` naming contract: the web price audit constructs this table
name from the backend registry and joins `lower(trim(title))` to product names.
Check nonempty titles/categories, valid currency/prices, item counts, unique
identifiers as required by consumers, duplicate normalized titles and addon JSON.
Duplicate titles are audited using their minimum price; review differences.
For exact `TEST3100` items, preserve normal quantity, price, modifications and
receipt entries; staff must not prepare the test item's food. Menu DDL alone does
not establish that the menu service supports the new restaurant.

## Backend, frontend and additional channels

- Add `{REF}: {"town": "{town}", "phone": "{public_phone}"}` to
  `utils_common/web_ordering/common.py::RESTAURANTS`. A database row alone leaves
  `/web/*` rejecting the restaurant. Update the module docstring if editing it.
- In sibling `restaurant-frontend/config/restaurants.ts`, add the town if needed
  and restaurant entry with correct `apiName`, `orderApiName`, `towns`, branding,
  `contactPhone`, `webOrderingEnabled` and `webOnly: true` for web-only scope.
  Keep it discoverable by checkout and payment return pages.
- Check the primary storefront and legacy `/restaurant/{slug}` redirect. Backend
  town must match the frontend primary town. Eligibility chooses the first
  deliverable restaurant's town: examine overlapping postcode coverage before
  changing towns; do not move existing restaurants just because CRMS moved BNAT.
- Web-only needs no restaurant-agents changes. If WhatsApp-agent onboarding is
  requested, inspect `notebooks/db_queries/restaurant_queries/onboarding_new_restaurant.sql`
  and the current restaurant-agents onboarding/deployment docs. Resolve app URL,
  runtime and Meta dependencies within that authorized scope; this web-only
  example does not prove their setup.

## Verify readiness and launch

1. Verify menu-service support and returned data against the new menu table.
   The frontend's `MENU_API_URL`/menu route resolves the upstream; test upstream
   separately from rendering. An unsupported restaurant response is a service gate.
2. Inspect the current payment implementation and deployed test/live mapping to
   the correct account, payout and return URLs. The historical Go service fell
   back to ELAS for unknown references: do not assume support from the DB row or
   plan. Check retained `payment`/`wrenPayment` contracts in `docs/test-orders.md`.
3. Verify requested delivery pricing from the confirmed restaurant coordinates,
   usable quotes and rider coverage, including eligible overwatch riders for test
   deliveries. Unsupported requested modes block launch; agree a narrower launch
   scope rather than using the retired delivery-only pause.
4. Confirm the written pause is effective before public registration/deployment
   opens a route. Deploy only when authorized. Smoke-test the actual deployed
   storefront, menu, checkout paused response and redirect behavior.
5. Run relevant existing backend web-ordering tests and frontend lint/build for
   changed code, using the local runbook's environment setup. Distinguish baseline
   failures from regressions. These checks do not replace service verification.
6. Use the local automatic-orders skill for authorized collection/delivery test
   orders containing exact `TEST3100`. Verify saved `payment_mode='test'`, Stripe
   checkout/capture/webhook alignment, admin acceptance/decline/timeout, order-page
   progress, hours/cutoff and pause behavior. Test deliveries must reach eligible
   overwatch riders. Ordinary baskets remain live; re-pause after the window.
7. Before authorized go-live, confirm real admins can receive actionable messages,
   operational timeout, menu/discount audit and service evidence. Reset restaurant
   cache using the current `/internal/cache/reset` authentication/parameters after
   changing admins (RestaurantMaster normally caches an hour; flags cache 60 s).
   A transport success is not confirmed WhatsApp delivery.
8. Remove the pause only at the agreed launch step. An actual live payment/order,
   refund, Meta change or deployment needs authorization for that action. Report
   exactly what was verified and any pending operational evidence.
