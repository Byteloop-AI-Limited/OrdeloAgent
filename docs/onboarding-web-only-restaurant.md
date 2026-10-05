# Runbook: onboarding a web-only restaurant

Use this to add a restaurant that is sold **only on the Ordelo web storefront** (`/town/{town}/{slug}`), with no WhatsApp agent, no restaurant-agents app and no restaurant-specific UI.

Worked example: CRMS (Creams Orpington), see [`plans/onboard-crms-plan.md`](../plans/onboard-crms-plan.md) and the SQL in [`notebooks/db_queries/restaurant_queries/onboarding_crms/`](../notebooks/db_queries/restaurant_queries/onboarding_crms/). To onboard `{REF}`, copy that folder to `onboarding_{ref}/` and replace the values.

For a WhatsApp restaurant (with an agent app), use [`notebooks/db_queries/restaurant_queries/onboarding_new_restaurant.sql`](../notebooks/db_queries/restaurant_queries/onboarding_new_restaurant.sql) instead. That flow also needs `{REF}_APP_URL` and a restaurant-agents app.

---

## 0. Collect before starting

| Item | Used for |
|---|---|
| `rest_ref` (4 chars, upper) and frontend id/slug (lower) | Everywhere; order numbers are `{REF}-XXXX-NN` |
| Town slug (existing or new) | Frontend `TOWNS`, `towns`, backend registry `town` |
| Name, tagline, public phone, brand colour, logo/hero URLs | Frontend config; the phone also goes in the backend registry |
| rest_id (≤ 12 chars, UNIQUE, nullable), email | `restaurant_master` |
| Full address, postcode, **lat/lon** | `restaurant_master`; lat/lon is the pricing quote origin |
| Opening hours per day, delivery/takeaway cutoff (web minimum 15) | `service_hours_json`, `*_order_cutoff_minutes` |
| Collection commission | `restaurant_master.collection_commission` |
| Confirmation mode: manual (admins) or auto-accept | `auto_accept`, `admins` |
| Admin WhatsApp numbers (E.164, no `+`) | `restaurant_master.admins` |
| Pickup defaults, dispatch timeout, confirmation timeout | `{REF}_*` config keys |
| Web offers (if any) and maximum discount | Frontend `ordeloOffers`; `{REF}_WEB_MAX_DISCOUNT_PERCENT` |
| Modes at launch | Both delivery and collection (R3.1 removed the delivery-only pause) |

## 1. External prerequisites (other services; check, don't assume)

1. **Payment service** (Go, separate repo) knows `{ref}` in **test and live**: Stripe account/payout destination and success/cancel URLs. **Critical:** an unknown `restRef` falls back to ELAS (plan F13), so the money would go to the wrong restaurant.
2. **Menu service** (`MENU_API_URL`) serves `?restaurant_name={apiName}`, normally from a `{ref}_menu` table. The nightly web price audit also joins `{ref}_menu` by `title`, so the table name must follow that pattern.
3. **Pricing service** returns a `car` option for `rest_ref: "{ref}"` from the restaurant lat/lon (delivery only).
4. **Rider cover** exists for the area (delivery only).

## 2. Ordelo database (manual SQL)

| Step | File (copy from the CRMS example) | Notes |
|---|---|---|
| Pre-flight | `00_preflight_readonly.sql` | rest_ref/rest_id free, columns present, global switches noted, menu sanity |
| restaurant_master | `01_restaurant_master.sql` | Upsert; `service_hours_json` is what the web enforces (`"24:00"` is allowed as the end) |
| `{REF}_*` keys | `02_ordelo_config_crms_keys.sql` | Start with **`{REF}_WEB_ORDERING_PAUSED=true`**. Do **not** create `{REF}_APP_URL` |
| Test window | `03_prod_test_enable.sql` | Since R3.1 only the `TEST_PAYMENT_REST_REFS` append and the unpause matter (every order of a listed restaurant is a test payment); the allowlist row is ignored |
| Go live | `04_go_live.sql` | Real admins, live timeout, remove from `TEST_PAYMENT_REST_REFS`, unpause |
| Rollback | `99_rollback.sql` | L1 pause → L4 delete |

