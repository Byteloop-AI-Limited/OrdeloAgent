# The web checkout address never blocks checkout

Status: accepted and implemented, 7 October 2026. Refines and partly supersedes [ADR 0007](0007-web-checkout-postcode-is-fixed-at-checkout-start.md).

Real addresses were rejected at checkout. On a road without house numbers (for example Churchill Way E, Salisbury SP1 2AB) the frontend required a house number or name. Google can't find a house name, so it returns a partial match on the right road, and `geocode()` rejected every partial match. The customer had no way through.

The postcode is fixed when checkout starts (ADR 0007), and distance variance inside a postcode is acceptable. So the address is no longer a gate:

- **Minimum order** is priced from the locked postcode's centroid, the same point eligibility quoted (`web_checkout.pricing_location()`). The address text can't change it, so the minimum can't be bypassed.
- **Address text is the customer's.** Street and town are required; house number, house/building name and flat are optional. The text is stored as typed and is what the rider and restaurant read.
- **The backend is the authority for the postcode sector.** `web_session_meta.postcode` (nullable `text`, with a `NOT VALID` check that it matches `^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$`; added by hand in the database on 7 October 2026) stores the full postcode approved at checkout start. `address()` ignores the request's postcode, rejects a different sector with `422 postcode_mismatch`, and a delivery session with no stored postcode fails closed with `409 checkout_restart_required` (the frontend already sends the customer back to the postcode step). The address, the minimum-order point and the rider pin therefore all stay in the approved sector.
- **Rider pin is best effort** (`availability.locate()`), never outside the sector. Google's result for the full address becomes the pin when it lands in the sector: precision `exact` for a door-level match, `street` for a road-level or partial match. If that is unusable (no result, another sector, too coarse) it retries once with the street, town and postcode only, which can only be `street`; interpolated door numbers can land in a neighbouring sector (1 Churchill Way East resolves to SP1 1HZ, 426 m from SP1 2AB). Still unusable, or a provider error: the postcode centroid, precision `postcode`. Only a postcode Google can't resolve fails, with `invalid_address`.
- **The pin is stored as `customer_master.lat/lon`**, which drives rider navigation and the shared delivery-fee calculation. The fee can therefore differ slightly from the eligibility estimate, bounded by the postcode sector. We accept that rather than fork the shared WhatsApp pricing path.
- **Approximate pins are flagged.** For `street` or `postcode` precision the order notes say "Address not verified … Use the address text." (`web_checkout.pin_note()`). The rider's drop-off message gets a matching warning line (`rider_agent._web_pin_warning()`, read from the order's immutable `web_order_request` snapshot).
- Coordinates still never come from the browser. Browser autofill (`address-line1`, `address-line2`, `address-level2`) fills the form; the postcode is shown as text, so autofill can't change it.

Deploy order: migration, then restaurant-frontend (sends `postcode`, reuses a session only for the same full postcode), then OrdeloAgent. Storing the full postcode in `web_session_meta` revises the earlier "only the district is stored" note; `web_order_request.address` and `customer_master.postcode` already held it per order and the table is service-role only.

The checkout snapshot on `web_session_meta.address` and `web_order_request.address` gains `postcode_latitude`, `postcode_longitude` and `pin_precision`. Snapshots saved before this change have no centroid and keep pricing from their geocoded point.

Rejected: Google Places Autocomplete (extra cost and UI for little gain), a paid PAF address picker (possible later), and strict validation with a manual-review queue.

Sources: [availability.py](../../utils_common/web_ordering/availability.py), [web_checkout.py](../../utils_common/web_ordering/web_checkout.py), [web contract tests](../../tests/utils_common/web_ordering/test_web_contract.py); in restaurant-frontend: `app/api/web/address/route.ts`, `components/ordelo/CheckoutFlow.tsx`.
