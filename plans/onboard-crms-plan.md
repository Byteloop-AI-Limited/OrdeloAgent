> Historical design/verification snapshot. Payment testing was superseded on 9 October 2026: new orders use test only with an exact `TEST3100` item, and test delivery offers are restricted to eligible overwatch riders. See the current test-orders guide.

# Onboarding plan: CRMS (Creams Orpington), web-only restaurant

| | |
|---|---|
| **Status** | Agreed 2026-10-05 (grilling session). Not executed. |
| **rest_ref** | `CRMS` (frontend id / slug `crms`) |
| **Storefront URL** | `/town/orpington/crms` |
| **Channel** | Web only. No WhatsApp agent, no restaurant-agents app, no restaurant-specific UI |
| **Repos touched** | OrdeloAgent (DB SQL + 1 registry line), restaurant-frontend (config + 1 small layout). **restaurant-agents: no changes** |
| **SQL** | [`notebooks/db_queries/restaurant_queries/onboarding_crms/`](../notebooks/db_queries/restaurant_queries/onboarding_crms/) (run manually by the owner) |
| **Reusable runbook** | [`docs/onboarding-web-only-restaurant.md`](../docs/onboarding-web-only-restaurant.md) |

---

## 1. Decisions (from the grilling session)

| # | Decision | Notes |
|---|---|---|
| D1 | New town **`orpington`**; CRMS lives at `/town/orpington/crms` | Discovery only. Delivery eligibility always comes from pricing. |
| D1b | **Move BNAT to `orpington` too** (frontend + backend) | `/web/eligibility` picks the town of the *first* deliverable restaurant (`availability.py:224`). With BNAT in `salisbury`, BR6 postcodes would be sent to `/town/salisbury`, where CRMS isn't listed. Old `/town/salisbury/bnat` links get a 308 redirect (§B.4). |
| D2 | Payment service **already knows CRMS** (Stripe account, payout, URLs) | Plan only verifies it (G0). Why it matters: an unknown `restRef` falls back to ELAS (plan F13). |
| D3 | **Delivery + collection from day one** | `CRMS_WEB_DELIVERY_PAUSED=false`; usable as a delivery-only switch. |
| D4 | **Manual confirmation** (`auto_accept=false`) over Ordelo admin WhatsApp | Test phase admin `447448440754` (owner, **temporary**); real Creams staff numbers swapped in at go-live (04). |
| D5 | Menu service (`MENU_API_URL` = restaurant.byteloop.ai) **already serves `crms`** from `crms_menu` | Verified in G0. The temporary `app/test-crms-menu/` page is deleted. |
| D6 | **No discount at launch** | No `ordeloOffers`; `CRMS_WEB_MAX_DISCOUNT_PERCENT=0` (strict nightly price audit). |
| D7 | restaurant_master values supplied by owner | See §A.1. rest_id `447595246457`; public phone `01689838792`. |
| D8 | Timings copied from BNAT | Pickup 17/17, dispatch timeout 5. **Confirmation timeout 3 min for the test phase** (BNAT uses 0.5), reviewed at go-live. |
| D9 | Branding: minimal now | Tagline "Creams Cafe is the ultimate dessert destination", Creams-like primary colour; logo/hero later (S3 `ordelo-restaurants/crms/`). |
| D10 | Rollout: **straight to production test** | Accepted risk: while CRMS is unpaused for testing, a visitor without `?isTest3100=true` pays live. Keep the window short. |
| D11 | Code committed **directly on current branches** | OrdeloAgent `release/ordelo-agg`, frontend `feature/r3-ordelo-agg`. |
| D12 | New frontend flag **`webOnly: true`** | `/` links web-only restaurants to their `/town` page, and `/restaurant/crms` redirects there. Reusable. |
| D13 | **No `CRMS_APP_URL`** | ADR-0003: web orders never call restaurant apps. `job_terminate_stale_active_threads` skips restaurants with no base URL. |

### What "web-only" means in this codebase (facts checked)

- Web checkout gates, in order (`utils_common/web_ordering/availability.py::available`):
  1. `rest_ref` in the backend registry `RESTAURANTS` (`utils_common/web_ordering/common.py`). **Code**, else `unknown_restaurant`.
  2. Row in `restaurant_master`.
  3. `rest_ref` in `ordelo_config.WEB_ORDERING_ENABLED_REST_REFS` (global CSV; empty means all web paused).
  4. Global flags `PAYMENT_INBOX_ENABLED`, `ORDER_CREATE_RPC_ENABLED`, `WEB_LATE_PAYMENT_GUARD_ENABLED`.
  5. `{REF}_WEB_ORDERING_PAUSED`, and for delivery `{REF}_WEB_DELIVERY_PAUSED`.
  6. `service_hours_json` with cutoff `max(15, {delivery|takeaway}_order_cutoff_minutes)`.
