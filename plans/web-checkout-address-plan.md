# Web checkout address: plan

Status: agreed with the owner on 7 October 2026 (grilling session). Implemented the same evening (migration run by the owner; steps 2 and 3 built and unit-tested, uncommitted). Remaining: live end-to-end checks and deploy in the order below.
Decision record: `docs/adr/0008-web-checkout-address-never-blocks-checkout.md` (update it in step 3g).

## Hard gates (must hold after every step)

1. **No change of postcode sector.** The delivery address, the minimum-order price point and the rider pin all stay inside the postcode sector approved at checkout start (sector = outward code + first inward digit, e.g. `SP1 2`). The backend enforces this from its own stored postcode, not from anything the browser sends.
2. **The rider always gets a best-effort pin**, always inside that sector: door-level when Google has it, else road-level, else the postcode centroid. Checkout never fails because Google can't find the address text.

Agreed, not gates: the delivery fee may differ slightly from the postcode-step estimate (it is priced from the pin, see "Pricing" below). Coordinates never come from the browser.

## Decisions (grilling, 7 Oct 2026)

| # | Decision |
|---|---|
| D1 | Backend is the authority. New nullable `web_session_meta.postcode` holds the full approved postcode. `address()` ignores the request postcode and rejects a different sector with `postcode_mismatch`. DDL ships as a migration file; the owner runs it. |
| D2 | Fail closed: a delivery session with no stored postcode returns `409 checkout_restart_required`. |
| D3 | Rider pin, option (c): geocode the full address; if unusable, retry with street + town + postcode; if still unusable, postcode centroid. Never outside the sector. |
| D4 | The uncommitted work from 7 Oct is Phase 0; verify it against this plan before building on it. |
| D5 | For web orders whose pin is not `exact`, add a warning line to the rider's drop-off message. Restaurant note stays. |
| D6 | Deploy order: migration → restaurant-frontend → OrdeloAgent. |
| D7 | This plan lives here; pointer in the claude.ai project doc `claude/ordelo-web-ordering-decisions.md`. |

## Why (root cause, confirmed with live Google calls on 7 Oct)

- `Churchill Way E, Salisbury SP1 2AB` has no house numbers. The frontend required a house number or building name (`restaurant-frontend/app/api/web/address/route.ts`, old line 38). With a house name, Google returns `partial_match: true` on the right road (`types: ["route"]`, `GEOMETRIC_CENTER`), and the old `availability.geocode()` rejected every partial match. Without one, the frontend rejected the form. No way through.
- "Churchill Way East" vs "E" was not the cause: both geocode cleanly without a premises name.
- `1, Churchill Way East, SP1 2AB` and `20, Churchill Way East, SP1 2AB` both resolve to the same `RANGE_INTERPOLATED` point labelled `SP1 1HZ` (another sector), 426 m from the SP1 2AB centroid. This is why D3 retries street-only instead of trusting the door-level guess.

## Code map (current working tree, line numbers as of 7 Oct, uncommitted)

OrdeloAgent:
- `utils_common/web_ordering/availability.py`
  - `_google(address)` :121 — one Geocoding call; raises `invalid_address` on ZERO_RESULTS, `address_lookup_unavailable` (503) otherwise.
  - `_same_sector(expected_postcode, result)` :150 — compares Google's resolved `postal_code` sector.
  - `geocode(address, *, expected_postcode=None)` :169 — strict (rejects partial). Used by `eligibility()` :269/:277 and for the centroid.
  - `_EXACT_TYPES` :185, `locate(address, postcode)` :188 — centroid + pin + precision. Fallbacks at :204 and :208.
  - `pricing(row, location, total=0)` :217 — calls the pricing service.
- `utils_common/web_ordering/web_checkout.py`
  - `start(rest_ref, mode, town_slug, visitor_id, district=None)` :77; INSERT at :92.
  - `session()` :112, `address_display(value)` :126, `address()` :132 (`meta` :143, district check :170–177, `locate` call :181, snapshot :182–193).
  - `pricing_location(addr)` :202, `_PIN_NOTES` :213, `pin_note(addr)` :219.
  - `create()` :238 — address read :257, minimum priced :271, notes `pin_note(addr)` :349, `web_order_request` INSERT :378, `customer_master` INSERT (lat/lon = pin) just above it.
