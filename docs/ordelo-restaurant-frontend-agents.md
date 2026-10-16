# Ordelo × Restaurant Frontend — integration reference (LLM/agent edition)

> **Alerts and notifications:** see [the end-to-end guide](alerts-and-notifications.md) and [interactive companion](alerts-and-notifications.html) for recipient routing, retry outcomes and frontend polling.

> **Web ordering implementation:** see the [interactive playground](web-ordering-playground.html) and [matching agent context](web-ordering-playground.md) for checkout identity, tables, payment/fulfilment flows and differences from the separate proposal.

Machine-friendly rendering of `ordelo-restaurant-frontend-co.html` (the Integration Playground). Same facts, no UI. Evidence snapshot: 2026-09-29; Ordelo commit `7697e15`; restaurant-frontend commit `a75312e`. Scope: Read-only code inspection; live services, deployed configuration and external payment internals were not exercised.

## How to use this document

- Every endpoint has a stable `id` (used by scenarios, steps, gaps and portals). Grep for `#### <id>` to jump to it.
- Direction ids (`br-fe`, `fe-ordelo`, ...) classify who calls whom. Status is `live`, `stale` (documentation out of date), or `dead` (no caller / stub).
- Source references use `Repo:path:line`. Repos: Frontend (restaurant-frontend), Ordelo (OrdeloAgent), Restaurant agents (restaurant-agents).
- Payload examples on journey endpoints use fictional values and may be subsets. Catalogue endpoints (`cc..` ids) give shapes as written in code, not live samples.
- Confidence notes: entries whose line numbers came from the second inspection (catalogue and portals) were taken from the `dev` branches and may not match the pinned commits.

## 1. Architecture summary

- **The frontend presents the journey** Restaurant selection, menu, basket, order summary and browser redirects. API routes proxy ordering calls and also read some data directly.
- **Ordelo coordinates the order** Order identifiers, persistence, fee calculation, payment orchestration, restaurant confirmation and the rider delivery lifecycle.
- **The restaurant agent owns chat context** Active customer-thread lookup and order/rider event callbacks resolve to a configured restaurant backend, separate from this frontend.

Main request path: browser → Next.js (restaurant frontend) → Ordelo. Return paths, browser redirects, database webhooks and background work are described in the scenarios (section 5). An arrow is not a claim of synchronous behaviour.

### Configuration and boundary notes

- Frontend configuration: restaurant list and branding live in config/restaurants.ts. apiName selects the menu; orderApiName ?? apiName selects the order target.
- Ordelo URL: Next.js reads ORDELO_APP_URL from ordelo_config with a 60-second cache, falling back to RIDER_AGENT_URL. The variable’s rider-agent name still points to the broader Ordelo service.
- Restaurant-agent URL: Ordelo resolves {REST_REF}_APP_URL through config/params.py. CHKS aliases to ELAS in the inspected configuration.
- Shared database: frontend hours/config and operational dashboards can read Supabase directly. Not every data read goes through Ordelo.
- Pricing: minimum food value, delivery distance and delivery fees are related concepts, not interchangeable endpoint outputs.

### Actors

| id | name | role |
|---|---|---|
| `browser` | Customer browser | Selects food, stores the summary in sessionStorage, and opens the payment page. |
| `frontend` | Restaurant frontend | Next.js owns presentation, menu configuration, API proxies and some direct database reads. |
| `ordelo` | Ordelo | FastAPI creates orders, calculates charges through pricing, coordinates payment and runs rider logistics. |
| `agent` | Restaurant agent | A separate configured backend supplies active customer threads and receives order/rider events. |
| `database` | Supabase / Postgres | Persists customer, order and delivery records. SQL functions and triggers drive logistics. |
| `menu` | Menu service | The upstream MENU_API_URL provides menu data. It is a separate configured dependency. |
| `pricing` | Pricing service | Calculates delivery options, minimum food value and delivery-related charges. |
| `payment` | Payment service / Stripe | Provides the hosted payment URL and accepts later capture commands. Its implementation was not inspected. |
| `whatsapp` | WhatsApp | Carries customer conversations through the restaurant agent and rider/admin interactions through Ordelo. |
| `geocoding` | Postcode / geocoding | The frontend calls postcodes.io and Google Geocoding to resolve an address. |
| `apiConsumer` | Other API consumer | Caller of an available Ordelo capability; no direct frontend caller was found for these endpoints. |

## 2. Directions (endpoint classification)

| id | label | count | note |
|---|---|---|---|
| `br-fe` | Browser → Frontend routes | 7 | Next.js server routes that the customer browser calls. The browser never calls Ordelo directly. |
| `fe-ordelo` | Frontend → ORDELO | 7 | Exactly 6 live. Every one goes through a Next.js server route — the browser never calls ORDELO directly, which is why ORDELO has no CORS config. |
| `fe-sb` | Frontend → Supabase (direct) | 5 | The admin and rider portals bypass ORDELO entirely and read Postgres through tenant-scoped Proxy clients. |
| `fe-ext` | Frontend → other services | 2 | Menu and geocoding do not involve ORDELO. |
| `rest-ordelo` | restaurant-agents → ORDELO | 9 | The restaurant runtime is the third corner of the triangle. |
| `ordelo-rest` | ORDELO → restaurant-agents | 7 | 11 webhook types. Base URL = ordelo_config.{REST_REF}_APP_URL, cached in-process for 1 hour. |
| `db-ordelo` | Postgres trigger / pg_cron → ORDELO | 12 | All take payload: dict = Depends(get_payload) — literally await request.json(), no validation and no auth. They return {"status":"success"} even on internal error, because a raised exception would fail the SQL trigger’s HTTP call. |
| `ordelo-ext` | ORDELO → microservices | 4 | Stripe, pricing and Google Maps. All channel-agnostic. |
| `wa-ordelo` | WhatsApp → ORDELO | 6 | Meta webhook and Flow endpoints. |
| `consumer` | Other API consumer → ORDELO | 2 | Ordelo capabilities for which no caller was found in the inspected frontend code. |
| `diag` | Diagnostics (unauthenticated) | 5 | No API key, no JWT, no signature check on any of these. |

Key facts: only 6 live calls go Frontend → Ordelo (plus one stale). The browser never calls Ordelo directly (no CORS config). Database-trigger and pg_cron hooks take unvalidated JSON and return `{"status":"success"}` even on internal error. Diagnostics routes have no authentication.

## 3. Endpoint catalogue (66 entries)

### Direction `br-fe` — Browser → Frontend routes (7)

Next.js server routes that the customer browser calls. The browser never calls Ordelo directly.

#### menu

- Method/path: `GET /api/menu?restaurant={id}`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Browse; title: Load the menu
- Does: Next.js resolves the restaurant configuration and fetches MENU_API_URL?restaurant_name={apiName}. It normalizes upstream menu data for the UI.
- Request: `{"restaurant": "elas"}`
- Response: `Normalized frontend menu model`
- State and side effects: No order is created. The upstream menu service owns the menu response.
- Notes: apiName selects the menu source; orderApiName can select a different restaurant for order creation.
- Sources: Frontend:app/api/menu/route.ts:49 (GET); Frontend:config/restaurants.ts:178 (getRestaurantConfig)

#### hours

- Method/path: `GET /api/restaurant-hours/{id}`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Browse; title: Read opening hours
- Does: Next.js reads restaurant_master.service_hours_json directly through Supabase and converts it to openingHours.
- Request: `{"id": "elas"}`
- Response: `{"openingHours": "<converted opening-hours model>"}`
- State and side effects: Database read; response uses Cache-Control: no-store.
- Notes: This path does not proxy through Ordelo.
- Sources: Frontend:app/api/restaurant-hours/[id]/route.ts:9 (GET); Frontend:lib/restaurantHours.ts:22 (getServiceHours)

#### verify

- Method/path: `GET /api/verify-session?rest_ref={id}&recipient={phone}`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Session; title: Validate the menu session
- Does: The frontend proxy calls Ordelo get-active-thread and returns its JSON to the page or basket.
- Request: `{"rest_ref": "elas", "recipient": "440000000001"}`
- Response: `{"thread_id": "example-thread"}`
- State and side effects: The browser compares the returned thread_id with its URL-provided thread_id.
- Notes: Missing session data blocks checkout. A mismatch, -1 or request failure leads to the session-expired page. The checkout API itself checks presence; it does not repeat this active-thread lookup.
- Sources: Frontend:app/api/verify-session/route.ts:4 (GET); Frontend:app/restaurant/[id]/page.tsx:39 (validateSession); Frontend:components/BasketDrawer.tsx:64 (handleCheckout)

#### postcode

- Method/path: `GET /api/postcode-lookup/{postcode}`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Address; title: Resolve a postcode in the frontend
- Does: Validates the postcode through postcodes.io, then calls Google Geocoding for address components and coordinates.
- Request: `{"postcode": "<UK postcode>"}`
- Response: ```
{"house_number": null, "building_name": null, "street_name": "Example street", "city": "Example city", "postcode": "<normalized postcode>", "latitude": 51.4, "longitude": 0.1}
```
- State and side effects: External lookup only; the user supplies house/building details afterward.
- Notes: This frontend route does not call Ordelo postcode-validator. Google Geocoding configuration is required.
- Sources: Frontend:app/api/postcode-lookup/[postcode]/route.ts:36 (GET); Frontend:app/address-update/page.tsx:38 (handleLookup)

#### address-proxy

- Method/path: `POST /api/capture-address`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Address; title: Submit the address
- Does: Passes the address body to Ordelo /order-hooks/capture-address.
- Request: ```
{"recipient": "440000000001", "rest_ref": "elas", "house_number": "10", "street_name": "Example street", "city": "Example city", "postcode": "<UK postcode>", "latitude": 51.4, "longitude": 0.1}
```
- Response: `{"success": true}`
- State and side effects: The browser shows an address-complete view.
- Notes: The address page obtains recipient and rest_ref from URL parameters and offers a return to WhatsApp.
- Sources: Frontend:app/api/capture-address/route.ts:4 (POST); Frontend:app/address-update/page.tsx:71 (handleSubmit)

#### checkout

- Method/path: `POST /api/checkout`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Ordering; title: Create an order from the basket
- Does: Maps browser fields to the Ordelo request. Chooses orderApiName ?? apiName from the selected restaurant configuration.
- Request: ```
{"restaurantId": "elas", "recipient": "440000000001", "threadId": "example-thread", "orderItems": [{"order_id": "placeholder", "sku": "example-meal", "quantity": 2, "price": 12.5, "product_name": "Example meal", "modifications": ["No onions"]}], "orderType": "delivery", "notes": "Example only"}
```
- Response: ```
{"success": true, "payment_intent_url": "https://payment.example/checkout", "delivery_fee": 3, "service_charge": 1.5, "small_order_fee": 0, "order_number": "ELAS-DEMO-1"}
```
- State and side effects: Calls Ordelo create-order; the browser stores the resulting summary in sessionStorage and opens /order-summary.
- Notes: The route checks recipient/threadId presence, items and restaurant config. Browser-side active-thread validation is a separate step. It forwards subtotal/total if present, but Ordelo currently does not return them.
- Sources: Frontend:app/api/checkout/route.ts:5 (POST); Frontend:components/BasketDrawer.tsx:64 (handleCheckout)