- Flag/CSV reads are cached for **60 s**. `RestaurantMaster.from_rest_ref` (used by admin WhatsApp flows) caches for **1 h**: reset it with `POST /internal/cache/reset?rest_ref=CRMS`.
- Restaurant confirmation, receipts and rider dispatch for web orders run from Ordelo using `restaurant_master.admins` and the `CRMS_*` timing keys. Nothing goes to restaurant-agents.

---

## 2. Part A: Ordelo database changes (run manually)

Files live in `notebooks/db_queries/restaurant_queries/onboarding_crms/`. Each one is a transaction you can turn into a dry run (`COMMIT` → `ROLLBACK`), and each is idempotent.

| File | When | What |
|---|---|---|
| `00_preflight_readonly.sql` | Any time before 01 | Checks CRMS/rest_id don't exist, the columns exist, and the current global web switches. Menu sanity: counts, bad prices, duplicate titles (the price audit matches by title). |
| `01_restaurant_master.sql` | Before or after deploy (harmless alone) | Upserts the CRMS row (§A.1). |
| `02_ordelo_config_crms_keys.sql` | With 01 | 7 `CRMS_*` keys; **`CRMS_WEB_ORDERING_PAUSED=true`**. |
| `03_prod_test_enable.sql` | **After** both deploys | Appends CRMS to `WEB_ORDERING_ENABLED_REST_REFS` and `retired restaurant-wide payment switch` (never overwrites), unpauses, has a query to inspect test orders, and a commented re-pause block. |
| `04_go_live.sql` | After the G3 gate | Real admins, live confirmation timeout, removes CRMS from `retired restaurant-wide payment switch`, unpauses. Refuses to commit while `<TODO_…>` placeholders remain. |
| `99_rollback.sql` | If needed | L1 pause all / L2 pause delivery / L3 remove from global lists / L4 full delete (only if no orders). |

### A.1 `restaurant_master` row

| Column | Value | Notes |
|---|---|---|
| rest_ref | `CRMS` | VARCHAR(4) PK |
| rest_id | `447595246457` | UNIQUE; pre-flight checks for collisions |
| rest_name | `Creams Orpington` | |
| rest_email | `admin@byteloop.ai` | |
| admins | `['447448440754']` | **Temporary**, replaced in 04 |
| house_number / building_name | `Unit 75 & 77` / `The Walnuts Shopping Centre` | |
| street_name / city / postcode | `High St.` / `Orpington` / `BR6 0TW` | |
| lat / lon | `51.37657021668398` / `0.1010799851892783` | Origin for the delivery pricing quote |
| service_hours_json | `11:00–24:00` every day | Evaluator accepts end `24:00` (≤ 2880 min) |
| delivery_ / takeaway_order_cutoff_minutes | `15` / `15` | Last web order is 23:45 |
| collection_commission | `0.10` | |
| auto_accept | `false` | Manual Accept/Decline |
| rest_stale_active_threads_minutes | `10` | Same as BNAT |
| restaurant_start_time / end_time | `11` / `23.59` | Legacy WhatsApp columns, not read by web |

### A.2 `ordelo_config` keys

| Key | Value | Set in | Purpose |
|---|---|---|---|
| `CRMS_DEFAULT_DELIVERY_PICKUP_TIME` | `17` | 02 | Minutes; used when acceptance is automatic/timeout |
| `CRMS_DEFAULT_COLLECTION_PICKUP_TIME` | `17` | 02 | Minutes |
| `CRMS_DELIVERY_TIMEOUT_TIME` | `5` | 02 | Rider dispatch timeout (minutes) |
| `CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` | `3` → `<live>` | 02 → 04 | Admin confirmation timeout (minutes) |
| `CRMS_WEB_MAX_DISCOUNT_PERCENT` | `0` | 02 | Nightly web price-audit floor |
| `CRMS_WEB_ORDERING_PAUSED` | `true` → `false` | 02 → 03/04 | Per-restaurant kill switch |
| `CRMS_WEB_DELIVERY_PAUSED` | `false` | 02 | Delivery-only kill switch |
| `WEB_ORDERING_ENABLED_REST_REFS` | `+CRMS` | 03 | Global allowlist (append) |
| `retired restaurant-wide payment switch` | `+CRMS` → `−CRMS` | 03 → 04 | Honour `?isTest3100=true` |
| ~~`CRMS_APP_URL`~~ | not created | n/a | D13 |

> Caution: the global PAUSE profile in `notebooks/db_queries/ordelo-agg-db-switch.sql` **overwrites** `WEB_ORDERING_ENABLED_REST_REFS` (sets it to `''`) and `retired restaurant-wide payment switch` (`'BNAT'`). If anyone runs it, re-run the 03 append for CRMS.