- `watomation/routers/web_hooks.py` — `Session` model :60–65 (no `extra="forbid"`, so unknown fields are ignored), `start` route :68–91 (calls `web_checkout.start` :82–88), `Address` model :94, `/address` route :112–119.
- `utils_common/web_ordering/common.py` — `WebError` :19, `query` :39, `one` (async psycopg pool; no `to_thread` needed).
- Fee path (shared with WhatsApp, do not change): `utils_common/order_management/food_order_pymodel.py` `from_order_number` :110 → `update_final_order_value_in_db` :230, which reads `customer_master.lat/lon` (:243–250) and prices the fee from it.
- Rider pin path: `ordelo_datamodels/jobs_n_functions/init_delivery.sql:113` copies `customer_master.lat/lon` into the delivery; `ordelo/agents/rider_agent.py` `send_dropoff_location` :426 reads `delivery_summary` (:451–458) and sends `send_location` (:459–465) plus `"Dropoff:\n" + customer_address` (:466–470). `rider_agent.py` has no `import asyncio` yet.
- Schema: `ordelo_datamodels/migrations/ordelo_agg_r3.sql:12–17` (`web_session_meta`), :18–21 (`web_order_request`, `address jsonb`).
- Tests: `tests/utils_common/web_ordering/test_web_contract.py` (helpers `_google_reply` :474, `_address_session` :519, `_google_replies` :554, `_result` :574; address/locate tests :499–680). Rider: `tests/ordelo/agents/test_rider_agent.py` `_runtime` :46, drop-off test :294–307. Fake client: `tests/fixtures/fake_supabase.py` (`register` :185; unregistered tables get the default response, :157–164).

restaurant-frontend:
- `app/api/web/checkout-sessions/route.ts` — eligibility for `loc.postcode` :44–54; session reuse rule `sameDistrict` :59–61; `startCheckout({... postcode_district: loc?.district ...})` :63–66; `keepAddress` :67–69; cookie :70–82.
- `lib/web/api.ts` — `startCheckout` input type :54–62 (needs `postcode?: string`), `captureAddress` :71–74, `liveRequest` :130.
- `lib/web/cookies.ts` — `LocCookie` :38–43 (`postcode`, `district`), `CheckoutCookie` :45–60.
- `app/api/web/address/route.ts` — field checks; postcode always from the checkout cookie.
- `components/ordelo/CheckoutFlow.tsx` — address fields :371–377 (autofill tokens already set), `orderError` :279 (`invalid_address` copy, `postcode_mismatch`/`checkout_restart_required` → "Enter your postcode" link :306–312).
- `lib/web/http.ts` `handleModeError` :16 — passes backend error codes and statuses through unchanged, so new backend 409/422 codes reach `CheckoutFlow` with no extra mapping.

## Phase 0 — verify the uncommitted work against this plan

Run `git diff` in both repos first. Expected uncommitted files: OrdeloAgent `availability.py`, `web_checkout.py`, `test_web_contract.py`, `docs/adr/0007-…md` (untracked, edited), `docs/adr/0008-…md` (new), `ordelo_datamodels/migrations/add_web_session_meta_postcode.sql` (new), this plan; restaurant-frontend `app/api/web/address/route.ts`, `components/ordelo/CheckoutFlow.tsx`. Note: `.git/stale-index-lock-claude` and a stray `.git/objects/57/tmp_obj_*` are harmless leftovers from a failed `git stash`; the owner can delete them. Do not run `git stash` in these folders (deletes are blocked, git leaves lock files).

| Check | Where | Verdict | Action |
|---|---|---|---|
| Premises optional, street + town required | `web_checkout.py` address(), frontend `route.ts` | Matches | Keep |
| Customer's text stored as typed and shown to rider | snapshot :182–193 | Matches | Keep |
| Minimum priced from centroid | `pricing_location` :202, `create()` :271 | Matches | Keep |
| Centroid is the **stored** postcode | `locate(display, value["postcode"])` :181 uses the **request** postcode | Gap (D1) | Step 3b |
| Sector gate on the backend | only district (outcode) check :170–177 | Gap (D1) | Step 3b |
| Fail closed without stored postcode | sessions without district skip the check | Gap (D2) | Step 3b |
| Pin never outside sector | `locate` falls back to centroid when `_same_sector` fails :206 | Matches | Keep |
| Street-only retry | missing | Gap (D3) | Step 3c |
| Restaurant note when pin not exact | `pin_note` :219, `create()` :349 | Matches | Keep |
| Rider warning line | missing | Gap (D5) | Step 3d |
| Frontend sends full postcode at start; reuse only for same postcode | `sameDistrict` :59–61 | Gap (D1/D6) | Step 2 |
| `[DEBUG-addr]` logging removed | both functions | Done | Keep |
| Async REST rule (CLAUDE.md) | address/locate use `requests` in `to_thread` and async psycopg | Matches | Keep |
| ADR 0007/0008 text | ADR 0008 says the backend checks only the district | Gap | Step 3g |
| Tests reflect D1/D2 | `test_address_district_check_skipped_without_delivery_district` :544 expects success with no district | Gap | Step 3f |

