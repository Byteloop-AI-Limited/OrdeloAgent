# The web checkout postcode is fixed when checkout starts

Status: accepted and implemented, 7 October 2026.

Delivery eligibility, the minimum order value and the estimated delivery fee are calculated for the postcode the customer enters before checkout. If the checkout address could use a different postcode, the customer could move outside the range, minimum or fee they were approved for. The postcode is therefore fixed for the life of a checkout session; changing it means going back to the postcode step, which runs eligibility again and starts a new checkout.

**Frontend (restaurant-frontend).** `POST /api/web/checkout-sessions` stores the approved postcode (from the signed `ordelo_loc` cookie) in the signed `ordelo_co` cookie. The checkout Details screen shows the postcode as read-only text with a *Change postcode* link to `/town/{town}`. `POST /api/web/address` ignores any postcode in the request body and always uses the cookie value; a delivery checkout without one returns `409 checkout_restart_required`. A checkout session is only reused for the same postcode district, and a changed postcode clears the saved address and quote. Town and other address fields stay editable.

**Backend (OrdeloAgent).** Originally `web_checkout.address()` compared only the outcode against `web_session_meta.postcode_district`. [ADR 0008](0008-web-checkout-address-never-blocks-checkout.md) supersedes that: the backend now stores the full postcode at checkout start and enforces the postcode sector from it; sessions without one fail closed.

The minimum order value is recalculated at order creation (`web_checkout.create()`, `below_minimum`) from the locked postcode's centroid; see [ADR 0008](0008-web-checkout-address-never-blocks-checkout.md). Both `postcode_mismatch` and `checkout_restart_required` send the customer back to the postcode step.

Sources: [web_checkout.py](../../utils_common/web_ordering/web_checkout.py), [web contract tests](../../tests/utils_common/web_ordering/test_web_contract.py); in restaurant-frontend: `app/api/web/checkout-sessions/route.ts`, `app/api/web/address/route.ts`, `components/ordelo/CheckoutFlow.tsx`, `lib/web/cookies.ts`.