#### pay-local

- Method/path: `POST /api/pay-at-restaurant`
- Direction: `br-fe`; status: `live`; flow: Customer browser → Restaurant frontend
- Area: Payment; title: Choose payment on collection
- Does: The takeaway summary posts the existing order_number and basket context to the frontend API.
- Request: ```
{"restaurantId": "elas", "recipient": "440000000001", "threadId": "example-thread", "orderItems": [{"order_id": "placeholder", "sku": "example-meal", "quantity": 2, "price": 12.5, "product_name": "Example meal", "modifications": ["No onions"]}], "orderType": "takeaway", "order_number": "ELAS-DEMO-1"}
```
- Response: ```
{"success": true, "order_id": "ELAS-DEMO-1", "order_number": "ELAS-DEMO-1", "message": "Order submitted successfully"}
```
- State and side effects: Proxies to Ordelo; on success the browser clears sessionStorage, shows an alert and returns to the restaurant page.
- Notes: Takeaway defaults to this path unless takeawayPayment is enabled. There is no dedicated persistent customer order-confirmation page in this flow.
- Sources: Frontend:app/order-summary/page.tsx:64 (shouldPayAtRestaurant; handleSubmitTakeawayOrder); Frontend:app/api/pay-at-restaurant/route.ts:5 (POST)

### Direction `fe-ordelo` — Frontend → ORDELO (7)

Exactly 6 live. Every one goes through a Next.js server route — the browser never calls ORDELO directly, which is why ORDELO has no CORS config.

#### active

- Method/path: `GET /order-hooks/get-active-thread/{rest_ref}/{recipient}`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Area: Session; title: Proxy the customer thread lookup
- Does: Ordelo calls the configured restaurant agent at /thread-hooks/get-active-thread/{rest_ref}/{recipient}. It passes through the upstream content, status and content type.
- Request: `{"rest_ref": "elas", "recipient": "440000000001"}`
- Response: `Upstream active-thread response`
- State and side effects: The customer thread is resolved by the restaurant backend.
- Notes: The restaurant agent is distinct from the Next.js frontend. Base URLs come from {REST_REF}_APP_URL, with alias resolution.
- Gotcha: Called twice per order: on page load and again immediately before checkout (BasketDrawer.tsx:82).
- Sources: Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread); Ordelo:config/params.py:66 (WEBHOOK_PATHS; get_restaurant_webhook_url_async); Frontend:app/api/verify-session/route.ts:20 (Caller); Ordelo:watomation/routers/order_hooks.py:393 (Implementation)

#### address

- Method/path: `POST /order-hooks/capture-address`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Area: Address; title: Persist and announce the address
- Does: Upserts customer_master and CustRestMap, then POSTs to the restaurant agent address-update endpoint.
- Request: ```
{"recipient": "440000000001", "rest_ref": "elas", "house_number": "10", "street_name": "Example street", "city": "Example city", "postcode": "<UK postcode>", "latitude": 51.4, "longitude": 0.1}
```
- Response: `{"success": true}`
- State and side effects: Writes customer coordinates keyed by recipient; updates the customer/restaurant mapping with has_consent=false.
- Notes: Outbound path: /order-event-hooks/{rest_ref}/address-update/{recipient}. The call is awaited, but this handler does not raise on an upstream HTTP error status.
- Gotcha: cust_name is set to request.recipient — the phone number doubles as the customer name.
- Sources: Ordelo:watomation/routers/order_hooks.py:342 (capture_address); Ordelo:config/params.py:66 (WEBHOOK_PATHS); Frontend:app/api/capture-address/route.ts:10 (Caller); Ordelo:watomation/routers/order_hooks.py:341 (Implementation)

#### postcode-ordelo

- Method/path: `GET /order-hooks/postcode-validator/{postcode}`
- Direction: `fe-ordelo`; status: `stale`; flow: Other API consumer → Ordelo
- Area: Eligibility; title: Ordelo postcode validation
- Does: Exposes the Ordelo address resolver as a postcode-validation endpoint.
- Request: `{"postcode": "<UK postcode>"}`
- Response: `Resolved address data`
- State and side effects: Address lookup only.
- Notes: The frontend has its own postcode-lookup route; the two paths should not be drawn as one existing call chain.
- Gotcha: Stale documentation — ENV_SETUP.md still prescribes this call.
- Sources: Ordelo:watomation/routers/order_hooks.py:308 (validate_postcode); Frontend:ENV_SETUP.md:84 (Caller); Ordelo:watomation/routers/order_hooks.py:307 (Implementation)

#### create

- Method/path: `POST /order-hooks/create-order/{rest_ref}`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Area: Ordering; title: Generate authoritative order identifiers
- Does: Gets a daily sequence, derives an order reference, inserts food_order and order_item, loads financial values, then requests a payment URL.
- Request: ```
{"recipient": "440000000001", "thread_id": "example-thread", "order_items": [{"order_id": "placeholder", "sku": "example-meal", "quantity": 2, "price": 12.5, "product_name": "Example meal", "modifications": ["No onions"]}], "order_type": "delivery", "notes": "Example only"}
```
- Response: ```
{"status": "success", "order_id": "DEMO-1", "recipient": "440000000001", "thread_id": "example-thread", "order_number": "ELAS-DEMO-1", "payment_intent_url": "https://payment.example/checkout", "service_charge": 1.5, "delivery_fee": 3, "small_order_fee": 0, "notes": "Example only"}
```
- State and side effects: Initial payment_status is requires_payment. Item order_id placeholders are replaced with the generated order_id. Delivery fees use the stored customer coordinates and pricing service.
- Notes: order_type is required and accepts delivery or takeaway. Ordelo sums submitted item prices. There is no menu-price relookup in create_order_with_items. Failed item insertion attempts deletion of the parent order; this is compensating cleanup, not one DB transaction.
- Gotcha: The frontend reads data.subtotal and data.total (checkout/route.ts:94-95), which this endpoint never returns. Both are always undefined and BasketDrawer.tsx:162 falls back to client-recomputed pricing.
- Sources: Ordelo:watomation/routers/order_hooks.py:202 (CreateOrderRequest; create_order); Ordelo:utils_common/order_management/order_service.py:172 (create_order_with_items); Ordelo:utils_common/order_management/food_order_pymodel.py:149 (from_order_id; update_final_order_value_in_db); Frontend:app/api/checkout/route.ts:52 (Caller); Ordelo:watomation/routers/order_hooks.py:212 (Implementation)

#### pay-rest

- Method/path: `POST /payment-hooks/pay-at-restaurant/{rest_ref}`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Area: Payment; title: Mark an existing order pay-at-restaurant
- Does: Requires order_type=takeaway and updates an existing food_order by order_number.
- Request: ```
{"recipient": "440000000001", "thread_id": "example-thread", "order_id": "ELAS-DEMO-1", "order_items": [{"order_id": "placeholder", "sku": "example-meal", "quantity": 2, "price": 12.5, "product_name": "Example meal", "modifications": ["No onions"]}], "order_type": "takeaway"}
```
- Response: `{"status": "success", "order_number": "ELAS-DEMO-1"}`
- State and side effects: Sets payment_status=pay_at_rest, schedules the restaurant-agent notification and init_takeaway.
- Notes: Despite the field name order_id, this handler matches food_order.order_number. Non-takeaway returns 400; missing order returns 404. It does not create a fresh order from the supplied items.
- Gotcha: order_id is matched against the order_number COLUMN (payment_hooks.py:230). It works only because the frontend happens to send an order number.
- Sources: Ordelo:watomation/routers/payment_hooks.py:188 (PayAtRest; pay_at_restaurant); Frontend:app/api/pay-at-restaurant/route.ts:63 (Caller); Ordelo:watomation/routers/payment_hooks.py:199 (Implementation)

#### cc01

- Method/path: `GET /sys-admin/rider-payout?start=&end=`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Does: Calls RPC get_rider_payout_report, which joins delivery_dispatch → rider_master → delivery_summary → rider_registrations, then aggregates per bank account.
- Request: `start (ISO date, required), end (optional, defaults start+6d)`
- Response: `{ start, end, total_orders, detailed[], aggregated[] }`
- Sources: Frontend:app/api/sys-admin/rider-payouts/report/route.ts:32 (Caller); Ordelo:watomation/routers/sys_admin_auth_session.py:240 (Implementation)

#### cc02

- Method/path: `POST /sys-admin/update-paid`
- Direction: `fe-ordelo`; status: `live`; flow: Restaurant frontend → Ordelo
- Does: Idempotently flips delivery_dispatch.paid_status unpaid→paid. Already-paid rows come back as skipped.
- Request: `{ dispatch_ids: [int, …] }  (min length 1)`
- Response: `{ updated_count, dispatch_ids_updated[], dispatch_ids_skipped[] }`
- Gotcha: ORDELO applies no caller identity here. The only thing enforcing sys_admin is the frontend proxy’s cookie check.
- Sources: Frontend:app/api/sys-admin/rider-payouts/mark-paid/route.ts:41 (Caller); Ordelo:watomation/routers/sys_admin_auth_session.py:341 (Implementation)

### Direction `fe-sb` — Frontend → Supabase (direct) (5)

The admin and rider portals bypass ORDELO entirely and read Postgres through tenant-scoped Proxy clients.

#### cc03

- Method/path: `GET v_admin_orders  (keyset paginated)`
- Direction: `fe-sb`; status: `live`; flow: Restaurant frontend → Supabase / Postgres
- Does: Auto-scoped by rest_ref through a JS Proxy that injects .eq("rest_ref", session.rest_ref) on every TENANT_SCOPED_TABLES query.
- Request: `cursor + limit`
- Response: `order rows`
- Sources: Frontend:app/api/rest-admin/orders/route.ts:15 (Caller); Frontend:lib/rest-admin-session.ts:348 (Implementation)

#### cc04

- Method/path: `GET v_admin_orders_daily / v_admin_order_items`
- Direction: `fe-sb`; status: `live`; flow: Restaurant frontend → Supabase / Postgres
- Does: Daily rollups and per-order line items for the restaurant dashboard.
- Request: `—`
- Response: `rollups / line items`
- Sources: Frontend:app/api/rest-admin/orders/summary/route.ts:7 (Caller); Frontend:app/api/rest-admin/orders/[order_number]/items/route.ts:7 (Implementation)

#### cc05

- Method/path: `GET delivery_dispatch  (rider jobs)`
- Direction: `fe-sb`; status: `live`; flow: Restaurant frontend → Supabase / Postgres
- Does: Scoped to .eq("rider_id", …). The rider portal never touches ORDELO.
- Request: `cursor + limit`
- Response: `dispatch rows`
- Sources: Frontend:app/api/rider/jobs/route.ts:9 (Caller); Frontend:lib/rider-session.ts:23 (Implementation)

#### cc06