Phase 0 is done when the table above has been re-checked against the diff and nothing unexpected is in it.

## Step 1 — migration (owner runs it; no DDL from agents)

File: `ordelo_datamodels/migrations/add_web_session_meta_postcode.sql` (already written). Adds nullable `web_session_meta.postcode text`, a `NOT VALID` format check `^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$`, a column comment and commented rollback. Safe with current code (nothing reads or writes the column).

Verify after running (read-only):
```sql
select column_name, data_type, is_nullable from information_schema.columns
where table_name = 'web_session_meta' and column_name = 'postcode';
select conname from pg_constraint where conname = 'web_session_meta_postcode_format';
```

## Step 2 — restaurant-frontend (deploy after step 1, before step 3)

2a. `lib/web/api.ts:54–62` — add `postcode?: string` to the `startCheckout` input type. The live branch already JSON-serialises the whole input (:64–65); the fixture branch is unaffected.

2b. `app/api/web/checkout-sessions/route.ts`
- Replace the district reuse rule at :59–60:
  ```ts
  // Ordelo pins the full postcode on the session at start (ADR 0008), so a new postcode needs a new session.
  const samePostcode = mode !== 'delivery' || existing?.postcode === loc?.postcode
  ```
  and use `samePostcode` in `reusable` at :61.
- Pass the postcode at :63: `startCheckout({ ..., postcode_district: loc?.district, postcode: mode === 'delivery' ? loc?.postcode : undefined, ... })`. Keep `postcode_district` (the backend still stores and logs it).
- `keepAddress` at :69 stays; with `samePostcode` it is now always true when `reusable`. Leave it as a guard.
- Postcode format: `loc.postcode` is the backend's normalised eligibility postcode (`app/api/web/eligibility/route.ts:36` stores `result.postcode`, normalised at `web_hooks.py:50–53`); the backend re-normalises anyway (3a).

2c. Already done in Phase 0: house number optional in `app/api/web/address/route.ts`; labels "House number (if any)" and "House or building name (optional)" and `invalid_address` copy "Please enter your street and town." in `CheckoutFlow.tsx`.

Old backend + new frontend is safe: `Session` (`web_hooks.py:60`) ignores the unknown `postcode` field.

Checks: `npm run lint`, `npx tsc --noEmit -p .`. Manual: start checkout for SP1 2AB, go back, enter SP1 3TA → a new session (201, `reused:false`); same postcode again → reused (200).

## Step 3 — OrdeloAgent (deploy last)

### 3a. Store the postcode at checkout start

- `utils_common/web_ordering/common.py`: add shared helpers (used by 3a, 3b, availability):
  ```python
  POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}")

  def normalise_postcode(value):
      """'sp12ab' -> 'SP1 2AB'; None when not a UK postcode shape."""
      compact = "".join((value or "").upper().split())
      return compact[:-3] + " " + compact[-3:] if POSTCODE_RE.fullmatch(compact) else None

  def postcode_sector(value):
      """'SP1 2AB' -> 'SP12' (outward code + first inward digit, no space)."""
      compact = "".join((value or "").upper().split())
      return compact[:-2] if len(compact) >= 5 else ""
  ```
  Refactor `availability._same_sector` (:150) to use `postcode_sector`. The regex in `web_checkout.address()` and `web_hooks.eligibility` (:51) can use `POSTCODE_RE` (optional tidy-up; keep behaviour).
- `watomation/routers/web_hooks.py:60–65` — add `postcode: str | None = Field(default=None, max_length=10)` to `Session`; pass `body.postcode` to `web_checkout.start(...)` at :82–88.
- `web_checkout.start()` :77 — new keyword `postcode=None`. For `mode == "delivery"`: `postcode = normalise_postcode(postcode)`; if it is None, store NULL (the session then fails closed in `address()`; do not raise here, so a frontend without step 2 degrades to "Enter your postcode" instead of a 500). If both `postcode` and `district` are present and `postcode.split()[0] != district.upper()`, raise `WebError("postcode_mismatch")` (frontend bug guard). Add `postcode` to the INSERT at :92–104. Collection: store NULL.

