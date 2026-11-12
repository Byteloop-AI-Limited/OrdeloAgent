# Crispy Dosa Orpington (CRDO) onboarding: web only

Prepared 2026-11-12. **Prepared, not executed:** no SQL has been run, nothing deployed, checkout stays
paused, nothing committed. Bundle: `notebooks/db_queries/restaurant_queries/onboarding_crdo/`.

## Confirmed inputs (from the owner, 2026-11-12)

| Field | Value |
| --- | --- |
| rest_ref / API id | `CRDO` / `crdo`; `rest_id` `CRDO01` (STRK pattern). No collision found by read-only checks |
| Name / address | Crispy Dosa; 273 High Street, Orpington, BR6 0NW |
| Public phone | 01689332664 |
| lat / lon | 51.374745918702864, 0.09894222729275585 |
| Hours | Mon-Fri 10:00-22:00; Sat-Sun 09:00-22:00 |
| Channel | Web only (`webOnly: true`, no `CRDO_APP_URL`) |
| Admins and timings | Copied from STRK's live rows: 3 admins, auto_accept, commission 0.1, cutoffs 15/15, stale threads 10, pickup 30/30, dispatch timeout 5, confirmation timeout 3, Telegram alert offsets `0,15,30,35` |
| Web offer | 5% (`ordeloOffers`), so `CRDO_WEB_MAX_DISCOUNT_PERCENT = 5` (STRK's 0 is not copied) |
| Menu | 146 Deliveroo items, 24 categories, Deliveroo prices and image URLs; 2 out of stock (Telugu Thali, Madras Thali) |

## Files

| File | Status |
| --- | --- |
| `00_preflight_readonly.sql`, `01_restaurant_master.sql`, `02_ordelo_config_crdo_keys.sql` | Written. 01 and 02 loaded into a throwaway local Postgres (test schema extended with the real STRK columns) |
| `core/menus.sql`, `menu_seed.sql`, `menu_verify.sql` | Written; seed loaded locally: 146 rows, counts per category, duplicate and addons checks as expected; a second run inserts 0 rows |
| `build_menu_seed.py` + `deliveroo/*.csv` | Generator and the validated Deliveroo CSVs (146 items, 18 groups, 51 options) |
| `03_prod_test_enable.sql`, `04_go_live.sql`, `99_rollback.sql` | Verification queries; mutations commented out. Unpause is `UPDATE ... 'false'`, not a delete |

Run order for the owner: `00` -> `01` -> `02` (pause first) -> `core/menus.sql` -> `menu_seed.sql` -> `menu_verify.sql`.

## Code changes (branches `feat/onboard-crdo`, menu manager `feat/crdo-menu`)

- OrdeloAgent `utils_common/web_ordering/common.py`: `RESTAURANTS["CRDO"]` + test assert. `pytest tests/utils_common/web_ordering`: 137 passed.
- restaurant-menu-manager `internal/storage/repository.go`: `"crdo": "crdo_menu"`. `go test ./...` compiles (no test files).
- restaurant-frontend `config/restaurants.ts`: `crdo` entry. `tsc` and lint clean. `npm test` fails identically on the baseline (Node v26, jsdom `localStorage`), so it proves nothing either way.

## Open items and gates

1. **Storefront theme not done:** no official brand site found; colours and logo/hero are needed from the owner. Without `config/storefronts/crdo.json` the restaurant uses the default Ordelo theme.
2. **Deploy order:** apply `core/menus.sql` and `01`/`02` BEFORE the backend deploy. The nightly price audit LEFT JOINs `{ref}_menu` for every registry ref in one `try`; a missing `crdo_menu` would stop the audit for all restaurants.
3. **Payment:** `payment-service` falls back to ELAS for an unknown ref. CRDO needs its Stripe account, payout and return URLs in the deployed config before any test order.
4. Delivery quotes from CRDO's coordinates and Orpington rider coverage; admin alerts reach all 3 admins; restaurant cache reset after any admin change.
5. Test window: exact `TEST3100` orders (ordelo-local-automatic-orders skill), then re-pause, then `04_go_live.sql`.
6. Menu images are Deliveroo CDN URLs (about 200 KB each, `unoptimized` images): confirm reuse is acceptable, or host copies under `ordelo-restaurants/crdo/` later.

## Found during research (not changed)

- STRK is missing from backend `RESTAURANTS` on fetched `origin/dev`, although the frontend enables it.
- `STRK_WEB_MAX_DISCOUNT_PERCENT = 0` against STRK's 5% storefront offer makes the price audit flag its discounted orders.

This preparation is not a finding that CRDO is ready for checkout.