- Method/path: `GET restaurant_master / ordelo_config`
- Direction: `fe-sb`; status: `live`; flow: Restaurant frontend → Supabase / Postgres
- Does: GET and PATCH. Sys-admin writes the same ordelo_config table that lib/config.ts reads to find ORDELO.
- Request: `—`
- Response: `config rows`
- Gotcha: Config write/read loop: lib/config.ts caches for 60s and /api/reset-config-cache is per-instance only, so on multi-instance Amplify a flush hits one container.
- Sources: Frontend:app/api/sys-admin/restaurants/route.ts:10 (Caller); Frontend:app/api/sys-admin/restaurants/[rest_ref]/config/route.ts:9 (Implementation)

#### cc07

- Method/path: `GET ordelo_config  (unauthenticated dump)`
- Direction: `fe-sb`; status: `live`; flow: Restaurant frontend → Supabase / Postgres
- Does: Debug route. Dumps the entire ordelo_config table with no auth and sits outside the middleware matcher.
- Request: `—`
- Response: `all rows`
- Sources: Frontend:app/api/test-db-connection/route.ts:4 (Caller); Frontend:app/api/test-db-connection/route.ts:11 (Implementation)

### Direction `fe-ext` — Frontend → other services (2)

Menu and geocoding do not involve ORDELO.

#### cc08

- Method/path: `GET {MENU_API_URL}?restaurant_name=`
- Direction: `fe-ext`; status: `live`; flow: Restaurant frontend → Menu service
- Does: restaurant.byteloop.ai — a separate service. Not ORDELO.
- Request: `restaurant_name`
- Response: `menu JSON`
- Sources: Frontend:app/api/menu/route.ts:81 (Caller); Frontend:services/menuService.ts:1 (Implementation)

#### cc09

- Method/path: `GET api.postcodes.io + Google Geocoding`
- Direction: `fe-ext`; status: `live`; flow: Restaurant frontend → Postcode / geocoding
- Does: Replaced the ORDELO postcode-validator call. The frontend now geocodes on its own.
- Request: `postcode`
- Response: `address + lat/lng`
- Sources: Frontend:app/api/postcode-lookup/[postcode]/route.ts:58 (Caller); Frontend:app/api/postcode-lookup/[postcode]/route.ts:82 (Implementation)

### Direction `rest-ordelo` — restaurant-agents → ORDELO (9)

The restaurant runtime is the third corner of the triangle.

#### authorized

- Method/path: `POST /payment-hooks/payment-complete`
- Direction: `rest-ordelo`; status: `live`; flow: Payment service / Stripe → Ordelo
- Area: Payment; title: Receive the payment completion event
- Does: Consumes a Stripe-shaped event and reads data.object.metadata.orderID. The exact webhook forwarding path inside the external payment service was not inspected.
- Request: `{"data": {"object": {"metadata": {"orderID": "DEMO-1"}}}}`
- Response: `{"success": "success"}`
- State and side effects: Sets food_order.payment_status=requires_capture, then schedules restaurant-agent notification and init_delivery or init_takeaway.
- Notes: The frontend does not POST this online-payment event. requires_capture means authorization awaiting capture. The handler shown has no explicit duplicate-event guard or Stripe-signature verification; upstream protections are unverified.
- Sources: Ordelo:watomation/routers/payment_hooks.py:106 (payment_complete_path; init_delivery_summary); Restaurant agents:.../on_message_graph_handler.py:203 (Caller); Ordelo:watomation/routers/payment_hooks.py:105 (Implementation)

#### cc10

- Method/path: `POST /delivery-hooks/notify-food-ready-for-pickup/{recipient}`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Gated on check_delivery_progress == AWAITING_PICKUP, so a late "Ready" tap returns skipped rather than running the agent.
- Request: `{ restaurant_name }`
- Response: `{ status: "success"|"skipped", action, recipient }`
- Gotcha: The caller never inspects the response — a bare await client.post.
- Sources: Restaurant agents:.../on_callback_handler.py:146 (Caller); Ordelo:watomation/routers/delivery_hooks.py:693 (Implementation)

#### cc11

- Method/path: `GET /delivery-hooks/check-rider-allocation-status/{order_number}`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Annotated "To Be Deleted" in the source comment, but it has a live caller.
- Request: `path order_number`
- Response: `{ delivery_summary_status }`
- Gotcha: Marked for deletion at delivery_hooks.py:813 while still in use. Deleting it would break the restaurant runtime.
- Sources: Restaurant agents:.../rest_agent/agents/delivery.py:691 (Caller); Ordelo:watomation/routers/delivery_hooks.py:814 (Implementation)

#### cc12

- Method/path: `POST /customer-hooks/create-or-update-customer`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Upserts with exclude_unset=True so omitted fields do not null out existing data. For a new customer it also seeds cust_rest_map with has_consent=false.
- Request: `{ cust_id, rest_ref, cust_name?, cust_email?, address fields… }`
- Response: `the upserted CustomerMaster`
- Sources: Restaurant agents:.../ordelo_service/ordelo_service.py:68 (Caller); Ordelo:watomation/routers/customer_hooks.py:51 (Implementation)

#### cc13

- Method/path: `POST /customer-hooks/update-address`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: 404 if the customer is missing. Then POSTs to the restaurant’s order-address-update webhook.
- Request: `{ cust_id, rest_ref, city, postcode, lat, lon, … }`
- Response: `{ success, cust_id }`
- Sources: Restaurant agents:.../ordelo_service/ordelo_service.py:90 (Caller); Ordelo:watomation/routers/customer_hooks.py:96 (Implementation)

#### cc14

- Method/path: `POST /customer-hooks/update-cust-rest-map`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Marketing-consent ledger, one row per (customer, restaurant). Fully channel-agnostic.
- Request: `{ cust_id, rest_ref, has_consent, consent_dtts? }`
- Response: `{ success, record }`
- Sources: Restaurant agents:.../ordelo_service/ordelo_service.py:116 (Caller); Ordelo:watomation/routers/customer_hooks.py:144 (Implementation)

#### cc15

- Method/path: `POST /customer-hooks/restaurant-feedback`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Mints FDB-<hex12> and WhatsApps every deduped admin. Nothing is persisted — feedback is ephemeral.
- Request: `{ rest_ref, cust_id, cust_name?, order_reference?, description (5–2000) }`
- Response: `202 { status:"accepted", feedback_id, admins_scheduled }`
- Sources: Restaurant agents:.../ordelo_service/ordelo_service.py:136 (Caller); Ordelo:watomation/routers/customer_hooks.py:198 (Implementation)

#### cc16

- Method/path: `POST /wa-request-location`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: The modern replacement for OwnTracks. Validates the caller against the live delivery_inflight assignment, then asks the rider for a native WhatsApp location.
- Request: ```
{ rest_ref, order_number, location_requested_by, requester_id, callback_url, idempotency_key? }
```
- Response: `200 location_available / 202 waiting_for_rider`
- Gotcha: callback_url is validated to be public HTTPS with no credentials or fragment — the closest thing to per-request authorization on any hook.
- Sources: Restaurant agents:.../ordelo_service/ordelo_service.py:164 (Caller); Ordelo:watomation/routers/wa_location_hooks.py:34 (Implementation)

#### cc17

- Method/path: `POST /internal/cache/reset`
- Direction: `rest-ordelo`; status: `live`; flow: Restaurant agent → Ordelo
- Does: Evicts process-local caches: base URL, overwatch list, RestaurantMaster, app URL. A shared operational contract between the two services.
- Request: `optional ?rest_ref=`
- Response: `{ scope, removed_entries{…} }`
- Sources: Restaurant agents:.../services/operational_diagnostics.py:101 (Caller); Ordelo:watomation/fapp_ordelo_agent.py:312 (Implementation)

### Direction `ordelo-rest` — ORDELO → restaurant-agents (7)

11 webhook types. Base URL = ordelo_config.{REST_REF}_APP_URL, cached in-process for 1 hour.

#### payment-event

- Method/path: `POST /order-event-hooks/{rest_ref}/payment-complete/{recipient}/{thread_id}`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Area: Payment; title: Notify the restaurant agent
- Does: Ordelo sends the persisted FoodOrder model to the configured restaurant backend.
- Request: ```
{"order_id": "DEMO-1", "order_number": "ELAS-DEMO-1", "recipient": "440000000001", "thread_id": "example-thread", "payment_status": "requires_capture", "action": "delivery"}
```
- Response: `Upstream response; shape not asserted`
- State and side effects: Updates the downstream customer conversation through a background task.
- Notes: The example is a subset of the FoodOrder payload. HTTP failures are logged by handle_payment_complete; the task does not provide a browser order-status response.
- Sources: Ordelo:watomation/routers/payment_hooks.py:38 (handle_payment_complete); Ordelo:config/params.py:66 (WEBHOOK_PATHS)

#### rider-event

- Method/path: `POST /rider-event-hooks/{rest_ref}/rider-inflight`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Area: Logistics; title: Notify customer conversation of assignment
- Does: Sends the delivery_summary to the restaurant agent after assignment.
- Request: `{"delivery_summary": "<DeliverySummary>"}`
- Response: `Restaurant-agent response`
- State and side effects: The restaurant backend can reflect rider progress in the customer conversation.
- Notes: Later callbacks use /on-restaurant-cc/{order_number}/{customer_id} and /on-customer-cc/{order_number}/{customer_id}. Zone-entry events and timeouts are other outbound hooks.
- Sources: Ordelo:watomation/routers/delivery_hooks.py:336 (post_rider_event_inflight); Ordelo:ordelo/agent_app_handlers.py:528 (post_rider_event_restaurant_cc; post_rider_event_customer_cc); Ordelo:config/params.py:66 (WEBHOOK_PATHS); Ordelo:watomation/routers/delivery_hooks.py:485 (Caller)

#### cc18

- Method/path: `POST order-event-hooks/{rest_ref}/address-update/{recipient}`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Does: Sent after capture-address and after customer-hooks/update-address.
- Request: `the customer_master row`
- Response: `ignored`
- Sources: Ordelo:watomation/routers/order_hooks.py:341 (Caller); Ordelo:config/params.py:66 (Implementation)

#### cc19

- Method/path: `POST rider-event-hooks/{rest_ref}/on-restaurant-enter | on-customer-enter`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Does: Geofence transitions. rid=rest + enter also WhatsApps admins the 2-digit restaurant confirmation code.
- Request: `{ event, rid, customer_id, order_number }`
- Response: `ignored`
- Sources: Ordelo:watomation/routers/location_hooks.py:243 (Caller); Ordelo:config/params.py:66 (Implementation)

#### cc20

- Method/path: `POST rider-event-hooks/{rest_ref}/delivery-timedout`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Does: Carries the outcome of cancel_payment(), which is the only thing that lets the restaurant runtime confirm a refund. Skipped for order numbers containing "test".
- Request: `delivery summary + payment_cancelled`
- Response: `ignored`
- Sources: Ordelo:watomation/routers/delivery_hooks.py:750 (Caller); Ordelo:config/params.py:66 (Implementation)

#### cc21