### A.3 Ordelo backend code (required with Part A)

The DB rows alone are not enough: the backend registry is a hardcoded allowlist.

`utils_common/web_ordering/common.py`
```python
RESTAURANTS = {
    "ELAS": {"town": "salisbury", "phone": "01722656888"},
    "SFCS": {"town": "salisbury", "phone": "01722433714"},
    "BNAT": {"town": "orpington", "phone": "01689637476"},   # D1b: was salisbury
    "CRMS": {"town": "orpington", "phone": "01689838792"},   # new, web-only
}
```
Effects: allows `/web/*` for CRMS; checkout `start()` requires `town_slug == "orpington"`; the nightly price audit now covers `crms_menu` and reads `CRMS_WEB_MAX_DISCOUNT_PERCENT`.

Tests (`tests/utils_common/web_ordering/test_web_contract.py`):
- add `test_registry_towns_and_phones`: every entry has a non-empty `town` and `phone`, CRMS and BNAT are `orpington`.
- add an eligibility test: with BNAT and CRMS deliverable, `town_slug == "orpington"`.
- run `pytest tests/utils_common/web_ordering/ && ruff check .`

Live web sessions created under `salisbury` for BNAT expire after 2 h (`web_session_meta.expires_at`). Deploy outside BNAT's busy hours. Existing order pages use the stored `page_path`, so they are unaffected.

---

## 3. Part B: UI changes (restaurant-frontend, `feature/r3-ordelo-agg`)

### B.1 `config/restaurants.ts`: new `webOnly` field (D12)
```ts
export interface RestaurantConfig {
  // ...
  /** Web storefront only: no WhatsApp agent. `/` links to the /town page and /restaurant/[id] redirects there. */
  webOnly?: boolean
}
```

### B.2 `config/restaurants.ts`: town + restaurant
```ts
export const TOWNS: Record<string, TownConfig> = {
  salisbury: { slug: 'salisbury', name: 'Salisbury', blurb: 'Local restaurants delivering across Salisbury' },
  orpington: { slug: 'orpington', name: 'Orpington', blurb: 'Local restaurants delivering across Orpington' },
}

// in RESTAURANTS
  crms: {
    name: 'Creams Orpington',
    tagline: 'Creams Cafe is the ultimate dessert destination',
    apiName: 'crms',          // menu service ?restaurant_name=crms (crms_menu)
    orderApiName: 'crms',     // → rest_ref CRMS for /web/* and order numbers
    contactPhone: '01689838792',
    primaryColor: '#E4007C',  // Creams-like pink; adjust when brand assets arrive
    template: 'default',
    // TODO(branding): logo + heroImage from s3 ordelo-restaurants/crms/
    towns: ['orpington'],
    webOrderingEnabled: true,
    webOnly: true,
    // no ordeloOffers: no discount (D6)
  },
```
And BNAT (D1b): `towns: ['salisbury']` → `towns: ['orpington']`.