### 3b. `address()` uses the stored postcode and fails closed

Replace the request-postcode handling in `web_checkout.address()` (:163–177) with:
```python
if meta.get("mode") == "delivery":
    stored = meta.get("postcode")
    if not stored:
        raise WebError("checkout_restart_required", 409)  # D2: pre-migration or pre-frontend sessions
    sent = normalise_postcode(value.get("postcode"))
    if sent and postcode_sector(sent) != postcode_sector(stored):
        logger.warning("[web-addr] rejected: sector {!r} differs from checkout sector {!r}",
                       postcode_sector(sent), postcode_sector(stored))
        raise WebError("postcode_mismatch")
    value["postcode"] = stored  # the server's postcode is the authority (D1)
else:
    value["postcode"] = normalise_postcode(value.get("postcode")) or ""  # collection: unchanged behaviour
```
- A unit difference inside the sector is overwritten silently with the stored postcode (frontend always sends the cookie postcode, so this only happens for a buggy caller).
- Keep the field-bounds check (:146–160) and the street/town requirement (:178–179) before calling Google.
- Logs never include the address text or full postcode (sector only).

### 3c. Street-only retry in `locate()` (D3)

Change the signature to `locate(address, postcode, *, street_address=None)`:
```python
async def locate(address, postcode, *, street_address=None):
    centroid = await geocode(postcode)                 # strict; raises invalid_address if the postcode itself fails
    for text, cap in ((address, None), (street_address, "street")):
        if not text or (cap and text == address):
            continue                                   # no premises given: the first call was already street-only
        try:
            result = await _google(text)
        except WebError as exc:
            if exc.status >= 500:
                break                                  # provider failure: don't spend a second call
            continue                                   # ZERO_RESULTS: try the street-only text
        pin = _usable_pin(result, postcode)            # None if outside sector or coarser than a road
        if pin:
            precision = "street" if cap else pin["precision"]
            return {"centroid": centroid, "pin": pin["location"], "precision": precision}
    return {"centroid": centroid, "pin": centroid, "precision": "postcode"}
```
- Extract `_usable_pin(result, postcode)` from the current checks at :205–215: inside sector via `_same_sector`, `types` intersecting `_EXACT_TYPES | {"route"}`, precision `exact` only for `_EXACT_TYPES` without `partial_match`, else `street`.
- Retry triggers: first result outside the sector, too coarse, or ZERO_RESULTS. A 5xx from Google skips the retry and uses the centroid. (Interpretation of D3: "unusable" covers more than "outside sector"; confirm with the owner if in doubt.)
- In `address()`: `street_address = address_display({"street": value["street"], "town": value["town"], "postcode": value["postcode"]})`, then `availability.locate(display, value["postcode"], street_address=street_address)`.
- Cost: at most 3 Geocoding calls per address save (centroid, full, street-only); usually 2.

Expected live results (re-run the probe in "Verification"):
| Input | Result |
|---|---|
| `Rose Cottage, Churchill Way East, Salisbury, SP1 2AB` | `street`, road point (51.064978, −1.788997) — first call, partial match in sector |
| `1, Churchill Way East, Salisbury, SP1 2AB` | `street`, same road point — first call lands in SP1 1HZ, retry succeeds |
| `Nowhere Lane, Atlantis, SP1 2AB` | `postcode`, centroid |

### 3d. Rider warning line (D5)

`ordelo/agents/rider_agent.py`:
- Add `import asyncio` to the imports (:37–62).
- Add next to `send_dropoff_location` (:426):
  ```python
  _PIN_WARNINGS = {
      "street": "⚠️ Map pin is on the street, not the door. Follow the address.",
      "postcode": "⚠️ Map pin is the postcode centre only. Follow the address.",
  }

  async def _web_pin_warning(client, order_number):
      """Rider warning for a web order whose pin isn't door-level; None otherwise.

      WhatsApp orders have no web_order_request row. Never blocks the drop-off.
      """
      try:
          rows = await asyncio.to_thread(
              lambda: client.table("web_order_request").select("address")
              .eq("order_number", order_number).limit(1).execute().data
          )
      except Exception:
          logger.exception("pin precision lookup failed")
          return None
      precision = ((rows or [{}])[0].get("address") or {}).get("pin_precision")
      return _PIN_WARNINGS.get(precision)
  ```
  `rider_agent.py` has no module logger (it only uses the async `get_wa_logger()` inside functions, e.g. :830); add `from loguru import logger` as other modules do (e.g. `availability.py:12`).