- Method/path: `POST order-event-hooks/{rest_ref}/takeaway-pickup-time-updated | takeaway-ready`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Does: Takeaway pickup-time and ready events.
- Request: `takeaway summary`
- Response: `ignored`
- Sources: Ordelo:watomation/routers/takeaway_hooks.py:533 (Caller); Ordelo:config/params.py:66 (Implementation)

#### cc22

- Method/path: `GET thread-hooks/get-active-thread/{rest_ref}/{recipient}`
- Direction: `ordelo-rest`; status: `live`; flow: Ordelo → Restaurant agent
- Does: The upstream of the frontend’s session check. The only WEBHOOK_PATHS entry that already carries rest_ref in its own path.
- Request: `—`
- Response: `{ thread_id } | -1`
- Sources: Ordelo:watomation/routers/order_hooks.py:400 (Caller); Ordelo:config/params.py:66 (Implementation)

### Direction `db-ordelo` — Postgres trigger / pg_cron → ORDELO (12)

All take payload: dict = Depends(get_payload) — literally await request.json(), no validation and no auth. They return {"status":"success"} even on internal error, because a raised exception would fail the SQL trigger’s HTTP call.

#### confirm

- Method/path: `POST /delivery-hooks/restaurant-confirmation-request`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Area: Logistics; title: Ask the restaurant to confirm delivery
- Does: Database-triggered restaurant confirmation flow handles confirmation and pickup-time changes.
- Request: ```
{"trigger_reason": "<database trigger reason>", "delivery_summary": "<delivery summary record>"}
```
- Response: `Acknowledgement; shape depends on the trigger`
- State and side effects: Coordinates restaurant/admin messaging and delivery readiness.
- Notes: This is a database → Ordelo interaction, not a frontend checkout request. Dispatch depends on subsequent database state transitions.
- Sources: Ordelo:watomation/routers/delivery_hooks.py:1499 (restaurant_confirmation_flow); Ordelo:ordelo_datamodels/delivery/delivery_summary.sql:56 (trigger_restaurant_updates); Ordelo:ordelo_datamodels/delivery/delivery_summary.sql:284 (Caller); Ordelo:watomation/routers/delivery_hooks.py:1498 (Implementation)

#### dispatch

- Method/path: `POST /delivery-hooks/delivery-dispatch`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Area: Logistics; title: Offer a delivery to riders
- Does: Processes bulk_dispatch entries and schedules WhatsApp Accept/Decline offers to riders.
- Request: `{"bulk_dispatch": ["<dispatch + rider + delivery data>"]}`
- Response: `{"status": "success"}`
- State and side effects: Fan-out uses BackgroundTasks. Rider callback handling subsequently changes dispatch state.
- Notes: The offer is not assignment. Customer frontend pages do not choose the rider.
- Sources: Ordelo:watomation/routers/delivery_hooks.py:434 (delivery_dispatch_hook; wa_send_delivery_dispatch_request_to_rider); Ordelo:ordelo_datamodels/dispatch/delivery_dispatch.sql:1 (dispatch trigger webhook); Ordelo:ordelo_datamodels/dispatch/delivery_dispatch.sql:73 (Caller); Ordelo:watomation/routers/delivery_hooks.py:409 (Implementation)

#### inflight

- Method/path: `POST /delivery-hooks/delivery-inflight-graph-init`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Area: Logistics; title: Start the assigned rider journey
- Does: A new inflight record triggers payment capture, the restaurant-agent rider event, admin receipt and rider graph initialization.
- Request: ```
{"delivery_inflight": [{"dispatch_id": "example-dispatch"}], "delivery_summary": "<DeliverySummary>", "rider_master": "<rider record>"}
```
- Response: `Acknowledgement of scheduled work`
- State and side effects: Schedules capture_delivery_payment, post_rider_event_inflight, admin_order_reciept and init_ordelo_graph.
- Notes: An HTTP acknowledgement is not proof that every background operation succeeded.
- Sources: Ordelo:watomation/routers/delivery_hooks.py:522 (delivery_inflight_graph_init_hook); Ordelo:ordelo_datamodels/dispatch/delivery_inflight.sql:1 (inflight webhook); Ordelo:ordelo_datamodels/dispatch/delivery_inflight.sql:75 (Caller); Ordelo:watomation/routers/delivery_hooks.py:485 (Implementation)

#### takeaway-confirm

- Method/path: `POST /takeaway-hooks/restaurant-confirmation-request`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Area: Logistics; title: Ask the restaurant to confirm collection
- Does: A takeaway summary triggers the restaurant confirmation flow and pickup-time selection.
- Request: `{"takeaway_summary": "<takeaway record>"}`
- Response: `Flow response; dependent on current state`
- State and side effects: Restaurant/admin messaging or configured acceptance determines pickup_time.
- Notes: This path replaces rider dispatch for collection orders.
- Sources: Ordelo:watomation/routers/takeaway_hooks.py:324 (restaurant_confirmation_flow); Ordelo:ordelo_datamodels/takeaway/takeaway_summary.sql:1 (restaurant confirmation webhook); Ordelo:ordelo_datamodels/takeaway/takeaway_summary.sql:214 (Caller); Ordelo:watomation/routers/takeaway_hooks.py:323 (Implementation)

#### takeaway-time

- Method/path: `POST /takeaway-hooks/pickup-time-updated`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Area: Logistics; title: Finalize collection pickup time
- Does: Triggered when takeaway_summary.pickup_time changes from NULL to a value.
- Request: `{"takeaway_summary": "<record with finalized pickup_time>"}`
- Response: `Acknowledgement of scheduled work`
- State and side effects: Schedules capture_takeaway_payment and the pickup-time event for the restaurant agent.
- Notes: Online payment is captured here. Pay-at-restaurant requests a print-only job. The restaurant agent receives /order-event-hooks/{rest_ref}/takeaway-pickup-time-updated.
- Sources: Ordelo:watomation/routers/takeaway_hooks.py:534 (pickup_time_updated_hook; _post_pickup_time_event); Ordelo:ordelo_datamodels/takeaway/takeaway_summary.sql:381 (Caller); Ordelo:watomation/routers/takeaway_hooks.py:533 (Implementation)

#### cc23

- Method/path: `SQL /delivery-hooks/delivery-timedout`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: No rider found. Cancels the payment, WhatsApps every restaurant admin (unless configured_auto), and posts to the restaurant webhook.
- Request: `{ delivery_summary: […] }`
- Response: `{ status:"success" }`
- Sources: Ordelo:ordelo_datamodels/delivery/delivery_summary.sql:356 (Caller); Ordelo:watomation/routers/delivery_hooks.py:750 (Implementation)

#### cc24

- Method/path: `SQL /delivery-hooks/notify-missed-dispatches`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: Tells losing riders the job was picked up by someone else, then bulk-marks those dispatches missed so the job will not re-emit them.
- Request: `{ missed_dispatches: [{ order_number, dispatches[] }] }`
- Response: `{ status:"success" }`
- Sources: Ordelo:ordelo_datamodels/dispatch/delivery_inflight.sql:158 (Caller); Ordelo:watomation/routers/delivery_hooks.py:597 (Implementation)

#### cc25

- Method/path: `SQL /delivery-hooks/rider-pickup-alerts`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: Returns instantly and hands off. Routes by audience: rider → run the agent, ops → ops channel, rest_admins → admin WhatsApp.
- Request: ```
{ event_type, timestamp, alerts[{order_number, rider_id, offset_minutes, phase, audience, …}] }
```
- Response: `{ status, alerts_scheduled }`
- Gotcha: The SQL marks checkpoints "sent" on the 2xx, not on actual delivery.
- Sources: Ordelo:ordelo_datamodels/dispatch/job_rider_pickup_alerts.sql:392 (Caller); Ordelo:watomation/routers/delivery_hooks.py:1065 (Implementation)

#### cc26

- Method/path: `SQL /delivery-hooks/close-threads`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: ~5-minute cron. Marks threads inactive and sends a goodbye WhatsApp.
- Request: `[{ thread_id, recipient, last_access_dtts, is_active, minutes_since_last_access }]`
- Response: `{ status, processed_count }`
- Sources: Ordelo:ordelo_datamodels/agent_threads/job_close_thread.sql:46 (Caller); Ordelo:watomation/routers/delivery_hooks.py:833 (Implementation)

#### cc27

- Method/path: `SQL /delivery-hooks/shift-availability-enquiry`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: Immediately sets is_in_shift=false for every listed rider, then asks each one over WhatsApp.
- Request: `{ event_type, timestamp, riders[] }`
- Response: `{ status, riders_scheduled }`
- Sources: Ordelo:ordelo_datamodels/dispatch/enquire_shift_availability.sql:46 (Caller); Ordelo:watomation/routers/delivery_hooks.py:888 (Implementation)

#### cc28

- Method/path: `SQL /delivery-hooks/admin-availability-enquiry`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: Inverts the map to admin→rest_refs so a number administering several restaurants is messaged once.
- Request: `{ event_type, timestamp, restaurant_admins: { REST_REF: [phone] } }`
- Response: `{ status, admins_scheduled }`
- Sources: Ordelo:ordelo_datamodels/restaurant_admin/enquire_admin_availability.sql:53 (Caller); Ordelo:watomation/routers/delivery_hooks.py:975 (Implementation)

#### cc29

- Method/path: `SQL /location-hooks/notify-rider-location-event`
- Direction: `db-ordelo`; status: `live`; flow: Supabase / Postgres → Ordelo
- Does: Geofence enter/exit from process_location_transition.
- Request: `{ event, rid, customer_id, order_number }`
- Response: `{ "event": "success" }`
- Sources: Ordelo:ordelo_datamodels/rider_location/rider_location.sql:77 (Caller); Ordelo:watomation/routers/location_hooks.py:243 (Implementation)

### Direction `ordelo-ext` — ORDELO → microservices (4)

Stripe, pricing and Google Maps. All channel-agnostic.

#### payment-url

- Method/path: `POST {PAYMENT_SERVICE}/threads/{thread_id}/orders/{order_id}/payment-url`
- Direction: `ordelo-ext`; status: `live`; flow: Ordelo → Payment service / Stripe
- Area: Payment; title: Request the hosted payment page
- Does: Ordelo calls the payment microservice and extracts the response url. Both delivery and online takeaway request manual capture.
- Request: ```
{"items": "<order summary items>", "currency": "GBP", "action": "delivery", "manual_mode_capture": true, "restRef": "elas", "notes": "Example only"}
```
- Response: `{"url": "https://payment.example/checkout"}`
- State and side effects: Creates payment-side checkout context; this request is not payment success.
- Notes: Takeaway uses action=collection, product-only items, total_amount, restaurant_confirmation_code=N/A and printonlyjob=false. Ordelo action remains takeaway. Even pay-at-restaurant starts with create-order generating a payment URL.
- Sources: Ordelo:utils_common/payment_ms/payment.py:26 (generate_payment_intent_url; generate_takeaway_manual_payment_url); Ordelo:utils_common/order_management/food_order_pymodel.py:192 (payment_uri; gen_payment_intent_payload)

#### capture

