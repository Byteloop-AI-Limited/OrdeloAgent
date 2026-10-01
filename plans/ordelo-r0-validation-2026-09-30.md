# R0 frontend validation — 30 September 2026

Reviewed the uncommitted restaurant-frontend working tree against `ordelo-agg-plan-cc.md`, especially sections 7.3, 8.1 and R0 guardrails. No application source was edited.

## Result

R0 is substantially implemented, but should not be marked fully accepted yet. Four actionable findings remain, and the required Lighthouse mobile accessibility score has not been measured.

## Findings

1. **P2 — Restaurant-switch confirmation is skipped (browser reproduced).** `components/ordelo/PersistedCart.tsx:69` saves the new basket before `components/ordelo/OrdeloMenuContainer.tsx:172` checks for another active basket. Saving updates the active restaurant, so the check finds no other basket. Reproduction: add a Burger Meal at SFCS, visit BNAT, add a Burger Meal. No confirmation appears; both restaurant baskets survive. Capture the prior active restaurant before persisting the first item, and update/clear storage only after the user chooses.

2. **P2 — Checkout drops Ordelo voucher discounts (code finding; conditional on configuring an Ordelo voucher).** The menu stores the code under `ordelo_web_voucher:{id}` and passes the voucher to `resolveOffers`. `components/ordelo/CheckoutFlow.tsx:98` resolves offers without restoring/passing that voucher. An advertised basket discount disappears from checkout and submitted prices. Currently no restaurant has `ordeloOffers`, so this is dormant in the supplied configuration. Carry the same validated voucher into checkout.
J
3. **P2 — Receipt silently truncates baskets above 20 lines (local API reproduced).** `lib/web/fixtures/index.ts` validates up to 50 lines and totals every line, then snapshots only the first 20. Submitting 21 distinct £1 items returned an order with £21 items total but only 20 receipt items. Preserve all accepted lines or reject unsupported basket sizes before creating the order; account for browser cookie size limits.

4. **P2 — Delivery capture wording describes the wrong milestone.** `components/ordelo/CheckoutFlow.tsx:342` and `lib/web/status.ts:89` say the customer is charged when a rider picks up food. The plan and fixture lifecycle capture when the rider is assigned/becomes inflight, before pickup. Update both strings to match the actual capture boundary. The review page also says the card is “authorised now” before the customer has visited payment.

## Validation performed

- Existing localhost:3000: original homepage renders; `/town` returns 404 because the web mode is off. Legacy WhatsApp URL with synthetic invalid session redirects to the existing session-expired flow.
- Isolated source copy under `/private/tmp/ordelo-r0-review`, excluding environment files, git metadata, build output and dependencies; existing dependencies reused. Built with `NEXT_PUBLIC_WEB_ORDERING_MODE=fixtures`; tested its production server at localhost:3001. Original localhost:3000 was not restarted.
- Production build passed after allowing the existing Google Fonts downloads. Initial restricted-network attempt failed on font DNS. Existing image lint warnings and Supabase Edge-runtime warnings remain.
- Lint passed with three existing image warnings. TypeScript check with incremental output disabled passed. `git diff --check` passed.
- 360 px browser: postcode gate → town → menu; required drink/customization; basket quantity/customizations survive reload; address validation; review totals; test payment → confirmation → order-page redirect.
- Fee-change scenario: £2.99 estimate becomes £3.49, highlighted explicitly; Pay is disabled until acceptance.
- All 18 canned order scenarios rendered, covering every section 7.3 status and collection-time/late/release variants. No horizontal overflow in the menu or the 18 status views at 360 px.
- Local fixture APIs: invalid postcode 400; eligible/closed/out-of-range/pricing-down distinctions; delivery below-minimum 422, closed 422, out-of-range 422, pricing-down 503; collection checkout returns a fixture quote.
- Access: no credential 401; token for another order 403; status-only lookup response excludes delivery, items, charges and notes; private/no-store API header present; ETag repeat returns 304.
- Same idempotency key/body returned the same order and payment URL; changed body returned 409.
- Existing `MenuContainer`, `BasketDrawer`, `CartContext`, legacy pages and middleware are unchanged in the working diff. Home remains at `/`; landing is under `/town`, as the R0 guardrail permits. Live web API mode fails closed with no Ordelo proxy implementation.

## Remaining acceptance limits

- Lighthouse mobile accessibility ≥90 has not been measured; rendered controls and 360 px checks do not establish that score.
- No valid authenticated WhatsApp delivery/collection session or payment transaction was exercised. Invalid-session smoke and unchanged source are narrower evidence than full revenue-flow regression coverage.
- Amplify preview basic auth and whole-site noindex were not inspected; these are deployment settings.
- Fixture validation does not prove R1/R2/R3 backend, Stripe, fulfilment or authenticated live integration behavior.
- `tsconfig.tsbuildinfo` is an unrelated generated change to exclude from a clean implementation commit. The new implementation files are still untracked and must be included when committing.

Screenshots: `/private/tmp/ordelo-r0-menu-360.jpg`, `/private/tmp/ordelo-r0-fee-360.jpg`.