- In `send_dropoff_location`, after the summary fetch (:451–458): `warning = await _web_pin_warning(ctx.client_ordelo, order_number)`; message text at :466–470 becomes `"Dropoff:\n" + summary["customer_address"] + (f"\n\n{warning}" if warning else "")`.
- Leave the existing synchronous `delivery_summary` fetch as is (pre-existing violation, out of scope).
- The rider's precision source is the order's immutable snapshot (`web_order_request.address`, written in `create()` :378), not the editable checkout session.

### 3e. No change to pricing code

- Minimum: centroid via `pricing_location()` (Phase 0). Fee: shared WhatsApp path prices from `customer_master.lat/lon` = the pin; agreed acceptable and bounded to the sector by 3c.
- Pre-0008 snapshots (no `postcode_latitude`) keep pricing from their stored point (`pricing_location` fallback). After 2 hours none remain.

### 3f. Tests (`tests/utils_common/web_ordering/test_web_contract.py`, `tests/ordelo/agents/test_rider_agent.py`)

Update:
- `_address_session` (:519) — `meta` gains `"postcode": "SP1 2AB"`; parameter `postcode="SP1 2AB"`.
- `test_address_accepts_postcode_in_checkout_district` (:529) → `test_address_uses_stored_postcode_inside_sector`: request `SP1 2AB`, `sp12ab`, `SP1 2ZZ`, or no postcode → snapshot postcode is `SP1 2AB`.
- `test_address_rejects_postcode_outside_checkout_district` (:535) → `…_outside_checkout_sector`: `SP1 3TA`, `SP2 8AB`, `BR6 0TW` → `postcode_mismatch`, `locate` not awaited.
- `test_address_district_check_skipped_without_delivery_district` (:544) → split into `test_address_fails_closed_without_stored_postcode` (delivery, `postcode=None` → `checkout_restart_required`, status 409) and `test_collection_address_unchanged`.
- `test_address_saves_without_house_number_and_keeps_pin_and_centroid` (:639) — assert `locate` awaited with `street_address="Churchill Way East, Salisbury, SP1 2AB"`.

Add:
- `test_start_stores_normalised_postcode` (`web_checkout.start` with `"sp12ab"` → INSERT params contain `"SP1 2AB"`; patch `one`/`query` like other tests).
- `test_start_rejects_postcode_outside_district` (`postcode="SP2 8AB"`, district `SP1` → `postcode_mismatch`).
- `test_start_without_postcode_stores_null` (delivery, no postcode → no raise, NULL stored).
- `test_locate_retries_street_only_when_door_lands_outside_sector` (`_google_replies` keyed so `"1, Churchill"` → SP1 1HZ street_address, `"Churchill Way East, Salisbury"` → SP1 2AB route → precision `street`, three calls).
- `test_locate_retry_is_capped_at_street` (retry returns `street_address` in sector → still `street`).
- `test_locate_skips_retry_without_premises` (street_address == address → one address call).
- `test_locate_skips_retry_on_provider_error` (first call `OVER_QUERY_LIMIT` → centroid, no second address call).
- `test_normalise_postcode` / `test_postcode_sector` (parametrised; include `"SP10 1AA"` → `SP101`, not `SP1 0`).
- Rider (`test_rider_agent.py`, next to :294): `test_dropoff_warns_rider_when_web_pin_is_approximate` (register `web_order_request` select → `[{"address": {"pin_precision": "postcode"}}]`; last `send_message` text ends with the warning), `test_dropoff_has_no_warning_for_exact_or_whatsapp` (exact; empty data), `test_dropoff_survives_pin_lookup_failure` (register an `Exception` response; drop-off still sent).

Note: the existing drop-off test (:294) gets the fake's default response for `web_order_request`; it should pass unchanged.

### 3g. Docs