- Method/path: `POST {PAYMENT_SERVICE}/threads/{thread_id}/orders/{order_id}/payment-url`
- Direction: `ordelo-ext`; status: `live`; flow: Ordelo → Payment service / Stripe
- Area: Payment; title: Capture the authorized payment
- Does: The same payment-service URL receives a capture command once the business trigger is met.
- Request: ```
{"payment_mode": "capture", "restaurant_confirmation_code": "<pickup code or N/A>", "total_amount": "<capture total>"}
```
- Response: `Payment-service response; not verified live`
- State and side effects: Delivery capture runs at rider assignment. Takeaway capture runs when pickup_time is first set. Capture also requests the relevant print/receipt behavior.
- Notes: Payload example is a subset. For pay_at_rest, takeaway processing requests a print-only job instead of capture.
- Sources: Ordelo:watomation/routers/delivery_hooks.py:175 (capture_delivery_payment); Ordelo:watomation/routers/takeaway_hooks.py:423 (capture_takeaway_payment); Ordelo:utils_common/order_management/food_order_pymodel.py:339 (gen_capture_payload); Ordelo:utils_common/order_management/food_order_pymodel.py:192 (Caller); Ordelo:utils_common/payment_ms/payment.py:26 (Implementation)

#### cc30

- Method/path: `POST {pricing_url}`
- Direction: `ordelo-ext`; status: `live`; flow: Ordelo → Pricing service
- Does: Single POST to the base URL, no sub-path. The quote path deliberately sends a uuid4 placeholder instead of a real order number.
- Request: `{ total_food_value, restaurant_lat/lon, customer_lat/lon, rest_ref, order_number }`
- Response: ```
delivery_options[] → the car entry gives service_charge, delivery_fee, small_order_fee, commission_rate
```
- Sources: Ordelo:utils_common/order_management/order_service.py:38 (Caller); Ordelo:utils_common/order_management/food_order_pymodel.py:55 (Implementation)

#### cc31

- Method/path: `GET maps.googleapis.com/maps/api/geocode | directions`
- Direction: `ordelo-ext`; status: `live`; flow: Ordelo → Postcode / geocoding
- Does: Called directly, not via a microservice. Keyed by google_settings.maps_api_key.
- Request: `postcode or coordinates`
- Response: `UKAddress / route`
- Sources: Ordelo:utils_common/maps_service/address_resolver.py:104 (Caller); Ordelo:config/google_setting.py:24 (Implementation)

### Direction `wa-ordelo` — WhatsApp → ORDELO (6)

Meta webhook and Flow endpoints.

#### cc32

- Method/path: `WA GET / and POST /  (Meta webhook)`
- Direction: `wa-ordelo`; status: `live`; flow: WhatsApp → Ordelo
- Does: Registered by pywa_async. Every rider, admin and customer message and every callback-button tap lands here and fans out to the registered handlers.
- Request: `WABA update JSON`
- Response: `challenge echo / { status: "ok" }`
- Gotcha: validate_updates=False (fapp_ordelo_agent.py:152) disables Meta webhook signature verification on the one route genuinely exposed to the public internet.
- Sources: Ordelo:watomation/fapp_ordelo_agent.py:147 (Caller); Ordelo:watomation/fapp_ordelo_agent.py:163 (Implementation)

#### cc33

- Method/path: `WA POST /customer-address-capture  (Flow)`
- Direction: `wa-ordelo`; status: `dead`; flow: WhatsApp → Ordelo
- Does: A STUB. Returns hardcoded placeholders ("John Doe - test", "44744123123123") and the completion handler only logs. It does not persist addresses.
- Request: `pywa encrypted Flow request`
- Response: `pywa encrypted Flow response`
- Gotcha: Good news for a web-only channel: real address writes already go through plain HTTP, not this Flow.
- Sources: Ordelo:watomation/fapp_ordelo_agent.py:214 (Caller); Ordelo:watomation/on_flow_request_wa_handler.py:40 (Implementation)

#### cc34

- Method/path: `WA POST /flows/postcode-search  (Flow)`
- Direction: `wa-ordelo`; status: `live`; flow: WhatsApp → Ordelo
- Does: Postcode search Flow.
- Request: `pywa encrypted Flow request`
- Response: `pywa encrypted Flow response`
- Sources: Ordelo:watomation/fapp_ordelo_agent.py:226 (Caller); Ordelo:watomation/on_flow_request_postcode_search.py:1 (Implementation)

#### cc35

- Method/path: `POST /rest-admin/dashboard-session`
- Direction: `wa-ordelo`; status: `live`; flow: WhatsApp → Ordelo
- Does: Resolves rest_ref via restaurant_master.admins @> [wa_number], mints a 30-min token, stores ONLY its SHA-256 hash, and returns {app_url}/rest-admin/activate/{token}.
- Request: `{ wa_number }`
- Response: `{ url, expires_at }`
- Gotcha: This is the real ORDELO↔portal coupling. The frontend never calls it — it only consumes the resulting magic link.
- Sources: Ordelo:watomation/on_message_wa_handler.py:314 (Caller); Ordelo:watomation/routers/rest_admin_auth_session.py:60 (Implementation)

#### cc36

- Method/path: `POST /rider/dashboard-session`
- Direction: `wa-ordelo`; status: `live`; flow: WhatsApp → Ordelo
- Does: 400 rider_not_registered if absent from rider_master, 409 multiple_rider_records if duplicated.
- Request: `{ wa_number }`
- Response: `{ url, expires_at }`
- Sources: Ordelo:watomation/fapp_ordelo_agent.py:134 (Caller); Ordelo:watomation/routers/rider_auth_session.py:48 (Implementation)

#### cc37

- Method/path: `POST /sys-admin/dashboard-session?wa_number=`
- Direction: `wa-ordelo`; status: `live`; flow: WhatsApp → Ordelo
- Does: 403 sys_admin_not_authorized unless the number is in ordelo_config.overwatch_list. Takes a query param deliberately so the coroutine can be called straight from the /sysadmin message handler.
- Request: `query wa_number`
- Response: `{ url, expires_at }`
- Sources: Ordelo:watomation/on_message_wa_handler.py:342 (Caller); Ordelo:watomation/routers/sys_admin_auth_session.py:74 (Implementation)

### Direction `consumer` — Other API consumer → ORDELO (2)

Ordelo capabilities for which no caller was found in the inspected frontend code.

#### minimum

- Method/path: `GET /order-hooks/get-min-order-value`
- Direction: `consumer`; status: `live`; flow: Other API consumer → Ordelo
- Area: Eligibility; title: Check the minimum food value
- Does: Ordelo resolves restaurant coordinates and asks the pricing service for the car delivery option. This endpoint exists, but no direct caller was found in the frontend.
- Request: `{"customer_latitude": 51.4, "customer_longitude": 0.1, "rest_ref": "elas"}`
- Response: `{"status": "ok", "min_order_value": 15, "source": "service"}`
- State and side effects: Pricing service lookup; illustrative £15 is not a live quote.
- Notes: Provide rest_ref or paired restaurant_latitude/restaurant_longitude. The helper can return -1 on service failure as well as an out-of-range result: do not interpret it as a uniquely classified failure.
- Sources: Ordelo:watomation/routers/order_hooks.py:62 (get_min_order_value); Ordelo:utils_common/order_management/order_service.py:123 (get_min_order_value; _call_pricing_service)

#### minimum-postcode

- Method/path: `GET /order-hooks/get-min-order-value-by-postcode`
- Direction: `consumer`; status: `live`; flow: Other API consumer → Ordelo
- Area: Eligibility; title: Check eligibility using postcodes
- Does: Resolves customer and restaurant locations, then uses the minimum-order pricing helper. This is an available Ordelo capability, not a verified frontend call.
- Request: `{"customer_postcode": "<UK postcode>", "rest_ref": "elas"}`
- Response: `{"status": "ok", "min_order_value": 15, "source": "service"}`
- State and side effects: Postcode resolution followed by pricing lookup.
- Notes: Restaurant location can be supplied via rest_ref or restaurant_postcode.
- Sources: Ordelo:watomation/routers/order_hooks.py:137 (get_min_order_value_by_postcode)

### Direction `diag` — Diagnostics (unauthenticated) (5)

No API key, no JWT, no signature check on any of these.

#### cc38

- Method/path: `POST /payment-hooks/payment-complete-test/{order_id}`
- Direction: `diag`; status: `live`; flow: Other API consumer → Ordelo
- Does: Replays the entire payment-complete flow without Stripe.
- Request: `path order_id`
- Response: `{ "success": "success" }`
- Gotcha: Unauthenticated, and it force-marks ANY order as paid and kicks off delivery/takeaway init.
- Sources: Ordelo:watomation/routers/payment_hooks.py:150 (Implementation)

#### cc39

- Method/path: `GET /details  |  /restaurant-details/{rest_ref}`
- Direction: `diag`; status: `live`; flow: Other API consumer → Ordelo
- Does: Diagnostics. /restaurant-details resolves every WEBHOOK_PATHS entry for a restaurant — useful for confirming the triangle wiring.
- Request: `—`
- Response: `phone-number + resolved base URLs + admins`
- Sources: Ordelo:watomation/fapp_ordelo_agent.py:240 (Implementation)

#### cc40

- Method/path: `GET /threads  |  /debug-state  |  /thread-hooks/debug-*`
- Direction: `diag`; status: `live`; flow: Other API consumer → Ordelo
- Does: Six debug routes on thread_hooks plus two at app level. All unauthenticated.
- Request: `recipient or thread_id`
- Response: `LangGraph checkpoint state`
- Sources: Ordelo:watomation/routers/thread_hooks.py:90 (Implementation)

#### cc41

- Method/path: `GET /location-hooks/live-location-map/{order_number}`
- Direction: `diag`; status: `live`; flow: Customer browser → Ordelo
- Does: DIRECTLY BROWSER-FACING — one of only two such routes. The URL is minted for the customer and sent as a WhatsApp button. 404 when there is no location fix.
- Request: `path order_number`
- Response: `302 → https://maps.google.com/?q=…`
- Sources: Restaurant agents:.../rider_event_hooks.py:208 (Caller); Ordelo:watomation/routers/location_hooks.py:159 (Implementation)

#### cc42

- Method/path: `POST /takeaway-hooks/init-takeaway-order`
- Direction: `diag`; status: `dead`; flow: Other API consumer → Ordelo
- Does: No caller exists in any of the repos. The source comment at takeaway_hooks.py:600 asks "Where is this called?" — and it is right.
- Request: `{ order_number, customer_id | recipient }`
- Response: `{ status:"accepted", order_number }`
- Sources: Ordelo:watomation/routers/takeaway_hooks.py:601 (Implementation)

## 4. Portals

The restaurant frontend hosts four applications. Only **customer** and **sys-admin** call Ordelo. **rest-admin** and **rider** read Postgres directly; their only Ordelo coupling is the magic link that lets them in.

| portal | live Ordelo calls | entry cookie | data path |
|---|---|---|---|
| Customer ordering (`customer`) | 4 | `none — WhatsApp deep-link parameters` | Next.js API routes proxy to Ordelo; menu from the menu service; hours from Supabase. |
| Restaurant admin (`rest-admin`) | 0 | `__Host-radash` | Supabase views read directly through a tenant-scoped Proxy client. |
| Rider (`rider`) | 0 | `__Host-rdash` | Supabase delivery_dispatch read directly, scoped by rider_id. |
| System admin (`sys-admin`) | 2 | `__Host-sdash` | Ordelo for rider payouts; Supabase for restaurants and config. |

