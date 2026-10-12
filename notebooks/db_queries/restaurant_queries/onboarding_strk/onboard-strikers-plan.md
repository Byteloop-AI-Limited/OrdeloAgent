# Strikers onboarding — preparation draft

Prepared 2026-10-11. Local artifacts only: no SQL executed, no deployment, no
checkout enabled, no backend/frontend restaurant registration changed yet.

## Identity and website evidence

Verified directly from the user's open Google Chrome window at
[strikersbar.com](https://strikersbar.com/) on 2026-10-11. The website works there;
the earlier failures were specific to the web tool and local shell DNS access.
The official site's contact details and hours supersede the earlier third-party
listing. Structured browser-observed facts and drinks prices are retained in
`notebooks/db_queries/restaurant_queries/onboarding_strk/website_source.json`.

| Field | Official website value / status |
| --- | --- |
| Name | Strikers Sports Bar |
| Address | 40b, The Walnuts, High Street, Orpington, Kent BR6 0TW |
| Public phone | 01689 637100 |
| Email | hello@strikersbar.com |
| Bar opening hours | Sun–Thu 12:00–23:30; Fri–Sat 12:00–00:30 next day |
| Food service hours | Daily 12:00–21:30; user confirmed both ordering cutoffs as 15 minutes on 2026-10-12 |
| Proposed rest_ref / API id | `STRK` / `strk` — check collision and confirm before executing SQL |
| Proposed primary route | `/town/orpington/strk` |
| Channel | Awaiting web-only versus web + WhatsApp agent decision |
| Latitude/longitude | User confirmed 2026-10-12: 51.37693075218233, 0.10113928953415006 |
| Operational admins | User confirmed 2026-10-12: `447448440754` |
| Collection commission | User confirmed 2026-10-12: `0.1` (10%) |
| Stale active-thread timeout | User confirmed 2026-10-12: 10 minutes |
| rest_id | Unresolved; nullable in schema, public landline is not automatically a WhatsApp identity |
| Logo/hero URLs | Unresolved; menu's red/blue style is only a branding cue |

## Menu evidence

The supplied image is preserved as `source-menu.png` under the SQL bundle.
`menu_source.json` transcribes **49 dishes across eight sections**, prices and
descriptions, printed V/VE markers, and explicit option text. The section counts
are Warm Up 6; Kick Off 13; Main Event 8; Star Burgers 3; On The Green 4;
Pass The Pizza 5; Off Side 4; Sweet Victory 6.

`menu.sql` creates `public.strk_menu` with the shared schema from
`ordelo_datamodels/menu.sql`. Numeric IDs are proposed local identifiers.
SKUs follow the user's item-name convention: trim and lowercase the name,
replace runs of spaces/special characters with one underscore, and remove edge
underscores. Examples: `Fish & Chips` → `fish_chips`; `Half-Time Skinny Fries` →
`half_time_skinny_fries`. Only ASCII letters/digits are retained; the accented
ending in `Affogato Al Caffè` produces `affogato_al_caff` under this rule.
All 49 normalized SKUs are unique. Menu currency GBP is
confirmed as GBP by the official website's £ prices. Seed rows are **out of stock**
until ordering availability is confirmed. No discounts or item image URLs are
invented, and no TEST3100 product has been added to the supplied menu.

The optional +£2 onion rings appears under all burgers. Required single-choice
sauces for wings/thighs and accompaniment for sticky toffee pudding are proposed
frontend-compatible JSON from the printed choices; confirm no surcharge and
selection rules. Clarify plain/butter naan and available three-scoop ice cream
flavours before making those products orderable. Diet markers retain the image's
claims only; no allergen assurances are inferred.

### Official website versus supplied image

The user confirmed the supplied image is the **authoritative food menu**.
Its prices, names, descriptions, dietary markers and printed options govern the
seed. The website confirms 49 food dishes and the V=vegetarian / VG=vegan legend;
the differences below are retained for reference and do not block menu-source selection:

| Item | Supplied image | Official website |
| --- | --- | --- |
| Stadium Loaded Nachos | £7.25; salsa, guacamole, jalapeños and herbs | £6.00; cheese nachos with herbs |
| Onion Rings | £4.75; V | £4.85; VG |
| Chilli Con Carne | Served with bread | Served with white rice |
| Pork Spare Ribs | Title: Pork Spare Ribs | Title: Spare Pork Ribs |
| Pepperoni | Fior di latte mozzarella | Mozzarella (type unspecified) |
| Burgers | All served with skinny fries; +£2 onion rings across section | Smash explicitly served with chips; fries absent from other descriptions; extra shown beside crispy chicken burger |

Keep the image's prices, diet claims and product names: price audit joins titles.
Use its section-wide +£2 onion rings for all burgers. Option constraints remain
proposed as noted above. `website_source.json` retains differing website values
as historical comparison only.

The website also lists **90 drink entries in 17 sections**, including multi-size
wine/beer/spirit prices. They are captured separately; no drinks were added to
the food seed. Decide which drinks, sizes and variants are offered for delivery
or collection before adding products. The bar's later hours must not extend the
food ordering schedule.

## Operational decisions still needed

- Confirm rest_ref/API identifier and channel; venue/website identity is now verified.
- Confirm ordering availability and any delivery/collection exclusions.
- Supply acceptance mode, rest_id if used, pickup defaults, dispatch and
  confirmation timeouts. Coordinates, admin, commission, stale-thread timeout
  and both ordering cutoffs were confirmed by the user on 2026-10-12.
- Confirm fulfilment modes and delivery coverage/rider support if delivery launches.
- Confirm ordering availability, option constraints, drinks scope and any ordering
  offers. Food source/price/diet discrepancies are resolved in favour of the image.
- Identify the correct payment account/payout/return URL mapping in current test
  and live payment services; a new DB row does not supply this mapping.

## Prepared SQL and execution order

Bundle: `notebooks/db_queries/restaurant_queries/onboarding_strk/`.

1. Review `00_preflight_readonly.sql`: actual collisions, columns/constraints,
   existing configuration and menu-table existence. No query results are claimed.
2. Complete `01_restaurant_master.sql`. The insertion remains commented out while
   required data/operational decisions are missing; its verification query is safe.
3. Apply the reviewed pause in `02_ordelo_config_strk_keys.sql` before registering
   a public backend/frontend route. Other timing/discount values remain proposals
   requiring decisions, not implicit inherited CRMS settings.
4. Create menu table via `menu.sql`, then run reviewed `menu_seed.sql` only for a
   fresh empty table. The seed refuses a nonempty table and does not overwrite it.
   Use `menu_verify.sql` to check counts, prices, duplicates and option structure.
5. Update backend/frontend registration after channel/identity confirmation;
   verify the deployed pause and upstream menu/payment support before any window.
6. `03_prod_test_enable.sql` and `04_go_live.sql` currently contain verification
   queries and commented mutation examples. Do not enable until their gates pass.
7. `99_rollback.sql` restores the scoped pause; no destructive deletion prepared.

Manual SQL uses standalone statements and verification queries. No retired global
allowlist, restaurant-wide payment selector or delivery-only pause is generated.
The proposed REF/slug is shared by all files; change consistently if rejected.

## Code changes to implement once identity/channel is confirmed

Backend: `utils_common/web_ordering/common.py::RESTAURANTS`, proposed entry:

```python
"STRK": {"town": "orpington", "phone": "01689637100"},
```

Frontend: sibling `restaurant-frontend/config/restaurants.ts`, proposed `strk`
entry with `apiName: 'strk'`, `orderApiName: 'strk'`, `towns: ['orpington']`,
name/contactPhone, agreed branding, and `webOrderingEnabled: true`. If web-only,
use `webOnly: true` and omit `STRK_APP_URL`; no restaurant-agents app changes.
Check `/town/orpington`, `/town/orpington/strk`, `/restaurant/strk`, checkout and
payment returns. Keep existing restaurants and routes unchanged.

Price audit constructs `{rest_ref.lower()}_menu`; using full slug `strikers` as
API id with REF STRK would need an explicit mapping and is not assumed here.
Verify the menu service actually recognizes `restaurant_name=strk`.

## Launch gates

- Correct deployed menu data and mapping; live/test payment destinations confirmed.
- Agreed service hours, admin operation, pricing and rider coverage for requested modes.
- Backend existing web-ordering tests and relevant frontend lint/build pass.
- Paused deployed checkout confirmed; authorize a short test window separately.
- Exact normal priced `TEST3100` accepted item selects test for new orders; normal
  baskets remain live. Test deliveries go only to eligible overwatch riders.
- Verify collection/delivery capture boundaries, admin accept/decline/timeout,
  receipt/order page, pause/hours/cutoff and price audit. Re-pause after testing.
- Operational admins/timings finalized and restaurant cache reset with the actual
  authenticated endpoint contract before authorized go-live.

This preparation is not a finding that Strikers is ready for checkout.