### B.3 Web-only routing (D12)
- `app/page.tsx` (legacy home): for `config.webOnly`, set the card's link to `getPrimaryRestaurantPath(id, config)` instead of `/restaurant/${id}` (or hide the card; linking is preferred).
- New `app/restaurant/[id]/layout.tsx` (server component; `page.tsx` is a client component and can't `redirect()` on the server):
```tsx
import { redirect } from 'next/navigation'
import { getPrimaryRestaurantPath, getRestaurantConfig } from '@/config/restaurants'

export default function RestaurantLayout({ children, params }: { children: React.ReactNode; params: { id: string } }) {
  const config = getRestaurantConfig(params.id)
  if (config?.webOnly) {
    const path = getPrimaryRestaurantPath(params.id, config)
    if (path) redirect(path)
  }
  return children
}
```
- Checkout (`app/(web)/checkout/page.tsx`) and `PaymentReturn` resolve the restaurant through `getAllRestaurants()`, so CRMS must stay in `RESTAURANTS`. Don't filter it out there.

### B.4 Wrong-town redirect (needed by D1b)
`app/(web)/town/[town]/[rest]/page.tsx`: today a restaurant opened under a town it isn't in returns 404. Change it to a 308 to its primary path so `/town/salisbury/bnat` keeps working:
```tsx
if (!town || !found) notFound()
if (found.redirectTo) permanentRedirect(`/town/${town.slug}/${found.redirectTo}`)
if (!found.config.towns?.includes(town.slug)) {
  const primary = getPrimaryRestaurantPath(found.id, found.config)
  if (primary) permanentRedirect(primary)
  notFound()
}
```

### B.5 Clean-up
- Delete the untracked `app/test-crms-menu/` (temporary preview reading `crms_menu` directly).

### B.6 Checks
`npm run lint && npm run build`. Then manually:
- `/town` → "Collecting instead?" lists **Orpington**
- `/town/orpington` lists Burger Nation + Creams Orpington
- `/town/orpington/crms` renders the menu (menu service), the phone 01689838792 and no discount banner
- `/town/salisbury/bnat` → 308 `/town/orpington/bnat`
- `/restaurant/crms` → `/town/orpington/crms`
- `/` shows CRMS linking to `/town/orpington/crms`
- the sitemap (live mode) includes `/town/orpington` and `/town/orpington/crms`

---

## 4. Execution order

### 4.1 Gate G0: external verification (no changes)
- [ ] Payment service: CRMS is in its restaurant config (Stripe account/payout destination, success/cancel URLs) **in both test and live**. If not, stop: payments would fall back to ELAS.
- [ ] Menu service: `GET ${MENU_API_URL}?restaurant_name=crms` returns categories/items matching `crms_menu`.
- [ ] Pricing service: a quote with `rest_ref: "crms"` and the CRMS lat/lon returns a `car` option for a BR6 postcode (Ordelo sends `rest_ref` lower-case).
- [ ] Rider cover for Orpington confirmed (delivery from day one).
- [ ] Run `00_preflight_readonly.sql`; all checks as expected.

### 4.2 Build and deploy
1. OrdeloAgent: A.3 change + tests → commit on `release/ordelo-agg` → deploy.
2. restaurant-frontend: Part B → commit on `feature/r3-ordelo-agg` → deploy.
3. Run `01_restaurant_master.sql`, `02_ordelo_config_crms_keys.sql` (CRMS still **paused**).
4. Smoke (paused): `/town/orpington/crms` renders and the menu loads; checkout shows *paused*, not *unknown restaurant*.

### 4.3 Production test window (D10)
Run `03_prod_test_enable.sql` §3A, wait about 60 s, then with **`?isTest3100=true`**:
- [ ] **Collection** test order: Stripe test checkout → `food_order.origin_channel='web'`, `payment_mode='test'` → Accept/Decline WhatsApp arrives at `447448440754` → accept with a pickup time → capture at the pickup boundary (ADR-0002) → web order page updates.
- [ ] **Delivery** test order (BR6 address): quote shown → pay → admin accepts → rider dispatch created (`CRMS_DELIVERY_TIMEOUT_TIME` respected) → capture on rider accept.
- [ ] **Confirmation timeout**: leave one order unanswered for over 3 min and check the timeout path.
- [ ] **Decline** path: payment cancelled; no WhatsApp to the (non-existent) customer.
- [ ] **No restaurant-app call**: logs show the `payment-complete` web branch and no `CRMS_APP_URL` lookup error.
- [ ] **Opening hours**: before 11:00 or after 23:45, the storefront shows closed and `/web/orders` rejects.
- [ ] **Kill switches**: `CRMS_WEB_DELIVERY_PAUSED=true` blocks delivery only; `CRMS_WEB_ORDERING_PAUSED=true` blocks both (each within 60 s).
- [ ] **BNAT regression**: `/town/orpington/bnat` checkout start works (town check now `orpington`).
- [ ] 3B query: every CRMS order is `payment_mode='test'`. If any is `live`, refund it and re-pause.
- [ ] Next morning: the price audit ran with no CRMS alerts (or only expected ones).
- [ ] Re-pause (03 §3C) until G3.

### 4.4 Gate G3: go-live
- [ ] Creams staff admin numbers collected; each has messaged the Ordelo WhatsApp number.
- [ ] Live `CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` agreed.
- [ ] Fill the `<TODO_…>` values in `04_go_live.sql` → run → `POST /internal/cache/reset?rest_ref=CRMS`.
- [ ] One real low-value live order (collection), then refund it if needed.

### 4.5 Rollback
`99_rollback.sql` Level 1 (`CRMS_WEB_ORDERING_PAUSED=true`) is the normal off switch, needs no deploy and takes effect within 60 s. Code revert is only needed for full removal (Level 4).

---

## 5. Open items / follow-ups
- Brand assets (logo, hero) → S3 `ordelo-restaurants/crms/` → add to `RESTAURANTS.crms`.
- The `TOWNS` / backend `RESTAURANTS` duplication (frontend config vs `common.py`) is a known D18 trade-off. A future step is a single DB-backed registry.
- The `/web/eligibility` "first deliverable restaurant's town" rule is fragile once a postcode is deliverable by restaurants in two towns. Revisit when a third town arrives.
- R3 launch gates in `docs/releases/ordelo-agg-r3-production-handover-2026-10-02.md` still apply to web ordering as a whole.