### Portal `customer` — Customer ordering

The only portal that really talks to ORDELO — 4 of the 6 live calls.

- Entry: WhatsApp deep link carrying ?recipient=&thread_id=&order_type=&minimum_order=
- Session: The pair (recipient, thread_id). No cookie, no signature. Cart is in-memory React Context; handoff to /order-summary is sessionStorage["order_summary"].
- Pages: `app/restaurant/[id]/page.tsx`, `app/order-summary/page.tsx`, `app/address-update/page.tsx`, `app/checkout-error/page.tsx`
- Calls:
  - `POST /api/checkout` → ORDELO create-order (Ordelo-facing)
  - `GET /api/verify-session` → ORDELO get-active-thread (proxied on to restaurant-agents) (Ordelo-facing)
  - `POST /api/capture-address` → ORDELO capture-address (Ordelo-facing)
  - `POST /api/pay-at-restaurant` → ORDELO pay-at-restaurant (Ordelo-facing)
  - `GET /api/menu` → byteloop menu service
  - `GET /api/postcode-lookup/[postcode]` → postcodes.io + Google
  - `GET /api/restaurant-hours/[id]` → Supabase restaurant_master.service_hours_json
- Gotcha: None of these four ORDELO-facing routes is inside the middleware matcher (middleware.ts:186-194), so all are unauthenticated and callable by anyone who can reach the host.

### Portal `rest-admin` — Restaurant admin

Never calls ORDELO at all. Reads Postgres directly through a tenant-scoped Proxy.

- Entry: Magic link minted by ORDELO from WhatsApp → /rest-admin/activate/[token] → __Host-radash cookie.
- Session: Opaque cookie → auth_sessions row. 60-minute idle timeout, 4-hour hard cap, enforced in middleware.ts.
- Pages: `app/rest-admin/page.tsx`, `app/rest-admin/orders/page.tsx`, `app/rest-admin/reports/page.tsx`, `app/rest-admin/actions/page.tsx`, `app/rest-admin/more/page.tsx`
- Calls:
  - `GET /api/rest-admin/orders` → Supabase v_admin_orders (keyset paginated, 30s refresh)
  - `GET /api/rest-admin/orders/summary` → Supabase v_admin_orders_daily
  - `GET /api/rest-admin/orders/[order_number]/items` → Supabase v_admin_order_items
  - `POST /api/rest-admin/logout` → clears the session row
- Gotcha: lib/rest-admin-session.ts:28-38 declares TENANT_SCOPED_TABLES and a JS Proxy (line 348) auto-injects .eq("rest_ref", session.rest_ref). Tenant isolation is enforced in JavaScript, not by RLS — the server client uses the secret key and bypasses RLS.

### Portal `rider` — Rider

Also never calls ORDELO. Same Supabase-direct pattern, scoped by rider_id.

- Entry: Magic link from ORDELO → /rider/activate/[token] → __Host-rdash cookie. Minted by rider_auth_session.py:48.
- Session: auth_sessions row with role=rider, scope_ref=rider_id.
- Pages: `app/rider/page.tsx`, `app/rider/jobs/page.tsx`, `app/rider/more/page.tsx`, `app/rider/expired/page.tsx`
- Calls:
  - `GET /api/rider/jobs` → Supabase delivery_dispatch (keyset paginated)
  - `GET /api/rider/jobs/summary` → Supabase delivery_dispatch earnings rollup
  - `GET rider_master / rider_registrations` → browser-side Supabase client (RLS-respecting)
  - `POST /api/rider/logout` → clears the session row
- Gotcha: The rider PORTAL is read-only. Everything a rider actually does that changes state — accepting a dispatch, confirming codes, going on shift — happens over WhatsApp, not here.

### Portal `sys-admin` — System admin

The only admin portal touching ORDELO — the remaining 2 of the 6 live calls.

- Entry: Magic link from ORDELO → /sys-admin/activate/[token] → __Host-sdash cookie. Gated on ordelo_config.overwatch_list.
- Session: auth_sessions row with role=sys_admin.
- Pages: `app/sys-admin/page.tsx`, `app/sys-admin/restaurants/page.tsx`, `app/sys-admin/rider-payouts/page.tsx`, `app/sys-admin/riders-inshift/page.tsx`
- Calls:
  - `GET /api/sys-admin/rider-payouts/report` → ORDELO GET /sys-admin/rider-payout (Ordelo-facing)
  - `POST /api/sys-admin/rider-payouts/mark-paid` → ORDELO POST /sys-admin/update-paid (Ordelo-facing)
  - `GET /api/sys-admin/rider-payouts/summary` → Supabase delivery_dispatch + rider_master
  - `GET/PATCH /api/sys-admin/restaurants/[rest_ref]` → Supabase restaurant_master
  - `GET/PATCH /api/sys-admin/restaurants/[rest_ref]/config` → Supabase ordelo_config
- Gotcha: The config PATCH writes the very ordelo_config row (ORDELO_APP_URL) that lib/config.ts reads to find ORDELO. Change it and the frontend repoints itself — after the 60s cache expires, per container.

## 5. Scenarios and step-by-step flows

### Scenario `delivery` — Delivery · online payment

Follow an existing customer session from menu to rider completion.

1. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
2. **Load menu and opening hours** (`menu`; Restaurant frontend → Menu service; kind: HTTP + DB read)
   - Menu data comes from MENU_API_URL using apiName. Hours come directly from restaurant_master through the frontend. Cart state, customizations and discounts are handled in the browser.
   - State: Browser basket; no food_order record.
   - Endpoint: `hours`
   - Sources: Frontend:app/api/menu/route.ts:49 (GET); Frontend:lib/restaurantHours.ts:22 (getServiceHours)
3. **Check the existing customer session** (`session`; Restaurant frontend → Ordelo; kind: HTTP proxy)
   - When session parameters are present, the page checks the active thread. The basket repeats the check before checkout. Ordelo delegates to the restaurant agent; the browser compares thread IDs.
   - State: Only a matching active thread permits this checkout path.
   - Endpoint: `verify`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread)
4. **Submit the basket** (`checkout`; Customer browser → Restaurant frontend; kind: HTTP POST)
   - The basket supplies discounted item prices and notes. Next.js resolves orderApiName ?? apiName, converts threadId → thread_id and orderItems → order_items, then calls Ordelo create-order.
   - State: Order request prepared; item order_id values are placeholders.
   - Endpoint: `checkout`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/api/checkout/route.ts:5 (POST)
5. **Ordelo creates the order** (`create`; Ordelo → Supabase / Postgres; kind: RPC + DB write)
   - Ordelo uses get_next_daily_seq and the recipient/date reference to create order_id and order_number. It inserts food_order and order_item. Delivery pricing uses stored customer coordinates to update charges.
   - State: food_order.payment_status = requires_payment
   - Endpoint: `create`
   - Sources: Ordelo:utils_common/order_management/order_service.py:172 (create_order_with_items); Ordelo:utils_common/order_management/food_order_pymodel.py:214 (update_final_order_value_in_db)
6. **Request the payment page URL** (`url`; Ordelo → Payment service / Stripe; kind: HTTP POST)
   - Ordelo asks the payment service for a URL, then returns it with the order number and fees. Delivery and takeaway both request manual capture. This also occurs before the pay-at-restaurant choice.
   - State: Payment URL available; no payment has been authorized yet.
   - Endpoint: `payment-url`
   - Sources: Ordelo:watomation/routers/order_hooks.py:233 (create_order); Ordelo:utils_common/payment_ms/payment.py:71 (generate_takeaway_manual_payment_url)
7. **Show the browser order summary** (`summary`; Restaurant frontend → Customer browser; kind: Browser state)
   - The basket stores order_summary in sessionStorage and navigates to /order-summary. TakeawayPayment controls whether collection is paid online or at the restaurant.
   - State: The summary is tab-local state, not an order-status lookup.
   - Endpoint: `pay-local`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/order-summary/page.tsx:33 (OrderSummaryPage)
8. **Open the hosted payment page** (`redirect`; Customer browser → Payment service / Stripe; kind: Browser redirect)
   - Pay now sets window.location.href to payment_intent_url. The payment provider collects payment details. The external payment service’s success/cancel URL configuration is outside these repositories.
   - State: Customer authorization occurs on the hosted payment page.
   - Endpoint: `payment-url`
   - Sources: Frontend:app/order-summary/page.tsx:91 (handlePayNow)
9. **Receive authorization notification** (`authorized`; Payment service / Stripe → Ordelo; kind: Webhook)
   - Ordelo consumes the Stripe-shaped completion event, sets requires_capture and schedules two activities: notify the restaurant agent and initialize the delivery or takeaway summary.
   - State: requires_payment → requires_capture
   - Endpoint: `authorized`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:106 (payment_complete_path)
10. **Update the customer conversation** (`notify`; Ordelo → Restaurant agent; kind: Background HTTP)
   - handle_payment_complete sends the FoodOrder model to the configured restaurant-agent payment-complete hook. This is a backend notification, not a response to the browser.
   - State: Customer conversation receives the order context.
   - Endpoint: `payment-event`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:38 (handle_payment_complete); Ordelo:config/params.py:66 (WEBHOOK_PATHS)
11. **Initialize delivery and restaurant confirmation** (`delivery-init`; Ordelo → Supabase / Postgres; kind: Background RPC → DB trigger)
   - init_delivery_summary calls init_delivery. The delivery summary and subsequent SQL state transitions drive restaurant confirmation and dispatch. The exact production cron/trigger configuration is not verified.
   - State: Delivery summary exists; restaurant/pickup state drives progress.
   - Endpoint: `confirm`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:80 (init_delivery_summary); Ordelo:ordelo_datamodels/delivery/delivery_summary.sql:1 (restaurant confirmation webhook)
12. **Send rider offers** (`dispatch`; Supabase / Postgres → Ordelo; kind: DB webhook → WhatsApp)
   - A dispatch trigger calls /delivery-hooks/delivery-dispatch. Ordelo sends Accept/Decline buttons to eligible riders. Callback handling updates delivery_dispatch; database transitions determine assignment.
   - State: Offered → accepted/assigned through callback and DB processing.
   - Endpoint: `dispatch`
   - Sources: Ordelo:watomation/routers/delivery_hooks.py:434 (delivery_dispatch_hook); Ordelo:watomation/on_callback_wa_handler.py:60 (dispatch_response)
13. **Start the assigned rider job** (`inflight`; Supabase / Postgres → Ordelo; kind: DB webhook + background work)
   - The inflight webhook schedules payment capture, the restaurant-agent rider-inflight notification, an admin receipt and the LangGraph rider journey.
   - State: Assigned rider; capture requested; instructions sent.
   - Endpoint: `inflight`
   - Sources: Ordelo:watomation/routers/delivery_hooks.py:522 (delivery_inflight_graph_init_hook)
