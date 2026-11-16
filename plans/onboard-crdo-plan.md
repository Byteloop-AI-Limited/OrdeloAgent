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

## TODO: open items and gates (updated 2026-11-12)

Status: SQL applied, menu manager, backend and frontend deployed. Storefront is live and themed. CRDO is **paused**
(`ordering_paused` confirmed on the production eligibility endpoint for delivery and collection). Not ready for checkout.

### Done
- [x] SQL applied: `crdo_menu` (146 rows), `restaurant_master` row, `CRDO_*` keys with the pause set to `true`
- [x] Deploy order respected: SQL before the backend deploy (price audit safe)
- [x] Menu manager, OrdeloAgent (registry `CRDO`) and frontend deployed
- [x] Storefront theme (`config/storefronts/crdo.json`, registered in `index.ts`); production storefront loads themed
- [x] Pause verified at the deployed endpoint

### Open (in gate order)
- [ ] **Payment (blocker):** `payment-service` falls back to ELAS for an unknown ref. Add CRDO's Stripe account, payout and return URLs to the deployed config. No test order before this.
- [ ] **Delivery pricing and riders:** confirm the quote from CRDO's coordinates and Orpington rider coverage (including overwatch riders for test orders). Cannot be tested while paused.
- [ ] **Test window:** unpause with `03_prod_test_enable.sql` (`UPDATE ... 'false'`, not a delete); place collection and delivery orders with exact `TEST3100`; check `payment_mode='test'`, admin accept/decline/timeout, order page and price audit; then re-pause.
- [ ] **Admin alerts:** confirm all 3 admins get CRDO alerts on Telegram; reset the restaurant cache (`/internal/cache/reset?rest_ref=CRDO`) after any admin change.
- [ ] **Go live:** run `04_go_live.sql` as the final step, only after every gate above passes and the owner approves.
- [ ] **Logo:** upload `logo-full.png` (200x75, a larger file would look better) to `s3://ordelo-restaurants/crdo/`, then add it (and optionally a hero) to `crdo.json` and `restaurants.ts`.
- [ ] **Menu images:** Deliveroo CDN URLs (about 200 KB each, `unoptimized`). Decide whether reuse is acceptable or host copies under `ordelo-restaurants/crdo/`.

### Housekeeping (separate from CRDO)
- [ ] PR #79 pulled three unrelated `Claude outputs/` files into `dev`; remove them.
- [ ] STRK is missing from the backend `RESTAURANTS` registry.
- [ ] `STRK_WEB_MAX_DISCOUNT_PERCENT=0` against its 5% offer makes the price audit flag its discounted orders.
- [ ] Add the reciprocal reference to `onboard-storefront` in the OrdeloAgent `ordelo-restaurant-onboarding` skill.

## Found during research (not changed)

- STRK is missing from backend `RESTAURANTS` on fetched `origin/dev`, although the frontend enables it.
- `STRK_WEB_MAX_DISCOUNT_PERCENT = 0` against STRK's 5% storefront offer makes the price audit flag its discounted orders.

This preparation is not a finding that CRDO is ready for checkout.