Per-restaurant keys read by code:

| Key | Read by | Missing means |
|---|---|---|
| `{REF}_WEB_ORDERING_PAUSED` | `availability.available` | not paused |
| `{REF}_WEB_MAX_DISCOUNT_PERCENT` | `monitoring` price audit | 0 % |
| `{REF}_DEFAULT_DELIVERY_PICKUP_TIME` / `_COLLECTION_` | `resolve_initial_restaurant_acceptance`, hooks | global `DEFAULT_*_PICKUP_TIME` |
| `{REF}_DELIVERY_TIMEOUT_TIME` | `process_delivery` | global `DELIVERY_TIMEOUT_TIME`, else 10 |
| `{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` | `process_restaurant_confirmation` | global default |
| `{REF}_APP_URL` | restaurant-app webhooks, stale-thread job | **leave out for web-only** (skipped safely) |

Global key (R3.1, D35): only `TEST_PAYMENT_REST_REFS`. Every order (web and WhatsApp) of a listed restaurant uses Stripe test; never list a restaurant with real customers. A restaurant is on the web when it is in the backend `RESTAURANTS` registry and frontend `webOrderingEnabled`; there is no allowlist row. Switches: `notebooks/db_queries/ordelo-agg-db-switch.sql`.

Caches: flags/CSV 60 s; `RestaurantMaster` 1 h, cleared with `POST /internal/cache/reset?rest_ref={REF}`.

## 3. Ordelo backend code (always needed)

`utils_common/web_ordering/common.py` → add `"{REF}": {"town": "{town}", "phone": "{public phone}"}` to `RESTAURANTS`. Without it, every `/web/*` call returns `unknown_restaurant`. The `town` must match the frontend `towns[0]`, because checkout `start()` rejects any other town.

**Town rule:** `/web/eligibility` sends a postcode to the town of the **first** deliverable restaurant in registry order. Restaurants that deliver to the same postcodes must share a town, otherwise the newcomer is hidden from the postcode flow (this is why BNAT moved to `orpington` with CRMS).

Run `pytest tests/utils_common/web_ordering/ && ruff check .`

## 4. Frontend (restaurant-frontend)

1. New town? Add it to `TOWNS` in `config/restaurants.ts`.
2. Add a `RESTAURANTS.{ref}` entry with: `name`, `tagline`, `apiName`, `orderApiName`, `contactPhone`, branding, `towns: ['{town}']`, `webOrderingEnabled: true`, **`webOnly: true`**, and optional `ordeloOffers` (absent means no discount).
3. `webOnly` (added for CRMS) makes `/` link to the `/town` page and `/restaurant/{ref}` redirect there. Keep the restaurant in `RESTAURANTS`, because checkout and payment-return look it up there.
4. Moving a restaurant between towns: the wrong-town URL 308s to the primary path (added for CRMS/BNAT), so old links survive.
5. `npm run lint && npm run build`, then check `/town/{town}`, `/town/{town}/{slug}`, `/restaurant/{ref}` and `/`.

**restaurant-agents:** no changes for a web-only restaurant.

## 5. Rollout and test checklist

1. G0: external prerequisites (§1) and pre-flight.
2. Deploy backend, then frontend. Run 01 and 02 (paused). Check the page renders and checkout says *paused*.
3. Run 03 (test window). With `?isTest3100=true`: a collection order and a delivery order through to capture. Also test admin Accept/Decline, the confirmation timeout, both kill switches, hours/cutoff, and that every order has `payment_mode='test'`. Check the next-day price audit. Re-pause.
   - Visitors without the parameter pay **live** while the restaurant is unpaused. Keep the window short.
4. G3: real admins (each has messaged the Ordelo WhatsApp number), live timeout. Run 04, then reset the cache.
5. Off switch: `{REF}_WEB_ORDERING_PAUSED=true` (no deploy, takes effect within 60 s).