14. **Capture the authorized amount** (`capture`; Ordelo → Payment service / Stripe; kind: HTTP capture command)
   - Delivery capture is requested during assignment. The payment-service command uses payment_mode=capture and the restaurant confirmation code. The HTTP background acknowledgement alone does not establish settlement.
   - State: Payment capture and receipt processing delegated to payment service.
   - Endpoint: `capture`
   - Sources: Ordelo:watomation/routers/delivery_hooks.py:175 (capture_delivery_payment)
15. **Confirm pickup and delivery** (`complete`; WhatsApp → Ordelo; kind: Messages + tool calls)
   - The rider agent verifies restaurant and customer confirmation codes. Pickup changes dispatch state to pickedup; completion calls dispatch_complete_func. Ordelo emits progress events to the restaurant agent.
   - State: pickedup → completed; rider thread/job closes.
   - Endpoint: `rider-event`
   - Sources: Ordelo:ordelo/agents/rider_agent.py:735 (verify_restaurant_confirmation_code; verify_customer_confirmation_code); Ordelo:ordelo/agent_app_handlers.py:502 (post_rider_event_customer_cc)

### Scenario `takeaway` — Collection · online payment

Requires takeawayPayment enabled; Ordelo order_type is takeaway.

1. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
2. **Load menu and opening hours** (`menu`; Restaurant frontend → Menu service; kind: HTTP + DB read)
   - Menu data comes from MENU_API_URL using apiName. Hours come directly from restaurant_master through the frontend. Cart state, customizations and discounts are handled in the browser.
   - State: Browser basket; no food_order record.
   - Endpoint: `hours`
   - Sources: Frontend:app/api/menu/route.ts:49 (GET); Frontend:lib/restaurantHours.ts:22 (getServiceHours)
3. **Check the existing customer session** (`session`; Restaurant frontend → Ordelo; kind: HTTP proxy)
   - When session parameters are present, the page checks the active thread. The basket repeats the check before checkout. Ordelo delegates to the restaurant agent; the browser compares thread IDs.
   - State: Only a matching active thread permits this checkout path.
   - Endpoint: `verify`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread)
4. **Submit the basket** (`checkout`; Customer browser → Restaurant frontend; kind: HTTP POST)
   - The basket supplies discounted item prices and notes. Next.js resolves orderApiName ?? apiName, converts threadId → thread_id and orderItems → order_items, then calls Ordelo create-order.
   - State: Order request prepared; item order_id values are placeholders.
   - Endpoint: `checkout`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/api/checkout/route.ts:5 (POST)
5. **Ordelo creates the order** (`create`; Ordelo → Supabase / Postgres; kind: RPC + DB write)
   - Ordelo uses get_next_daily_seq and the recipient/date reference to create order_id and order_number. It inserts food_order and order_item. Delivery pricing uses stored customer coordinates to update charges.
   - State: food_order.payment_status = requires_payment
   - Endpoint: `create`
   - Sources: Ordelo:utils_common/order_management/order_service.py:172 (create_order_with_items); Ordelo:utils_common/order_management/food_order_pymodel.py:214 (update_final_order_value_in_db)
6. **Request the payment page URL** (`url`; Ordelo → Payment service / Stripe; kind: HTTP POST)
   - Ordelo asks the payment service for a URL, then returns it with the order number and fees. Delivery and takeaway both request manual capture. This also occurs before the pay-at-restaurant choice.
   - State: Payment URL available; no payment has been authorized yet.
   - Endpoint: `payment-url`
   - Sources: Ordelo:watomation/routers/order_hooks.py:233 (create_order); Ordelo:utils_common/payment_ms/payment.py:71 (generate_takeaway_manual_payment_url)
7. **Show the browser order summary** (`summary`; Restaurant frontend → Customer browser; kind: Browser state)
   - The basket stores order_summary in sessionStorage and navigates to /order-summary. TakeawayPayment controls whether collection is paid online or at the restaurant.
   - State: The summary is tab-local state, not an order-status lookup.
   - Endpoint: `pay-local`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/order-summary/page.tsx:33 (OrderSummaryPage)
8. **Open the hosted payment page** (`redirect`; Customer browser → Payment service / Stripe; kind: Browser redirect)
   - Pay now sets window.location.href to payment_intent_url. The payment provider collects payment details. The external payment service’s success/cancel URL configuration is outside these repositories.
   - State: Customer authorization occurs on the hosted payment page.
   - Endpoint: `payment-url`
   - Sources: Frontend:app/order-summary/page.tsx:91 (handlePayNow)
9. **Receive authorization notification** (`authorized`; Payment service / Stripe → Ordelo; kind: Webhook)
   - Ordelo consumes the Stripe-shaped completion event, sets requires_capture and schedules two activities: notify the restaurant agent and initialize the delivery or takeaway summary.
   - State: requires_payment → requires_capture
   - Endpoint: `authorized`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:106 (payment_complete_path)
10. **Update the customer conversation** (`notify`; Ordelo → Restaurant agent; kind: Background HTTP)
   - handle_payment_complete sends the FoodOrder model to the configured restaurant-agent payment-complete hook. This is a backend notification, not a response to the browser.
   - State: Customer conversation receives the order context.
   - Endpoint: `payment-event`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:38 (handle_payment_complete); Ordelo:config/params.py:66 (WEBHOOK_PATHS)
11. **Initialize the takeaway workflow** (`takeaway-init`; Ordelo → Supabase / Postgres; kind: Background RPC → DB trigger)
   - init_takeaway creates the collection summary. Restaurant confirmation or configured auto-accept establishes pickup_time; no rider dispatch is needed for this branch.
   - State: Takeaway summary awaiting or receiving pickup_time.
   - Endpoint: `takeaway-confirm`
   - Sources: Ordelo:watomation/routers/takeaway_hooks.py:122 (init_takeaway_summary); Ordelo:ordelo_datamodels/takeaway/takeaway_summary.sql:1 (confirmation webhook)
12. **Finalize pickup time and payment** (`takeaway-time`; Supabase / Postgres → Ordelo; kind: DB webhook → payment service)
   - The first pickup_time triggers /takeaway-hooks/pickup-time-updated. Online takeaway captures the authorized payment; pay_at_rest generates a print-only job. Ordelo sends the pickup-time event to the restaurant agent.
   - State: Collection time available; capture or print requested.
   - Endpoint: `takeaway-time`
   - Sources: Ordelo:watomation/routers/takeaway_hooks.py:534 (pickup_time_updated_hook; capture_takeaway_payment)

### Scenario `cash` — Collection · pay at restaurant

An order and payment URL are created before the customer chooses payment on collection.

1. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
2. **Load menu and opening hours** (`menu`; Restaurant frontend → Menu service; kind: HTTP + DB read)
   - Menu data comes from MENU_API_URL using apiName. Hours come directly from restaurant_master through the frontend. Cart state, customizations and discounts are handled in the browser.
   - State: Browser basket; no food_order record.
   - Endpoint: `hours`
   - Sources: Frontend:app/api/menu/route.ts:49 (GET); Frontend:lib/restaurantHours.ts:22 (getServiceHours)
3. **Check the existing customer session** (`session`; Restaurant frontend → Ordelo; kind: HTTP proxy)
   - When session parameters are present, the page checks the active thread. The basket repeats the check before checkout. Ordelo delegates to the restaurant agent; the browser compares thread IDs.
   - State: Only a matching active thread permits this checkout path.
   - Endpoint: `verify`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread)
4. **Submit the basket** (`checkout`; Customer browser → Restaurant frontend; kind: HTTP POST)
   - The basket supplies discounted item prices and notes. Next.js resolves orderApiName ?? apiName, converts threadId → thread_id and orderItems → order_items, then calls Ordelo create-order.
   - State: Order request prepared; item order_id values are placeholders.
   - Endpoint: `checkout`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/api/checkout/route.ts:5 (POST)
5. **Ordelo creates the order** (`create`; Ordelo → Supabase / Postgres; kind: RPC + DB write)
   - Ordelo uses get_next_daily_seq and the recipient/date reference to create order_id and order_number. It inserts food_order and order_item. Delivery pricing uses stored customer coordinates to update charges.
   - State: food_order.payment_status = requires_payment
   - Endpoint: `create`
   - Sources: Ordelo:utils_common/order_management/order_service.py:172 (create_order_with_items); Ordelo:utils_common/order_management/food_order_pymodel.py:214 (update_final_order_value_in_db)
6. **Request the payment page URL** (`url`; Ordelo → Payment service / Stripe; kind: HTTP POST)
   - Ordelo asks the payment service for a URL, then returns it with the order number and fees. Delivery and takeaway both request manual capture. This also occurs before the pay-at-restaurant choice.
   - State: Payment URL available; no payment has been authorized yet.
   - Endpoint: `payment-url`
   - Sources: Ordelo:watomation/routers/order_hooks.py:233 (create_order); Ordelo:utils_common/payment_ms/payment.py:71 (generate_takeaway_manual_payment_url)
7. **Show the browser order summary** (`summary`; Restaurant frontend → Customer browser; kind: Browser state)
   - The basket stores order_summary in sessionStorage and navigates to /order-summary. TakeawayPayment controls whether collection is paid online or at the restaurant.
   - State: The summary is tab-local state, not an order-status lookup.
   - Endpoint: `pay-local`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/order-summary/page.tsx:33 (OrderSummaryPage)
8. **Submit pay-at-restaurant choice** (`cash`; Restaurant frontend → Ordelo; kind: HTTP POST)
   - The summary sends the already-created order_number through /api/pay-at-restaurant. Ordelo finds it using the request field named order_id and marks the takeaway order pay_at_rest.
   - State: requires_payment → pay_at_rest
   - Endpoint: `pay-rest`
   - Sources: Frontend:app/api/pay-at-restaurant/route.ts:5 (POST); Ordelo:watomation/routers/payment_hooks.py:206 (pay_at_restaurant)
9. **Update the customer conversation** (`notify`; Ordelo → Restaurant agent; kind: Background HTTP)
   - handle_payment_complete sends the FoodOrder model to the configured restaurant-agent payment-complete hook. This is a backend notification, not a response to the browser.
   - State: Customer conversation receives the order context.
   - Endpoint: `payment-event`
   - Sources: Ordelo:watomation/routers/payment_hooks.py:38 (handle_payment_complete); Ordelo:config/params.py:66 (WEBHOOK_PATHS)
10. **Initialize the takeaway workflow** (`takeaway-init`; Ordelo → Supabase / Postgres; kind: Background RPC → DB trigger)
   - init_takeaway creates the collection summary. Restaurant confirmation or configured auto-accept establishes pickup_time; no rider dispatch is needed for this branch.
   - State: Takeaway summary awaiting or receiving pickup_time.
   - Endpoint: `takeaway-confirm`
   - Sources: Ordelo:watomation/routers/takeaway_hooks.py:122 (init_takeaway_summary); Ordelo:ordelo_datamodels/takeaway/takeaway_summary.sql:1 (confirmation webhook)