- `docs/adr/0008-web-checkout-address-never-blocks-checkout.md`: add the stored postcode as the sector authority, fail-closed, the street-only retry, the rider warning, and the deploy order. Remove "district" wording.
- `docs/adr/0007-…md:9`: change "Only the outcode (district) is compared, so no schema change was needed" to point at ADR 0008 (full postcode stored, sector compared).
- `plans/ordelo-agg-plan-cc.md:475` and `:1066` say only `postcode_district` is stored in meta. Add a dated note pointing at ADR 0008 (see "Privacy").

## Privacy

`plans/ordelo-agg-plan-cc.md:1066` recorded "only `postcode_district` is stored in meta". Storing the full postcode on `web_session_meta` changes that. Impact is low: `web_order_request.address` and `customer_master.postcode` already hold the full postcode for every order, and `web_session_meta` is service-role only (`ordelo_agg_r3.sql:34–38`, RLS on, `anon`/`authenticated` revoked). Record the change in ADR 0008.

## Verification

1. Unit tests in a Linux venv outside the repo (the repo's `.venv` is macOS):
   ```bash
   cd ~/mnt/OrdeloAgent
   UV_PROJECT_ENVIRONMENT=$HOME/ordelo-venv uv sync --frozen --python 3.13
   source $HOME/ordelo-venv/bin/activate && export PYTHONPATH="$PWD"
   python -m pytest tests/utils_common/web_ordering tests/ordelo/agents/test_rider_agent.py -q -p no:cacheprovider
   uvx ruff check utils_common/web_ordering ordelo/agents watomation/routers tests --select F --ignore F704
   ```
   `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column` fails in the full suite independently of this work.
2. Live Google probe (no app config needed; uses the frontend's key). Stub the config modules, then call `locate`:
   ```python
   import asyncio, os, sys, types
   ns = types.SimpleNamespace
   sys.modules["config"] = ns(); sys.modules["config.pg_setting"] = ns(pg_settings=None)
   sys.modules["config.feature_flags"] = ns(flag_enabled=None)
   sys.modules["utils_common.order_management.order_service"] = ns(_call_pricing_service=None)
   sys.modules["utils_common.maps_service.address_resolver"] = ns(API_KEY=os.environ["K"])
   from utils_common.web_ordering import availability as av
   # K = GOOGLE_GEOCODING_API_KEY from ../restaurant-frontend/.env.local
   ```
   Expect the table in 3c.
3. Frontend: `npm run lint`, `npx tsc --noEmit -p .`.
4. End to end (skill `ordelo-local-automatic-orders`, runbook `docs/local-testing-runbook.md`), after the migration:
   - Web delivery to `Rose Cottage, Churchill Way East, Salisbury` with postcode SP1 2AB → order created; `web_session_meta.postcode = 'SP1 2AB'`; `web_order_request.address->>'pin_precision' = 'street'`; rider drop-off shows the warning.
   - Web delivery to a normal numbered address → `exact`, no warning.
   - Mid-checkout postcode change SP1 2AB → SP1 3TA → new session, new postcode stored, address saves.
   - Direct POST to `/web/address` with `postcode: "SP1 3TA"` on an SP1 2AB session → `422 postcode_mismatch`.
   - Collection order → unaffected.
   - WhatsApp delivery → drop-off message unchanged.

## Deploy and rollback

Order (D6): (1) owner runs the migration → (2) deploy restaurant-frontend (Amplify) → (3) deploy OrdeloAgent (Docker). Only sessions started before step 2 hit `checkout_restart_required`; they expire within 2 hours.

Rollback: revert OrdeloAgent first (old code ignores the column), then the frontend if needed. Drop the column last, using the commented SQL in the migration.

## Edge cases

- Google can't resolve the locked postcode itself (`geocode(postcode)` strict): `invalid_address`. Eligibility would already have failed for that postcode, so this should not happen in practice.
- Customer types another town in the Town field: text is kept; the pin search runs with the locked postcode, so the pin stays inside the sector or falls back to the centroid.
- Snapshot saved before step 3 but order created after it: `pricing_location` falls back to the stored point; `pin_precision` absent → no warnings.
- Resumed session (`/checkout-sessions/resume`, `web_hooks.py:105`) doesn't touch the postcode.

## Out of scope / still open (from the 7 Oct handoff)

- Review-page copy "charged only on delivery" vs card capture when a rider accepts (`lib/web/status.ts` still has the old text). Awaiting the owner's choice.
- `restaurant-test.ordelo.app` appears to run `next dev`; suggest a production build.
- Places Autocomplete and PAF address pickers: rejected for now (ADR 0008).