11. **Finalize pickup time and payment** (`takeaway-time`; Supabase / Postgres → Ordelo; kind: DB webhook → payment service)
   - The first pickup_time triggers /takeaway-hooks/pickup-time-updated. Online takeaway captures the authorized payment; pay_at_rest generates a print-only job. Ordelo sends the pickup-time event to the restaurant agent.
   - State: Collection time available; capture or print requested.
   - Endpoint: `takeaway-time`
   - Sources: Ordelo:watomation/routers/takeaway_hooks.py:534 (pickup_time_updated_hook; capture_takeaway_payment)

### Scenario `address` — Address & delivery eligibility

Separate capabilities and current handoffs; the minimum-order lookup is not wired directly into the frontend.

1. **Capture the customer address** (`address`; Restaurant frontend → Ordelo; kind: HTTP + DB write)
   - The separate address page resolves postcodes using its own route, then sends coordinates and address details to Ordelo. Ordelo upserts customer_master and notifies the restaurant agent.
   - State: Customer coordinates persist under recipient.
   - Endpoint: `address`
   - Sources: Frontend:app/address-update/page.tsx:38 (handleLookup; handleSubmit); Ordelo:watomation/routers/order_hooks.py:342 (capture_address)
2. **Understand delivery eligibility** (`minimum`; Ordelo → Pricing service; kind: Available HTTP capability)
   - Ordelo exposes minimum-order endpoints. The current frontend does not call them directly; it reads distance and minimum_order from menu URL parameters and compares the discounted basket against the minimum.
   - State: The displayed minimum is passed-in context; no live quote is simulated here.
   - Endpoint: `minimum`
   - Sources: Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData); Frontend:components/BasketDrawer.tsx:72 (meetsMinimum); Ordelo:watomation/routers/order_hooks.py:62 (get_min_order_value)
3. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
4. **Check the existing customer session** (`session`; Restaurant frontend → Ordelo; kind: HTTP proxy)
   - When session parameters are present, the page checks the active thread. The basket repeats the check before checkout. Ordelo delegates to the restaurant agent; the browser compares thread IDs.
   - State: Only a matching active thread permits this checkout path.
   - Endpoint: `verify`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread)

### Scenario `missing` — Website visit · missing session

The current direct-website journey stops at checkout.

1. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
2. **Load menu and opening hours** (`menu`; Restaurant frontend → Menu service; kind: HTTP + DB read)
   - Menu data comes from MENU_API_URL using apiName. Hours come directly from restaurant_master through the frontend. Cart state, customizations and discounts are handled in the browser.
   - State: Browser basket; no food_order record.
   - Endpoint: `hours`
   - Sources: Frontend:app/api/menu/route.ts:49 (GET); Frontend:lib/restaurantHours.ts:22 (getServiceHours)
3. **Stop: website visitor has no session** (`missing`; Customer browser → Restaurant frontend; kind: Blocked)
   - A direct visitor can see the menu, but checkout sends them to /checkout-error when recipient or thread_id is missing. No create-order request is sent.
   - State: No new order or payment URL.
   - Endpoint: `checkout`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Frontend:app/checkout-error/page.tsx:5 (CheckoutErrorPage)

### Scenario `expired` — WhatsApp link · expired session

A thread mismatch or verification failure invokes WhatsApp-based recovery.

1. **Choose a restaurant** (`browse`; Customer browser → Restaurant frontend; kind: Browser)
   - The landing page lists frontend-configured restaurants. A menu link can carry recipient, thread_id, distance, minimum_order and order_type. A plain website visit can browse without those parameters.
   - State: No order yet. Customer context may be missing.
   - Endpoint: `menu`
   - Sources: Frontend:app/page.tsx:7 (Home); Frontend:app/restaurant/[id]/page.tsx:15 (restaurantData)
2. **Check the existing customer session** (`session`; Restaurant frontend → Ordelo; kind: HTTP proxy)
   - When session parameters are present, the page checks the active thread. The basket repeats the check before checkout. Ordelo delegates to the restaurant agent; the browser compares thread IDs.
   - State: Only a matching active thread permits this checkout path.
   - Endpoint: `verify`
   - Sources: Frontend:components/BasketDrawer.tsx:64 (handleCheckout); Ordelo:watomation/routers/order_hooks.py:400 (get_active_thread)
3. **Stop: thread expired or mismatched** (`expired`; Restaurant frontend → WhatsApp; kind: Browser recovery)
   - The menu page or basket sends the customer to /address-update?session_expired=true&rest_ref=… on a mismatch, -1 or verification failure. That screen offers “Start new conversation” through WhatsApp.
   - State: Current recovery requires a customer conversation.
   - Endpoint: `active`
   - Sources: Frontend:app/restaurant/[id]/page.tsx:39 (validateSession); Frontend:app/address-update/page.tsx:161 (sessionExpired)

## 6. Website-channel gaps

Implications of a customer ordering entirely on the website. They do not by themselves require replacing rider or restaurant-admin channels.

### identity — Create a customer session from the website

- Tag: Session dependency
- Affected actors: Customer browser, Restaurant frontend, Ordelo, Restaurant agent
- What exists today: The existing basket needs recipient and thread_id, and checks the active restaurant-agent thread. Ordinary website visitors have neither. No website session-creation endpoint was found in this customer ordering path.
- Missing capability: A website channel needs a way to establish customer identity and order context independently of a WhatsApp conversation.
- Related endpoints: `verify`, `active`, `checkout`
- Related scenario: `missing`

### address — Complete address capture without returning to chat

- Tag: Recovery dependency
- Affected actors: Customer browser, Restaurant frontend, Ordelo, WhatsApp
- What exists today: Address capture is already reusable, but recipient arrives in the URL and the success/recovery pages link back to WhatsApp.
- Missing capability: Website customers need ownership of their address and a route back into checkout after capture or expiry.
- Related endpoints: `postcode`, `address-proxy`, `address`
- Related scenario: `address`

### eligibility — Obtain current delivery eligibility on the website

- Tag: Unconnected capability
- Affected actors: Restaurant frontend, Ordelo, Pricing service
- What exists today: distance and minimum_order are URL parameters. Ordelo has pricing-backed minimum-order endpoints, but no direct frontend caller was found. The pricing helper also uses -1 for a service failure.
- Missing capability: The website needs to obtain and explain delivery eligibility and minimum value from customer location, including distinct unavailable-service and out-of-range outcomes.
- Related endpoints: `minimum`, `minimum-postcode`
- Related scenario: `address`

### validation — Make checkout decisions authoritative

- Tag: Validation boundary
- Affected actors: Customer browser, Restaurant frontend, Ordelo, Supabase / Postgres
- What exists today: The browser checks thread validity and minimum basket value. Next.js checkout checks required fields; Ordelo sums submitted item prices. The inspected create-order code does not perform a menu-price relookup.
- Missing capability: A public website channel needs explicit server ownership for session, restaurant, price, discount and eligibility validation. Removing the browser check alone would not provide this.
- Related endpoints: `checkout`, `create`
- Related scenario: `delivery`

### recovery — Recover an order after redirects or reloads

- Tag: Browser state dependency
- Affected actors: Customer browser, Restaurant frontend, Payment service / Stripe, Ordelo
- What exists today: The summary is held in sessionStorage and navigates home when missing. Pay-at-restaurant shows an alert and returns to the menu. Hosted payment success/cancel routes are controlled outside the inspected code.
- Missing capability: The website needs persistent customer order lookup and a defined payment-return and retry experience. This guide does not assume the payment provider already supplies it.
- Related endpoints: `payment-url`, `authorized`, `pay-local`
- Related scenario: `cash`

### status — Surface progress in the customer website

- Tag: Notification dependency
- Affected actors: Ordelo, Restaurant agent, Restaurant frontend, WhatsApp
- What exists today: Payment, address, rider assignment and delivery events are sent to the restaurant agent. The inspected frontend has operational dashboards, but no customer order-status view in this checkout flow.
- Missing capability: The website needs customer-visible acceptance, pickup/delivery progress and failure states. Existing rider/admin WhatsApp operations can be considered separately from customer-channel changes.
- Related endpoints: `payment-event`, `rider-event`, `inflight`
- Related scenario: `delivery`

### contracts — Resolve existing contract ambiguities

- Tag: Observed mismatches
- Affected actors: Restaurant frontend, Ordelo, Payment service / Stripe, Supabase / Postgres
- What exists today: Next.js forwards subtotal/total even though Ordelo create-order omits them. The pay-at-restaurant field order_id actually carries order_number. An order/payment URL can exist before checkout completes.
- Missing capability: These contracts need explicit meanings before reuse in a second customer channel, including retries and reconciliation. The inspected payment-complete handler has no explicit duplicate-event guard.
- Related endpoints: `create`, `checkout`, `pay-rest`, `authorized`
- Related scenario: `cash`

## 7. Evidence, boundaries and observed mismatches

| finding | evidence | meaning |
|---|---|---|
| Session check is separate from order creation | BasketDrawer.handleCheckout ; app/api/checkout/route.ts | UI validation is not an independent server authorization guarantee. |
| Ordelo omits subtotal / total | order_hooks.create_order return object | Next.js forwards them if available; the browser has fallback arithmetic. Do not assume a canonical total is returned here. |
| order_id can mean order_number in pay-at-restaurant | payment_hooks.pay_at_restaurant filters by order_number | Preserve the exact wire behavior when understanding the existing flow. |
| Payment completion means requires_capture | payment_complete_path ; delivery and takeaway capture handlers | Payment authorization and later capture must be explained separately. |
| Minimum lookup is not a frontend call | Frontend call sites and menu query parsing | An existing Ordelo capability is not evidence of an already-integrated website feature. |
| Minimum helper can return -1 on upstream failure | order_service.get_min_order_value | Do not present -1 as exclusively “outside delivery range”. |
| Direction catalogue and portal data merged from a second inspection | Entries cite file:line on the dev branches of OrdeloAgent, restaurant-frontend and restaurant-agents | Line numbers may not match the commits pinned above; recheck against those commits before relying on them. |

Primary sources: restaurant-frontend pages, API routes, config and basket; Ordelo order/payment/delivery/takeaway routers, order models, payment helpers and SQL trigger definitions. Restaurant-agent route names are grounded in Ordelo outbound URL construction. The map omits operational dashboard details except the shared-database boundary. No future API paths or new schemas are asserted.

## 8. Read-this-carefully rules for agents

- An existing Ordelo capability is not evidence that the frontend already uses it (see `minimum`, `minimum-postcode`, `consumer` direction).
- Payment authorisation (`requires_capture`) and later capture are separate steps.
- `order_id` can mean `order_number` in pay-at-restaurant; preserve the wire behaviour.
- Ordelo omits subtotal/total from create-order; do not assume a canonical total is returned.
- Minimum-order helper can return -1 on upstream failure; do not read -1 as only "outside delivery range".
- Tenant isolation in rest-admin is enforced in JavaScript (a Proxy injecting `rest_ref`), not by database RLS.
- Rider and restaurant state changes (accept dispatch, confirm order, pickup time) happen over WhatsApp callbacks, not HTTP endpoints.
- Catalogue entries `capture` and `payment-url` share one path in the source data; they are distinguished by description, not by path.
