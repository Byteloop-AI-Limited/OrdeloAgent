# Ordelo web ordering channel (ordelo-agg): design and release plan

- **Target repository:** `OrdeloAgent` → `plans/ordelo-agg-plan-cc.md` (branch `release/ordelo-agg`)
- **Status (2026-10-01, after go-live):** R0 (front end, fixtures) and R1a (Ordelo) plus the test-payment addendum (D32) are **live in production**, and every R1a verification gap is closed. Next is **R1b**, then **R2**. The R0 front-end findings were deferred to the R3 entry gate (D34) and then fixed on 2026-10-01 (uncommitted in restaurant-frontend; only the Lighthouse check remains); scheduling the init reconciler is deferred (D33). **A new session should start at "Resume here" below.**
- **Revised 2026-10-01:** the payment-service contract stays unchanged for web; web-specific payment behaviour moves into Ordelo's `payment-complete` (D22–D27). Glossary in `CONTEXT.md`; decisions in ADR-0003, ADR-0004 and ADR-0005.
- **Evidence snapshot:** 2026-09-29. OrdeloAgent `7697e15` (`release/ordelo-agg`), restaurant-frontend `a75312e` (`dev`), restaurant-agents `eeb6a3c` (`main`). Payment service `58158ca` read on 2026-10-01.
- **Companion reference:** `OrdeloAgent/docs/ordelo-restaurant-frontend-agents.md` (endpoint ids such as `create` and `authorized` below refer to it)
- **Audience:** a coding agent or engineer implementing this in phases. Every recommendation lists its rationale, alternatives, affected code and dependencies.

Labels used throughout:

- **[V]** verified in code at the snapshot above.
- **[A]** assumption: not verifiable from the connected repos.
- **[D]** decision already made with the owner (see §0).
- **[B]** blocking decision or open question (see §21).

---

## Resume here (state at 2026-10-01, after go-live)

Read this first, then §0 (D22–D34), §18 and §22. Background reading: `CONTEXT.md` ("Web ordering"), `docs/adr/0003`–`0005`, `plans/ordelo_agg_plan_cc_decision_log.md` (entries 27–36).

### Done

| Area | What was done | Where |
|---|---|---|
| Decisions | Payment service unchanged for web (D22); no webhook signature check, as today (D23); web orders collect no name/phone (D24); manual capture only (D25); post-payment redirect gap deferred (D26); web orders never reach restaurant apps (D27); `storefront` column now (D28); R2 creates a real web-style order (D29); R1 split into R1a/R1b (D30); R1 SQL run manually (D31); test payments via `?isTest3100=true` (D32) | §0, decision log 27–36 |
| Docs | Glossary, three ADRs, plan sections §9.3, §13.1, §18 rewritten | `CONTEXT.md`, `docs/adr/0003–0005` |
| SQL (run by owner on the shared Supabase `pqsvhidiwiydgshynfib`) | `ordelo_datamodels/migrations/ordelo_agg_r1.sql` (food_order `origin_channel`/`storefront`/`idempotency_key`, `payment_event`, RPCs `create_food_order_with_items` and `record_payment_authorised`, `job_payment_init_reconciler()`, R1b tables) and `ordelo_agg_r1_test_payment.sql` (`food_order.payment_mode`, RPC updated) | both run 2026-10-01 |
| `ordelo_config` | `PAYMENT_INBOX_ENABLED=true`, `ORDER_CREATE_RPC_ENABLED=true`, `ENABLE_PAYMENT_TEST_ROUTES=false`, `TEST_PAYMENT_REST_REFS=BNAT`, `PAYMENT_INIT_RECONCILER_SINCE` set. `ORDELO_APP_URL` points back at production Ordelo (go-live, 2026-10-01) | shared DB |
| OrdeloAgent code (R1a + D32) | `config/feature_flags.py`; `utils_common/order_management/order_reference.py`, `customer_keys.py`, `order_service.py`, `food_order_pymodel.py` (`payment_mode`, `uses_test_payment`); `utils_common/payment_ms/payment_events.py`, `payment_mode.py`; `watomation/routers/order_hooks.py` (new fields, F3 fix, W-id skip, test payments), `payment_hooks.py` (once-only payment-complete, gated test route, `/init-reconciler`); tests | branch `release/ordelo-agg` |
| restaurant-frontend code | R0 web prototype (fixtures); D32: `lib/testPayment.ts`, `BasketDrawer`, `/api/checkout`, order summary label, `/api/web/orders`, fixtures, `CheckoutFlow`, `OrdeloMenuContainer`. `.env.local` set to `NEXT_PUBLIC_WEB_ORDERING_MODE=off`; production is off by default because `amplify.yml` doesn't copy that variable | branch `dev` |
| Go-live (owner, 2026-10-01) | Both repos committed and deployed; Amplify production has web ordering off; `ORDELO_APP_URL` back on production. One real paid WhatsApp order went through the new `payment-complete`. | production |

### Verified

- **Unit tests:** OrdeloAgent 431 passed (one failure pre-dates this work: `test_restaurant_master_get_admins_fetches_live_column`); restaurant-frontend `tsc` and lint clean.
- **SQL:** both files run twice cleanly on a scratch Postgres 16; RPC outcomes, rollback and constraints checked.
- **R1a against the owner's server (15/15):** web-style create-order on both insert paths; once-only `payment-complete` outcomes (applied, duplicate, rejected_state, unknown_order, ignored, invalid); test route gated; legacy path with the flag off; reconciler job end to end (Supabase → `/payment-hooks/init-reconciler` → overwatch WhatsApp). Server logs confirmed web orders skip the restaurant app. All test data cleaned up.
- **Real WhatsApp orders** (`SFCS-JDQS-25`, `ELAS-RMLT-26/27`) were created through the new one-transaction RPC with the flags on.
- **D32 test payments:** curl — BNAT honoured (`payment_mode='test'`, Stripe `cs_test_` session), SFCS refused (live). WhatsApp page — `ELAS-RMLT-27` from a non-overwatch number: the front end passed the flag and Ordelo refused it. Web page (fixtures) — BNAT gives `payment_mode: test`, ELAS gives `live`.

### Verified after go-live (owner, 2026-10-01)

All three former "Not verified yet" items are done:

1. A WhatsApp order **paid for real** through the new `payment-complete` (event applied, restaurant app notified, summary row, capture in Stripe).
2. Overwatch + takeaway + `&isTest3100=true` (label, Stripe test page, capture through the test service).
3. Full WhatsApp takeaway and pay-at-restaurant runs with the flags on.

### Next steps, in order

1. **R1b: customer notifier** (§18 R1b, §22). *Why now:* today only `payment-complete` and `capture-address` skip web orders. The other restaurant-app hooks (§2.2: `order_hooks`, `takeaway_hooks`, `location_hooks`, `delivery_hooks` ×2, `agent_app_handlers` ×2, `on_callback_wa_handler`, …) would still post a web order's W-id to a restaurant app. R1b puts all of them behind one module so web and WhatsApp can be routed differently. For WhatsApp orders nothing visible changes. Steps:
   1. **Characterisation tests first.** For each of the 10 hooks, record the exact URL and JSON body sent today (mock the HTTP client). These tests must pass unchanged at the end.
   2. **M3 notifier** `utils_common/notify/customer_notifier.py`: `publish(order_number, event)` writes `order_customer_event` (idempotent), resolves subscriptions, writes the outbox and dispatches. **Adapter A** = restaurant app (same URL and payload as today, retries = 0). **Adapter B** = web page (no-op until R3). Fallback: a WhatsApp order with no subscription goes to its restaurant app.
   3. **Swap the 10 call sites** to `publish(...)` behind `CUSTOMER_NOTIFIER_ENABLED`. Flag off = the legacy direct call, kept for one release.
   4. **Subscriptions:** `create_order_with_items` creates `whatsapp_restaurant` (WhatsApp) or `web_page` (web). M2's web branch publishes `payment_authorised`.
   5. **SQL:** none new. Section 003 of `ordelo_agg_r1.sql` (subscriptions, customer events, outbox) was run on 2026-10-01.
   6. **Roll-out:** deploy with the flag off, turn it on with `BNAT` first, place a WhatsApp delivery and a takeaway order, compare customer messages, then enable for all. Rollback = flag off.
2. **R2: payment-path check** (§18 R2). *No code and nothing to deploy;* it is a scripted test run that proves a web-style order can be paid, captured and cancelled through the unchanged payment service before any web page is wired to it. Do it after R1b so the web-style test order reaches no restaurant app at any stage. On `BNAT` (Stripe test mode):
   1. Create a web-style order: `SELECT create_thread('WEB', NULL)`; `POST /order-hooks/capture-address` with a W-id; `POST /order-hooks/create-order/BNAT` with that W-id, the `WEB-…` thread, `"origin_channel":"web"`, `"storefront":"ordelo"`. Expect a Stripe Checkout URL.
   2. Pay it with a Stripe test card. Check the payment service saved the PaymentIntent (`payment_details`) and Ordelo logged `payment event … : applied` on the web branch (no restaurant-app call). Replay the event: `duplicate`, no side effects.
   3. Note, from the Stripe dashboard, the Ordelo webhook URL and subscribed events for each Stripe account in use (§21, assumption 1).
   4. Let a rider accept: capture succeeds. On a second order, let dispatch time out: cancel succeeds.
   5. Record where Stripe sends the browser after paying (expected: the restaurant's fixed URL, D26).
   6. Write the five results into the release notes and clean up the test rows.
3. **R3 entry gate (D34):** items 1–5 under §18 R3 "Entry gate" were **fixed on 2026-10-01** (restaurant-frontend `dev`, uncommitted). Still open before R3 goes live: Lighthouse mobile accessibility (item 6), and answers to Q14, Q16, Q17. None of these blocks R1b or R2.
4. **Deferred by the owner (D33):** scheduling the init reconciler. The job and endpoint exist; when wanted, run `SELECT cron.schedule('job_payment_init_reconciler', '*/2 * * * *', $$SELECT job_payment_init_reconciler()$$);`.
5. **Separate track:** payment-service F11–F13 (§3).

---

## 0. Decision log (agreed with owner, 2026-09-29)

| # | Decision | Consequence |
|---|---|---|
| D1 | The plan lives in `OrdeloAgent/plans/`. | — |
| D2 | We own the payment microservice and can change its contract. | **Consequence superseded by D22 (2026-10-01):** we own it, but web ordering makes no change to it. |
| D3 | Web customers opt into WhatsApp updates on a **new Ordelo-branded customer WABA number**. | This is separate from the Ordelo rider/admin number and from the per-restaurant numbers. |
| D4 | `ordelo-agg-agent` is a **new app in restaurant-agents** (e.g. `apps/ordelo_agg`). | It reuses Thread, GraphAdapter and WABA-namespace isolation. Ordelo stays the order authority. |
| D5 | **No OTP.** Stripe Checkout is the only gate. | — |
| D6 | Order access uses a **secret link + HttpOnly cookie**, with **order number + phone** as a status-only fallback. | §16. **Fallback affected by D24:** no phone is collected, so the order-number + phone lookup has nothing to check (Q14). |
| D7 | A **postcode gate on landing** (with a "collecting instead?" path to the town). | §8 |
| D8 | **Prices, discounts, collection thresholds and vouchers stay exactly as today** (client-computed, `config/restaurants.ts`). `*_menu` prices are authoritative, but moving pricing to the server is **later** (R5). | Accepted risk, recorded in §3 and §11. |
| D9 | Web checkout creates a **real `thread` row** (namespaced, recipient NULL) and links it to a later WhatsApp thread rather than re-keying it. | §4 |
| D10 | The web customer key is a **synthetic `cust_id` = `W` + 11 base32 chars**. `capture-address` upserts `customer_master` with it (as today). **No phone field in the web form.** | §4 |
| D11 | ~~Stripe Checkout collects name and phone (required). The payment service forwards them and Ordelo stores them on the order before `init_delivery`/`init_takeaway`.~~ **Superseded by D24 (2026-10-01).** | — |
| D12 | **Order references must not depend on a phone number.** Phone-derived when a 12-digit phone is available, random otherwise. | Ordelo change (R1) |
| D13 | Web collection follows the **same restaurant confirmation flow** as WhatsApp. The order page shows the pickup time once it is set or updated. | No forced auto-accept. |
| D14 | **No customer self-cancel.** The order page directs the customer to call the restaurant. | Self-cancel is later. |
| D15 | Schema: `food_order.origin_channel`, `order_notification_subscription` and `order_customer_event`, behind **one customer-notifier module in Ordelo**. | §6 |
| D16 | A WhatsApp sender whose number doesn't match the Stripe-collected phone is allowed, with **status-only** detail. | §14. **Affected by D24:** there is no collected phone to compare against (Q15). |
| D17 | **Web collection is online-payment only.** Pay-at-restaurant stays WhatsApp-only. | — |
| D18 | Towns and restaurant slugs live in **frontend config for now**. | A DB storefront is later. |
| D19 | Releases R0–R5 as in §18. | — |
| D20 | (2026-09-30) **The Ordelo aggregator is one storefront with two entry channels: web and WhatsApp (`ordelo-agg-agent`). Both channels get the same page elements and offers.** So `ordelo-agg-agent` will also send customers to the Ordelo menu page to order, not only track orders. | §8.1; R4 scope note |
| D21 | (2026-09-30) The **restaurant-specific UI is deferred**: it may converge onto the Ordelo page design or stay different. The existing `/restaurant/[id]` WhatsApp page is **left untouched** until that decision. | §8.1, R5 |
| D22 | (2026-10-01) **The payment-service contract is unchanged for web.** Web orders call the existing create, capture and cancel endpoints with today's payloads (`thread_id=WEB-…`, a known `restRef`). Web-specific payment behaviour lives in Ordelo, in `payment_hooks.payment_complete_path`, which branches on `origin_channel`. | §9.3, §13, R2; ADR-0004 |
| D23 | (2026-10-01) **No webhook signature verification, as today.** Neither Ordelo nor the payment service has a Stripe webhook signing secret configured [V]. `payment-complete` keeps accepting unsigned events. Replays become harmless through M2's conditional update and event log; forgery stays an accepted risk (F1). | §13; ADR-0004 |
| D24 | (2026-10-01) **Web orders collect no name and no phone** (replaces D11). `capture-address` stores the W-id as `cust_name`, exactly as it stores the WhatsApp number today. Riders get no customer number for web deliveries. | §2.2, §6, R3; ADR-0005 |
| D25 | (2026-10-01) **Web payments use manual capture only.** Delivery is captured when a rider accepts the job (existing behaviour); collection at the pickup-time boundary (ADR-0002). Web never uses the automatic-capture path, which prints a kitchen ticket inside the payment service at authorisation. | §13 |
| D26 | (2026-10-01) **The post-payment redirect is deferred.** Stripe sends a web customer to the restaurant's fixed success/cancel URL in the payment service (a wa.me link for elas and sfcs). Documented as a known gap; fixed in a later release. | §13.1, R5 |
| D27 | (2026-10-01) **Web orders never reach restaurant-agents apps** (rule kept after review). `payment-complete` and the other restaurant-app hooks skip web orders; customer events go through the Ordelo customer notifier. | §2.2, §5; ADR-0003 |
| D28 | (2026-10-01) **Q11 answered: add `food_order.storefront` now**, in the R1a migration (default `direct`, immutable like `origin_channel`). | §6.1 |
| D29 | (2026-10-01) **R2 creates a real web-style order.** The existing `create-order` accepts optional `origin_channel` (default `whatsapp`) and `storefront` (default `direct`) in R1a, and `capture-address` skips the restaurant-app hook for a W-id from R1a (moved from R3). | R1a, R2 |
| D30 | (2026-10-01) **R1 is split.** **R1a** = payment and order foundation (everything R2 needs). **R1b** = the customer notifier (needed by R3, not R2). The late-payment guard (Q17) stays out of R1 and belongs to R3. | §18 |
| D32 | (2026-10-01) **Test payments on request: `?isTest3100=true`.** Both checkouts (WhatsApp `/restaurant/[id]` and the Ordelo web page) pass `test_payment: true` to `create-order`. **Ordelo decides:** it honours the request only for an overwatch recipient (WhatsApp; web orders have no phone, D24) or a restaurant listed in `ordelo_config.TEST_PAYMENT_REST_REFS` (web, option 1). Otherwise the order is live and the request is logged. The choice is stored once on `food_order.payment_mode` (`live`/`test`), so create, capture and cancel all use the same payment service. Today's rule (overwatch + delivery → test) is unchanged. Owner overrode the R0 guardrail of not touching `BasketDrawer` for this. | §13, R1a addendum |
| D31 | (2026-10-01) **All R1 SQL ships as one file**, `ordelo_datamodels/migrations/ordelo_agg_r1.sql`, which the owner runs manually. Code that depends on it is behind `ordelo_config` flags that are off when the key is missing, so deploying code before the SQL is safe. | §6.1, §18 |
| D33 | (2026-10-01) **Scheduling the init reconciler is deferred** (owner: not wanted yet). The SQL job and `/payment-hooks/init-reconciler` stay deployed but unscheduled. | §18 R1a, §22 |
| D34 | (2026-10-01) **The R0 front-end findings are deferred to an R3 entry gate.** All four findings and the stale copy sit in the Ordelo web code only (`components/ordelo/*`, `lib/web/*`, the fixture pay page), which is off in production; none touches the WhatsApp flow (`/restaurant/[id]`, `MenuContainer`, `BasketDrawer`, `CartContext`). They don't block R1b or R2, but must be fixed before web ordering goes live. | §18 R3 "Entry gate", `plans/ordelo-r0-validation-2026-09-30.md` |

---

## 1. Scope and system roles (corrected picture)

The brief says OrdeloAgent "contains the customer facing whatsapp solution". The code says otherwise [V]:

| System | Role today | Evidence |
|---|---|---|
| **restaurant-agents** (apps `elas`, `sfcs`, `bnat`) | The **customer WhatsApp agent**: one app, one WABA number and one LangGraph per restaurant. It owns `Thread` and `AgentState`, sends menu links carrying `recipient` and `thread_id`, receives order and rider events and messages the customer. | `docs/domain/platform-domain-model.md`; `services/wa_templates/rest_menu_query_params.py:RestMenuQueryParams`; `watomation/routers/order_event_hooks.py:payment_complete` |
| **OrdeloAgent** | Order, pricing, payment and fulfilment**orchestrator**. It also runs the **rider** LangGraph agent and the **restaurant-admin/ops** WhatsApp interactions on its own number. | `watomation/routers/*`; `ordelo/agents/rider_agent.py` |
| **restaurant-frontend** | Next.js 14 menu, basket and order summary for WhatsApp deep links, plus the rest-admin, rider and sys-admin portals. | `app/restaurant/[id]/page.tsx`, `components/BasketDrawer.tsx` |
| **Payment service** | Stripe wrapper (Go, AWS Lambda): creates Checkout Sessions, captures (with restaurant payout transfer) and cancels; its own Stripe webhook stores the order → PaymentIntent mapping or prints the kitchen ticket. **Read at `58158ca` (2026-10-01) [V]. Unchanged for web (D22).** | `payment-service/internal/transport/http/handler.go`, `internal/stripe/payment.go`, `internal/stripe/webhook.go`, `internal/config/config.go`; called by `utils_common/payment_ms/payment.py`, `delivery_hooks.py:capture_delivery_payment/cancel_payment` |
| **Menu service** | `MENU_API_URL` (restaurant.byteloop.ai), backed by `{rest}_menu` tables [A]. **Not in any connected repo.** | `restaurant-frontend/app/api/menu/route.ts` |
| **Pricing service** | Delivery options, fees and minimum order. **Not in any connected repo** [A]. | `order_service.py:_call_pricing_service` |

**What is being built:** an Ordelo-branded, multi-restaurant storefront (town → restaurant → menu → checkout → order page). Ordelo is the source of truth for orders. Later, a new WhatsApp app (`ordelo_agg`) lets web customers follow orders on WhatsApp, and then becomes a second entry channel into the **same** Ordelo page (D20). The restaurant-specific UI is a separate, deferred decision (D21).

---

## 2. Verified current behaviour (trace)

### 2.1 End-to-end WhatsApp-originated order [V]

1. **Conversation.** restaurant-agents `get_or_create_thread(agent=REST_REF, recipient)` creates `thread_id = '{REST_REF}-{uuid}'` (`thread_mgmnt.sql:create_thread`, `v_thread_id := p_agent || '-' || gen_random_uuid()`).
2. **Address.** The customer shares an address. `POST /order-hooks/capture-address` (`order_hooks.py:capture_address`) upserts `customer_master{cust_id=recipient, cust_name=recipient, address, lat, lon}`, upserts `cust_rest_map{has_consent=false}`, and POSTs `order-address-update` to the restaurant app.
3. **Menu link.** The agent sends `/restaurant/{id}?distance&minimum_order&order_type&thread_id&recipient` (`RestMenuQueryParams`, recipient pattern `^\d{12}$`).
4. **Session check.** The frontend page and basket call `/api/verify-session` → Ordelo `get-active-thread` → restaurant app `thread-hooks/get-active-thread`, and compare `thread_id` (`page.tsx:validateSession`, `BasketDrawer.tsx:handleCheckout`). This is **browser-side only**. `/api/checkout` checks only that the fields are present.
5. **Basket.** `BasketDrawer` applies `discountPercentage` to each item and sends **discounted item prices**. Minimum spend is checked client-side against the **discounted subtotal** (`basketTotal = discountedSubtotal`).
6. **Create order.** `POST /order-hooks/create-order/{rest_ref}` → `order_service.create_order_with_items`:
   - `order_reference = create_order_reference(recipient)`: SHA-256 of the **last 4 phone digits** + salt + date → 4 letters. It raises if the recipient doesn't end in 4 digits.
   - `seq = get_next_daily_seq()` (global daily sequence starting at 20).
   - `order_id = REF-seq`, `order_number = RESTREF-REF-seq`.
   - Inserts `food_order` (`thread_id NOT NULL`, `recipient NOT NULL`, `payment_status='requires_payment'`) and then `order_item`. Failure handling is **compensating delete, not a transaction**.
   - Then `FoodOrder.from_order_id` → `update_final_order_value_in_db` reads **`customer_master.lat/lon` by `cust_id = recipient`** and calls pricing → writes the fees and `final_order_value`.
   - Then `generate_payment_intent_url` → `POST {stripe_url}/threads/{thread_id}/orders/{order_id}/payment-url`.
7. **Pay.** The browser redirects to the Stripe URL. The success and cancel URLs are **fixed per restaurant inside the payment service** [V] (`internal/config/config.go:ensureRestaurantDefaults`: wa.me links for elas and sfcs, the menu page for bnat; used at `internal/stripe/payment.go` L122–123). The frontend also has per-restaurant `PAYMENT_COMPLETE` wa.me links (`config/whatsapp.ts`).
8. **Payment webhook.** Stripe → `POST /payment-hooks/payment-complete` (`payment_hooks.py:payment_complete_path`). The payment service's own webhook (`internal/stripe/webhook.go:HandleWebhook`) only saves the PaymentIntent or prints, and **never calls Ordelo** [V], so this is a Stripe webhook endpoint registered directly on Ordelo [A: confirm in the Stripe dashboard for each Stripe account in use]. Neither side verifies Stripe's signature [V]. The handler reads `data.object.metadata.orderID` and **unconditionally** sets `payment_status='requires_capture'`. It then queues `handle_payment_complete` (POST to the restaurant app `payment-complete/{recipient}/{thread_id}`) and `init_delivery_summary` or `init_takeaway_summary`.
9. **Fulfilment init.** `init_delivery(p_cust_id, p_order_number)` **snapshots the customer name and address from `customer_master`** into `delivery_summary` and generates the restaurant and customer confirmation codes. `resolve_initial_restaurant_acceptance` applies configured auto-accept (ADR-0001).
10. **Restaurant confirmation.** DB triggers → `/delivery-hooks/restaurant-confirmation-request` or `/takeaway-hooks/restaurant-confirmation-request` → admin WhatsApp Accept plus pickup-time buttons. The **Decline button is commented out** in `send_restaurant_order_confirmation` (`utils_common/waba_utils/wa_senders.py` ~L673), which both delivery (`delivery_hooks.py` ~L1266) and takeaway (`takeaway_hooks.py` ~L159) use. A timeout becomes auto-accept (`delivery_hooks.py:_handle_restaurant_timedout`, `takeaway_hooks.py:_handle_restaurant_timedout`).
11. **Delivery.** `process_delivery` → `delivery_dispatch` → rider offers. Assignment → `delivery_inflight` → `delivery_inflight_graph_init_hook` → capture (`capture_delivery_payment`), `post_rider_event_inflight` to the restaurant app, and the rider graph.
12. **Takeaway.** The first non-null `pickup_time` → `pickup_time_updated_hook` → `capture_takeaway_payment` (ADR-0002) and `order-pickup-time-updated` to the restaurant app.
13. **Customer updates** all go through the restaurant app, keyed by `recipient`/`customer_id`:
    - rider-inflight
    - on-restaurant-cc (food collected)
    - on-customer-enter (rider near + **customer code**)
    - on-customer-cc (delivered)
    - delivery-timedout (no rider; `payment_cancelled`)
    - takeaway-pickup-time-updated
    - takeaway-ready
14. **Thread lifecycle.** `retain_thread` blocks new service selection while an order is in flight (the "duplicate ordering" protection). Stale-thread jobs terminate idle threads.

### 2.2 Dependency inventory: `thread_id`, phone, and WhatsApp session [V]

| Dependency | Where | Impact on web |
|---|---|---|
| `food_order.thread_id TEXT NOT NULL` | `utils_common/order_management/food_order.sql` | Needs a value → the web thread (D9). |
| Payment URL path `/threads/{thread_id}/orders/{order_id}/payment-url` (create, capture, cancel) | `food_order_pymodel.py:FoodOrder.payment_uri`, `delivery_hooks.py:cancel_payment` | Opaque correlation key; `WEB-<uuid>` works unchanged. |
| `food_order.recipient NOT NULL`; `customer_master.cust_id VARCHAR(12) PK` | `food_order.sql`, `ordelo_datamodels/masterdata.sql` | W-id (12 chars) fits (D10). |
| Order reference from the last 4 phone digits | `order_db_ops_new.py:create_order_reference` | Raises for a W-id → D12 change. It also **leaks the last 4 digits** (`order_num_gen.py:decode_order_number` brute-forces them). |
| Pricing reads `customer_master` by recipient | `food_order_pymodel.py:update_final_order_value_in_db` | Works with the W-id row. |
| `init_delivery`/`init_takeaway` read `customer_master` by `p_cust_id`; `customer_name` comes from `cm.cust_name` (which `capture-address` sets to the recipient) | `jobs_n_functions/init_delivery.sql`, `init_takeaway.sql` | Works unchanged: for web, `cust_name` is the W-id, just as it is the WhatsApp number today (D24). |
| Rider gets the customer contact card with `phone = delivery_summary.customer_id` | `ordelo/agents/rider_agent.py:send_customer_contact` ~L560–610 | **Breaks for a W-id.** Web orders carry no phone (D24), so the tool must tell the rider no number is on file instead of sending the W-id (Q16). |
| Restaurant admin delivery receipt shows `customer_id` next to the address | `utils_common/waba_utils/wa_senders.py` ~L233 | Shows the W-id for web orders. Acceptable: it is not a number to call. |
| Ordelo messages the customer directly on takeaway decline | `takeaway_hooks.py:_handle_restaurant_decline` (`send_message(to=customer_id)`) | W-id is not a phone → must go through the notifier. |
| 10 outbound restaurant-app hooks keyed by recipient/customer_id | `payment_hooks.py:51`, `order_hooks.py:379`, `takeaway_hooks.py:408`, `location_hooks.py:290`, `delivery_hooks.py:353,380`, `agent_app_handlers.py:514,541`, `on_callback_wa_handler.py:532`, `customer_hooks.py:126` | For web orders they would hit a restaurant app with a W-id. **These are the seam** for the customer notifier (§5). |
| restaurant app `payment-complete` validates path/body recipient and thread, then runs the graph **by recipient** | `restaurant-agents .../order_event_hooks.py:payment_complete` | Must never receive web orders. |
| Browser session validation (`verify-session` → `get-active-thread`) | `page.tsx`, `BasketDrawer.tsx` | Not used on web routes; WhatsApp routes unchanged. |
| `job_close_thread` selects **all** active threads with no `agent` filter and posts `recipient` for a goodbye WhatsApp | `jobs_n_functions/job_close_thread.sql` | A web thread (recipient NULL) must be excluded (§6). Whether this job is still scheduled is unknown [A]. |
| The restaurant stale-thread job joins `restaurant_master` on the thread_id prefix | `OrdeloAgent/ordelo_datamodels/jobs_n_functions/job_terminate_stale_active_threads.sql` | A `WEB-` prefix doesn't join → already excluded [V]. |
| Admin views list delivery/takeaway orders | `migrations/admin_orders_views.sql` | Web orders appear automatically; add `origin_channel` to the views. |
| Overwatch test payment URL is chosen by `recipient in overwatch_list` | `FoodOrder.payment_uri` | W-ids never match → web test orders need a different switch (§18, R3). |
| Payment-service Checkout success/cancel URLs are fixed per restaurant | payment-service `internal/config/config.go` L166–219; `internal/stripe/payment.go` L122–123 | A web customer lands on the restaurant's wa.me link after paying (D26, §13.1). |
| Payment-service `GetRestaurant` falls back to `elas` for an unknown `restRef` | payment-service `internal/config/config.go:GetRestaurant` L51–65 | A web order for an unknown restaurant would be charged on Elas's account and paid out to it. M6 must reject such a `rest_ref` before calling the payment service (F13). |
| Automatic-capture sessions print the kitchen ticket inside the payment service at authorisation | payment-service `internal/stripe/webhook.go` L92–154 | Web uses manual capture only (D25). |

---

## 3. Verified defects and risks that matter for a public channel

| # | Finding [V] | Severity for web | Fix phase |
|---|---|---|---|
| F1 | `payment-complete` has no signature check, no idempotency and an unconditional status update. Replays re-notify and re-init. `payment-complete-test/{order_id}` is unauthenticated and marks any order paid. | **Critical** | R1: idempotency, conditional update and the test-route gate. **Signature: accepted risk, not fixed (D23).** A forged event for an unpaid order would start fulfilment; capture then fails at rider acceptance or pickup time and alerts (M-4). |
| F2 | Item prices, discounts and vouchers are client-supplied; voucher codes ship in the JS bundle. Ordelo sums the submitted prices with no `*_menu` lookup. | High (public abuse) | **Accepted for now (D8)**. R5. Monitoring in R3. |
| F3 | `create_order` calls `FoodOrder.from_order_id(order_result["order_id"])` **before** checking `success`, so a failure raises `KeyError` → 500. | Medium | R1 |
| F4 | `food_order` + `order_item` insert is not transactional; compensation is a delete. | Medium | R1 (RPC wrapping both inserts) |
| F5 | Ordelo `/order-hooks/*`, `/payment-hooks/*`, `/delivery-hooks/*` and the debug routes are unauthenticated; the frontend proxy routes are outside `middleware.ts` matcher. | High once the web is public | R3: new `/web/*` routes require a server-to-server secret. The legacy ones are listed in §21. |
| F6 | Money is stored as `FLOAT`. | Low (display rounding) | Later |
| F7 | Payment outcomes after capture or cancel are not written back (`payment_status` stays `requires_capture`); ADR-0002 forbids new `payment_status` values. | Medium (the order page can't say "refund released") | R1: `payment_event` log (§6) |
| F8 | Delivery `restaurant_decline` handler sets `delivery_summary.status='unassigned'`, which makes `process_delivery` dispatch riders. The decline button is currently commented out. | Latent | Document; don't enable decline for web without fixing it. |
| F9 | `middleware.ts` and `/api/menu` log all query params (including `recipient`) to Amplify logs. | Medium (PII in logs) | R3 (redact) |
| F10 | `/location-hooks/live-location-map/{order_number}` reveals the rider location to anyone with the order number. | Medium | R3: web page never exposes it directly; proxy it behind the access token. |
| F11 | Payment-service webhook (`webhook.go:HandleWebhook`) doesn't verify Stripe's signature. A forged automatic-capture event prints a kitchen ticket; a forged manual one writes a `payment_details` row. | Not web-specific (server-to-server URL) | Separate payment-service track; not a web blocker. |
| F12 | The payment service never checks the `X-Authorization` token Ordelo sends (`main.go` puts it in the context for outbound print calls only) [V]. Unless API Gateway enforces it [A], anyone with the URL can capture with any amount or cancel any order by number. | Not web-specific | Separate payment-service track; check API Gateway first. |
| F13 | Payment-service `GetRestaurant` falls back to `elas` for an unknown `restRef`. | High for web if a new restaurant is listed before the payment service knows it | R3: M6 rejects any `rest_ref` outside the payment service's known set. |

---

## 4. Identifiers: responsibilities and lifecycle

| Identifier | Represents | Created | Before payment? | Stored in | Notes |
|---|---|---|---|---|---|
| **Visitor id** | An anonymous browser, for analytics only | First page view (first-party cookie `ov`, 13 months, random) | Yes | `web_session_meta.visitor_id` | Never used for authorisation. No PII. |
| **Web thread** (`thread_id='WEB-<uuid>'`, `agent='WEB'`, `recipient=NULL`) | **Checkout session / payment correlation.** Not a conversation. | "Checkout" pressed with a non-empty basket, via the existing `create_thread('WEB', NULL)` | Yes | `thread`, `web_session_meta` | One per checkout attempt; reused on retries of the same basket. Doubles as your "sessions" metric. |
| **Web customer key** (`cust_id='W'+11 base32`) | Guest customer record **for one checkout** | With the web thread | Yes | `customer_master` (via `capture-address`), `food_order.recipient` | One per web thread, so the `customer_master` row is effectively an **address snapshot for that order**. This avoids the concurrent-order address race (§2.2) without changing SQL. |
| **Order** (`order_id`, `order_number`) | The commercial order (FoodOrder aggregate) | `create-order` | Yes (`requires_payment`) | `food_order`, `order_item` | Reference per D12. `order_number` is **not** a credential. |
| **Payment attempt** | A Stripe Checkout Session / PaymentIntent for an order | `create-order` → payment service | Yes | Payment service `payment_details` (order → PaymentIntent, written by its own Stripe webhook); `payment_event` rows in Ordelo | One Checkout Session per successful create call. The payment service has no idempotency key (D22), so a retried call can create a second session; the orphan expires unused after Stripe's default 24 h. A new basket means a new order. |
| **Contact** | **Not collected for web (D24).** WhatsApp orders keep using the WhatsApp number. | — | — | — | Riders get no number for web deliveries (Q16). |
| **Order access grant** | Bearer right to view one order in full | `create-order` (web) | Yes | `order_access_grant` (hash only) + HttpOnly cookie | §16 |
| **WhatsApp hand-off code** | One-time right to bind a WhatsApp sender to an order | On request from the order page (R4) | No | `order_access_grant` (kind=`wa_handoff`) | §14 |
| **WhatsApp conversation thread** (`ORDELO_AGG-<uuid>`, recipient = phone) | A real conversation on the Ordelo customer number | First inbound message to `ordelo_agg` | No | `thread` | Linked, not re-keyed (D9). |
| **Notification subscription** | "Send events for order X to destination Y via channel Z at detail level L" | WhatsApp origin: at `create-order`. Web: `web_page` at `create-order`; `whatsapp_agg` on bind. | Varies | `order_notification_subscription` | Decouples **origin** from **communication preference** (D15). |

**Is the current thread a conversation or a checkout container?** [V] It is both. It is a conversation (AgentState, checkpoints, stale-thread closure), and it is also the checkout container: `food_order.thread_id`, the payment URL path, and the restaurant-app `payment-complete/{recipient}/{thread_id}` identity check. The web design **keeps the column** but gives it one meaning per namespace. For `WEB-*` it is the checkout/payment correlation; for `{REST_REF}-*` both meanings stay, unchanged.

**Compatibility and eventual migration** (R5, optional): add `food_order.checkout_ref`, backfill it from `thread_id`, move the payment path to `/orders/{order_id}` with `thread_id` optional, then make `food_order.thread_id` nullable. Not needed for launch.

**Phone as primary key:** the web path no longer requires a phone as `cust_id`. A real phone-keyed `customer_master` row is created or linked **only** through a WhatsApp bind (R4; the rule is pending Q15, since there is no collected phone to match). `web_customer_link(w_cust_id, cust_id, linked_at, via)` records it (R4). A future account system can introduce a surrogate `customer_uuid`; nothing here blocks that.

---

## 5. Target architecture: ownership and modules

### 5.1 Source of truth

- **Ordelo owns order state and every valid transition.** It covers FoodOrder, payment projection, restaurant acceptance, fulfilment summaries, dispatch, customer events and notification subscriptions. That rule already appears in the restaurant-agents domain model ("FoodOrder is authoritative; external payment and fulfilment are authoritative over their state") and stays true.
- **Web UI, WhatsApp agents and portals are readers and command-issuers.**
  - Reads go through one **customer order view** (§5.2 M5). The rest-admin portal keeps its direct Supabase views.
  - Commands go through Ordelo endpoints.
  - The browser never writes order state.
- **Core processing never depends on a conversation.** Payment webhook → init → confirmation → dispatch → capture → completion runs from Ordelo endpoints, SQL triggers and pg_cron alone. The notifier is **fire-and-record** through an outbox. If `ordelo_agg` or a restaurant app is down, events queue and the order still completes.

### 5.2 Deep modules (small interfaces, behaviour behind them)

Vocabulary follows the codebase-design skill: *module*, *interface*, *seam*, *adapter*.

| Module (new, in OrdeloAgent) | Interface (what callers learn) | Hidden behaviour | Seam / adapters |
|---|---|---|---|
| **M1 `order_reference`** | `new_order_reference(recipient: str, order_dt) -> str` | Phone-derived for a 12-digit recipient (unchanged WhatsApp behaviour), random 4 letters from a 23-letter unambiguous alphabet otherwise. Retries on `order_id` unique violation (max 3). | None (pure function). Replaces the call in `order_service.create_order_with_items`. |
| **M2 `payment_events` (inbox)** | `async record_payment_authorised(evt: PaymentAuthorisedEvent) -> Outcome{applied, duplicate, rejected}` | One SQL RPC (`record_payment_authorised`) inserts the `payment_event` with a unique `provider_event_id` and runs the conditional `UPDATE food_order ... WHERE payment_status='requires_payment' RETURNING *` in the same transaction; ignores Stripe event types other than `checkout.session.completed`; **branch on `origin_channel`**: WhatsApp → restaurant app as today, web → no restaurant-app call (D27; notifier publish from R1b); queues init exactly once. Late-payment guard (Q17) is added in R3. **No signature check (D23).** | Adapter 1: Stripe's `checkout.session.completed`, received as today. Adapter 2: `/paid3100` and test replays (unchanged). |
| **M3 `customer_notifier`** | `async publish(order_number: str, event: CustomerOrderEvent) -> None` | Append `order_customer_event` (idempotent on `(order_number, event_key)`), resolve active subscriptions, write the `notification_outbox`, dispatch, record the outcome, retry with a sweep. Detail-level redaction. | **Adapter A** `RestaurantAppWebhook`: reproduces today's 10 calls byte-for-byte for `whatsapp_restaurant` subscriptions. **Adapter B** `WebPage`: no-op; the page reads events. **Adapter C** `OrdeloAggWhatsApp` (R4). Two adapters at R1 make it a real seam. |
| **M4 `order_access`** | `issue(order_number, kind) -> RawToken`; `verify(raw, order_number?) -> Grant{order_number, detail_level}`; `consume_handoff(code, sender_phone) -> Binding` | SHA-256 hashing, expiry, single use, rate limits, attempt logging. | None. |
| **M5 `customer_order_view`** | `async get_view(order_number, detail_level) -> CustomerOrderView` | Joins `food_order`, `order_item`, `delivery_summary`/`takeaway_summary`, `delivery_dispatch`/`delivery_inflight`, `payment_event` and `order_customer_event`; derives the display status (§7.3); redacts by detail level. | Used by the web order page, the lookup fallback and `ordelo_agg` (on bind, and on customer questions). |
| **M6 `web_checkout`** | `start(rest_ref, mode, meta) -> CheckoutSession{thread_id, cust_id}`; `create_order(session, items, notes, idempotency_key) -> OrderQuote` | Web-thread creation (existing `create_thread('WEB', NULL)`), W-id minting, `web_session_meta`, availability checks (§12), eligibility check (§11), idempotent order creation (reusing `create_order_with_items`), payment URL through the **existing** contract with manual capture only (D22, D25), rejection of a `rest_ref` the payment service doesn't know (F13), access-grant issue, `web_page` subscription. | None. |

**Deletion test.**

- Deleting M3 would put 10 call sites back, each branching on channel. That is exactly today's coupling, multiplied by the number of channels.
- Deleting M5 would make the web page, lookup and agent each re-join five tables and re-derive status.

Both modules earn their keep.

### 5.3 What changes where (summary)

- **OrdeloAgent:**
  - M1–M6 plus the `/web/*` router (`watomation/routers/web_hooks.py`).
  - Payment-hook hardening.
  - The 10 hook call sites switched to `customer_notifier.publish`.
  - SQL: `job_close_thread` filter; migrations (§6).
  - `rider_agent.py:send_customer_contact` tells the rider no number is on file for a web order (D24).
  - All new Supabase REST calls wrapped in `asyncio.to_thread` (CLAUDE.md rule).
- **Payment service:** **no change (D22).**
- **restaurant-frontend:**
  - New `(web)` route group: landing, town, restaurant, checkout, return, order and lookup pages.
  - New `/api/web/*` proxy routes with a server secret.
  - A persisted basket, and log redaction.
  - Existing `/restaurant/[id]` WhatsApp flow is **unchanged**.
- **restaurant-agents:** no change in R1 (no signing, D23). R4: the new `apps/ordelo_agg` (app-owned GraphAdapter), which needs a CONSTITUTION/ADR review because it serves no restaurant `rest_ref` [B].

---

## 6. Data model (proposed DDL)

All migrations are **additive** and backward-compatible. **R1's SQL ships as one file, `ordelo_datamodels/migrations/ordelo_agg_r1.sql`, run manually by the owner (D31).** It contains the DDL below (001–003) plus the RPCs `create_food_order_with_items` (F4), `record_payment_authorised` (M2) and the alert-only init reconciler. The DDL below is the design summary; the file is authoritative.

### 6.1 R1: WhatsApp-safe foundation

```sql
-- 001_food_order_channel.sql   (no contact_* columns: web collects no name or phone, D24)
ALTER TABLE public.food_order
  ADD COLUMN IF NOT EXISTS origin_channel TEXT NOT NULL DEFAULT 'whatsapp'
      CHECK (origin_channel IN ('whatsapp','web')),
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT NULL,
  ADD COLUMN IF NOT EXISTS order_dtts_utc TIMESTAMPTZ NULL,   -- optional; order_dtts already exists
  ADD COLUMN IF NOT EXISTS storefront TEXT NOT NULL DEFAULT 'direct'
      CHECK (storefront IN ('direct','ordelo'));             -- §8.1; Q11 answered yes (D28); immutable like origin_channel
CREATE UNIQUE INDEX IF NOT EXISTS food_order_idempotency_key_uq
  ON public.food_order (idempotency_key) WHERE idempotency_key IS NOT NULL;
-- origin_channel is written once at insert; enforce immutability:
CREATE OR REPLACE FUNCTION forbid_origin_channel_change() RETURNS trigger AS $$
BEGIN
  IF NEW.origin_channel IS DISTINCT FROM OLD.origin_channel THEN
    RAISE EXCEPTION 'food_order.origin_channel is immutable';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER food_order_origin_channel_immutable
  BEFORE UPDATE ON public.food_order FOR EACH ROW EXECUTE FUNCTION forbid_origin_channel_change();

-- 002_payment_event.sql  (inbox + outcome log; replaces the need for new payment_status values, respecting ADR-0002)
CREATE TABLE IF NOT EXISTS public.payment_event (
  id                 BIGSERIAL PRIMARY KEY,
  provider_event_id  TEXT NOT NULL,             -- Stripe evt_… (or synthetic 'ordelo:<kind>:<order_id>:<n>' for Ordelo-originated outcomes)
  order_id           TEXT NOT NULL REFERENCES public.food_order(order_id),
  kind               TEXT NOT NULL CHECK (kind IN (
                        'authorised','authorised_duplicate','capture_requested','capture_succeeded',
                        'capture_failed','cancel_requested','cancel_succeeded','cancel_failed',
                        'refund_succeeded','rejected_state',
                        'init_reconcile_alerted')),   -- no 'rejected_signature': no signature check (D23)
  payment_intent_id  TEXT NULL,
  amount_pence       INTEGER NULL,
  payload            JSONB NOT NULL DEFAULT '{}'::jsonb,   -- redacted: no phone/email
  received_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider_event_id)
);
CREATE INDEX IF NOT EXISTS payment_event_order_idx ON public.payment_event (order_id, received_at);

-- 003_customer_events_and_subscriptions.sql
CREATE TABLE IF NOT EXISTS public.order_notification_subscription (
  id            BIGSERIAL PRIMARY KEY,
  order_number  TEXT NOT NULL REFERENCES public.food_order(order_number),
  channel       TEXT NOT NULL CHECK (channel IN ('whatsapp_restaurant','whatsapp_agg','web_page')),
  destination   TEXT NULL,       -- recipient phone for whatsapp_*; NULL for web_page
  detail_level  TEXT NOT NULL DEFAULT 'full' CHECK (detail_level IN ('full','status_only')),
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  source        TEXT NOT NULL,   -- 'order_origin' | 'wa_handoff'
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deactivated_at TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ons_unique_active
  ON public.order_notification_subscription (order_number, channel, COALESCE(destination,''))
  WHERE active;

CREATE TABLE IF NOT EXISTS public.order_customer_event (
  id            BIGSERIAL PRIMARY KEY,
  order_number  TEXT NOT NULL REFERENCES public.food_order(order_number),
  event_key     TEXT NOT NULL,   -- deterministic, e.g. 'payment_authorised', 'pickup_time_set:2026-09-29T18:40Z', 'rider_assigned:<dispatch_id>'
  event_type    TEXT NOT NULL,   -- see §7.4 catalogue
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_estimate   BOOLEAN NOT NULL DEFAULT FALSE,
  data          JSONB NOT NULL DEFAULT '{}'::jsonb,   -- minimal; redaction happens at read time
  UNIQUE (order_number, event_key)
);

CREATE TABLE IF NOT EXISTS public.notification_outbox (
  id              BIGSERIAL PRIMARY KEY,
  event_id        BIGINT NOT NULL REFERENCES public.order_customer_event(id),
  subscription_id BIGINT NOT NULL REFERENCES public.order_notification_subscription(id),
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT NULL,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, subscription_id)
);
CREATE INDEX IF NOT EXISTS notification_outbox_due ON public.notification_outbox (status, next_attempt_at);
```

**No backfill (decided 2026-09-30):** there are no live orders, so no in-flight WhatsApp order needs a subscription. The notifier's **mandatory fallback** covers any WhatsApp-origin order without a subscription by routing it to the restaurant app, so a backfill would be redundant even if orders were in flight. From R1b on, `create_order_with_items` creates the `whatsapp_restaurant` subscription for each new WhatsApp order. **Pre-deploy check:** confirm no order is mid-fulfilment (§18 R1a).

### 6.2 R3: web ordering

```sql
-- 004_order_access_grant.sql  (access tokens + WhatsApp hand-off codes)
CREATE TABLE IF NOT EXISTS public.order_access_grant (
  id            BIGSERIAL PRIMARY KEY,
  order_number  TEXT NOT NULL REFERENCES public.food_order(order_number),
  kind          TEXT NOT NULL CHECK (kind IN ('page_token','wa_handoff')),
  secret_hash   BYTEA NOT NULL UNIQUE,          -- sha256(raw)
  detail_level  TEXT NOT NULL DEFAULT 'full',
  expires_at    TIMESTAMPTZ NOT NULL,           -- page_token: order_dtts + 30 days; wa_handoff: +24h
  consumed_at   TIMESTAMPTZ NULL,               -- wa_handoff only (single use)
  consumed_by   TEXT NULL,                      -- sender phone for wa_handoff
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.order_lookup_attempt (   -- only if Q14 keeps a lookup fallback (no phone to check, D24)
  id BIGSERIAL PRIMARY KEY, order_number TEXT, ip_hash BYTEA, success BOOLEAN, at TIMESTAMPTZ DEFAULT now());

-- 005_web_session_meta.sql
CREATE TABLE IF NOT EXISTS public.web_session_meta (
  thread_id     TEXT PRIMARY KEY REFERENCES public.thread(thread_id),
  visitor_id    TEXT NOT NULL,
  rest_ref      VARCHAR(4) NOT NULL,
  mode          TEXT NOT NULL CHECK (mode IN ('delivery','takeaway')),
  town_slug     TEXT NULL,
  postcode_district TEXT NULL,          -- outward code only (e.g. 'SP1'), not the full postcode
  utm           JSONB NOT NULL DEFAULT '{}'::jsonb,
  referrer_host TEXT NULL,
  device_class  TEXT NULL,              -- 'mobile'|'desktop'|'tablet' (derived, no raw UA)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 006 (removed 2026-10-01): no customer_phone column. Web orders carry no phone (D24);
--     init_delivery / init_takeaway are unchanged.

-- 007_admin_views_origin.sql : add fo.origin_channel to v_admin_orders (both UNION branches).
```

`thread` needs **no DDL**: `create_thread('WEB', NULL)` already works (recipient is nullable [V]). Two guards are needed:

- `job_close_thread.sql`: add `AND recipient IS NOT NULL AND agent IS DISTINCT FROM 'WEB'`.
- After payment is confirmed or the checkout is abandoned, web threads are set `is_active=false` by M6/M2. Retention is in §16.

### 6.3 R4: WhatsApp hand-off

```sql
-- 008_web_customer_link.sql
CREATE TABLE IF NOT EXISTS public.web_customer_link (
  w_cust_id  VARCHAR(12) NOT NULL REFERENCES public.customer_master(cust_id),
  cust_id    VARCHAR(12) NOT NULL REFERENCES public.customer_master(cust_id),  -- the verified phone-keyed row
  wa_thread_id TEXT NULL,
  via        TEXT NOT NULL DEFAULT 'wa_handoff',
  linked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (w_cust_id, cust_id)
);
```

### 6.4 Why not a single `channel` column

`origin_channel` answers where the order came from (immutable, used for reporting and routing defaults). `food_order.action` answers how it is fulfilled. Subscriptions answer where updates go (0..n, changeable). A single column can't express "web order, also on WhatsApp, forwarded to a partner at status-only". Putting the channel on `thread` would couple business routing to conversation runtime, which the restaurant-agents domain model explicitly rejects ("runtime graph state is never the business source of truth").

---

## 7. Order state model

### 7.1 Dimensions (existing columns; no new status column)

| Dimension | Source of truth | Values [V] |
|---|---|---|
| Payment | `food_order.payment_status` + `payment_event` | `requires_payment` → `requires_capture` (authorised) · `pay_at_rest` (WhatsApp takeaway only). Capture and cancel outcomes are **only** in `payment_event` (new). |
| Restaurant acceptance | `{delivery,takeaway}_summary.restaurant_confirmation_status` | `restaurant_unconfirmed`, `restaurant_accept`, `restaurant_decline`, `restaurant_timedout`, `auto_accept`, `auto_decline`, `restaurant_pickuptime_adjusted` (delivery) |
| Delivery lifecycle | `delivery_summary.status` + `delivery_dispatch.status` + `delivery_inflight` existence | summary: `restaurant_unconfirmed`, `unassigned`, `timedout`, `assigned`, `completed`; dispatch: …`assigned`, `pickedup`, `completed` (see `ordelo/delivery_progress.py:check_delivery_progress`) |
| Takeaway lifecycle | `takeaway_summary.status` | `restaurant_unconfirmed`, `pickup_confirmed`, `declined`, `completed` |
| Refund/release | `payment_event` | `cancel_succeeded` (authorisation released), `refund_succeeded` (post-capture, manual today) |

### 7.2 Transition table (who may cause each transition)

| From | Event / command | To | Actor (module) | Customer event emitted |
|---|---|---|---|---|
| — | create-order | payment `requires_payment` | Ordelo `create_order` (M6 for web) | none (a `web_page` subscription is created) |
| `requires_payment` | Stripe `checkout.session.completed` (first; unsigned, D23) | `requires_capture`; init summary | M2 (Stripe webhook) | `payment_authorised` |
| `requires_payment` (web) | authorised after the late-payment cut-off (Q17) | stays `requires_payment`; authorisation cancelled through the existing cancel call | M2 | `payment_released` |
| `requires_capture` | duplicate `payment.authorised` | no change | M2 | none; `payment_event(kind='authorised_duplicate')` |
| any ≠ `requires_payment` | late or out-of-order `authorised` | no change | M2 | none; `rejected_state` logged and alerted |
| `requires_payment` | Checkout Session expired / abandoned | stays `requires_payment`; web thread inactive | sweep job (R3) | none (the page shows "Payment not completed") |
| summary `restaurant_unconfirmed` | admin Accept + pickup time | `restaurant_accept`, `pickup_time` set | restaurant admin (WhatsApp callback) | `pickup_time_set` (takeaway) / `restaurant_accepted` (delivery) |
| `restaurant_unconfirmed` | timeout | `restaurant_timedout` → auto-accept with default pickup | pg_cron + `_handle_restaurant_timedout` | as above, flagged `auto` |
| accepted | admin adjusts pickup | `restaurant_pickuptime_adjusted` | admin | `pickup_time_updated` |
| `restaurant_unconfirmed` | Decline (**button disabled today**) | takeaway `declined` + cancel; delivery → **F8 bug** | admin | `restaurant_declined` + `payment_released` |
| takeaway `pickup_time` first set | trigger | capture (ADR-0002) | `pickup_time_updated_hook` | `payment_captured` (web page only) |
| delivery `unassigned` | rider accepts | `assigned`, inflight created, capture | DB + `delivery_inflight_graph_init_hook` | `rider_assigned`, `payment_captured` |
| delivery `unassigned` | all vehicle types timed out | `timedout`, cancel payment | `process_delivery` + `delivery_timedout` | `no_rider_found` + `payment_released`/`payment_release_failed` |
| dispatch `assigned` | rider verifies restaurant code | `pickedup` | rider agent tool | `food_collected` |
| picked up | rider enters customer geofence | — | location hooks | `rider_near_customer` (includes the code for `full` only) |
| `pickedup` | rider verifies customer code | `completed` | rider agent tool / `dispatch_complete_func` | `delivered` |
| takeaway ready | admin "Ready" | — | `on_callback_wa_handler` takeaway-ready | `ready_for_collection` |
| takeaway | collected | `completed` [A: who sets it isn't verified] | — | `collected` |
| before accept | customer cancel | **not supported (D14)** | — | — |

### 7.3 Customer-facing status (derived in M5, never stored)

Precedence runs top to bottom:

1. **Cancelled.** `payment_event.cancel_succeeded` or summary `declined`/`timedout`. Sub-state: "Payment released" / "Refund pending".
2. **Delivered / Collected.** Terminal success.
3. **On its way.** Dispatch `pickedup`.
4. **Rider assigned.** Inflight exists and dispatch is `assigned`.
5. **Ready for collection.** Takeaway ready event.
6. **Preparing.** Accepted and `pickup_time` set. Shown as "Ready around HH:MM" (estimate until restaurant_accept; confirmed after).
7. **Waiting for restaurant.** `restaurant_unconfirmed`.
8. **Confirming payment.** `requires_payment`, created within the last 10 min, no `payment_event` yet. (The return page is deferred, D26.)
9. **Payment not completed.** `requires_payment`, older than the late-payment cut-off (Q17). The Stripe session itself stays payable for Stripe's default 24 h (D22).

### 7.4 Customer event catalogue (M3)

| `event_type` | Emitted at (existing code point → becomes `publish`) | `full` data | `status_only` data |
|---|---|---|---|
| `payment_authorised` | `payment_hooks.payment_complete_path` | totals | none |
| `restaurant_accepted` / `pickup_time_set` / `pickup_time_updated` | `takeaway_hooks._post_pickup_time_event`; delivery confirmation handlers | pickup_time | pickup_time |
| `rider_assigned` | `delivery_hooks.post_rider_event_inflight` | rider first name | none |
| `food_collected` | `agent_app_handlers.post_rider_event_restaurant_cc` | — | — |
| `rider_near_customer` | `location_hooks` (cust enter) | **customer code** | none |
| `delivered` | `agent_app_handlers.post_rider_event_customer_cc` | — | — |
| `no_rider_found` | `delivery_hooks.post_delivery_timedout` | payment_cancelled | payment_cancelled |
| `restaurant_declined` | `takeaway_hooks._handle_restaurant_decline` | — | — |
| `ready_for_collection` | `on_callback_wa_handler` takeaway-ready | — | — |
| `payment_captured` / `payment_released` | capture/cancel functions (via M2 outcome log) | amount | none |

`capture_address` → `order-address-update` and `customer_hooks.update_address` are **pre-order conversational events**, not order events. They stay direct calls, guarded to skip W-ids.

---

## 8. Public page routes (restaurant-frontend)

Implement as a new App Router group, `app/(web)/…`. **Leave `/restaurant/[id]`, `/order-summary` and `/address-update` untouched** for WhatsApp links.

| Route | Purpose | Index? | Cache | Notes |
|---|---|---|---|---|
| `/` | Landing: **postcode gate** (D7) with a "Collecting instead? Choose your town" link | index | static + ISR | Postcode → `GET /api/web/eligibility` → redirect to `/town/{town}` with a `ordelo_loc` cookie (HttpOnly, SameSite=Lax: `{postcode, lat, lon, mode:'delivery'}`). **The postcode is never in the URL.** |
| `/town/{town}` | Restaurants in the town; Delivery/Collection toggle; per-card eligibility when `ordelo_loc` exists | index | ISR (list); eligibility fetched client-side | `town` is a slug from the `TOWNS` registry (D18). Unknown slug → 404 with a town list. Mode is a cookie, not the path, so there's one canonical URL. |
| `/town/{town}/{rest_ref}` | Menu (the **Ordelo storefront page**, §8.1) | index | ISR (shell); menu via `/api/menu` | Path segment = the lowercase `rest_ref` config key (e.g. `sfcs`). `canonical` = the restaurant's primary town, so a restaurant listed in several towns has one canonical URL. |
| `/r/{rest_ref}` | Short/direct link | noindex | redirect | 308 → primary-town URL. It keeps old or shared links alive when slugs change (`previousSlugs[]` in config → 308). |
| `/checkout` | Details (delivery address with flat/building, delivery instructions, notes) → review with server fees → Pay | **noindex** | `no-store` | Needs a basket and the `ordelo_co` cookie. |
| `/checkout/return` | **Deferred (D26, §13.1).** Stripe can't send web customers here until the redirect gap is fixed. | noindex | no-store | When built: **not authoritative**; polls the order view until `payment_authorised` or a 60 s timeout, then goes to the order page. Until then the customer reopens the order page from the saved link or cookie. |
| `/town/{town}/orders/{orderNumber}` | **Order page** (tracking, help, receipt, WhatsApp CTA) | **noindex** | `private, no-store` | Requires the `oat_{orderNumber}` cookie (full) or a lookup session (status_only); otherwise renders the lookup form. Keeps your preferred path. |
| `/o/{token}` | Secret-link exchange | noindex | no-store | Verifies the token → sets the HttpOnly cookie → 303 to the order page. `Referrer-Policy: no-referrer`; the token is never logged. |
| `/orders/find` | Lookup fallback — **pending Q14** (no phone to check, D24) | noindex | no-store | Rate-limited; status only. |
| `/legal/*` | Terms, privacy, allergens, cookies | index | static | Needed at launch (§17). |

**Town vs eligibility.** A town is discovery context only. **Delivery eligibility always comes from `(rest_ref, customer lat/lon)` via pricing.** A postcode just over a town border still sees restaurants from the neighbouring town when the landing gate returns them (the eligibility query runs over all web-enabled restaurants within N km, not just one town).

**Restaurant admins** (brief item 6.2): don't overload the customer order path. Use the existing `/rest-admin/orders` portal, extended later with a detail view that reuses the same timeline component, with separate auth (`__Host-radash`) and separate data scope.

**SEO:**

- `robots.txt` disallows `/checkout`, `/o/`, `/orders/`, `/*/orders/`.
- `X-Robots-Tag: noindex` on the private routes.
- Sitemap covers `/`, towns and restaurant pages.
- Restaurant JSON-LD (`Restaurant`, `servesCuisine`, `openingHoursSpecification` from `service_hours_json`).
- No `recipient`/`thread_id` in any web URL.

### 8.1 Storefronts, channels and the page design (D20, D21)

There are two independent axes. Keep both explicit so the UIs can diverge later without copying code.

- **Storefront** is who sells and on what terms: branding, offers/discounts/vouchers, voucher UX placement, collection payment options, page chrome, and (possibly) commission. Values: `ordelo` (aggregator) and `direct` (a restaurant's own customers, today's restaurant-agents apps).
- **Channel** is how the customer arrived and is identified: session source, where the address comes from, checkout target, post-payment destination. Values: `web` (cookies) and `whatsapp_link` (a menu link sent by an agent).

| | Web | WhatsApp link |
|---|---|---|
| **Ordelo storefront** | `/town/{town}/{rest_ref}`, **built now** (R0/R3) | Same page, opened from `ordelo-agg-agent`, **R4+** |
| **Direct (restaurant) storefront** | Not planned; decide later | `/restaurant/[id]` **today, untouched** |

**Now (R0/R3), for the Ordelo storefront only:**

1. **One Ordelo page for both Ordelo channels** (D20). `/town/{town}/{rest_ref}`, using the lowercase `rest_ref` config key (e.g. `sfcs`) as the path segment. The page is a thin route shell that resolves `{storefront:'ordelo', channel}` and renders shared blocks.
2. **Shared leaf components, never copied.** Import the existing `ItemCard`, `CategoryTabs`, `MenuItems`, `AddonCustomizationModal`, `BasketBar`, `QuantityControl`, `DishImage` and `SkeletonCard` as they are. The Ordelo page gets its **own container** (`components/ordelo/OrdeloMenuContainer.tsx`, `OrdeloBasket.tsx`) instead of adding branches to `MenuContainer.tsx` (652 lines) or `BasketDrawer.tsx` (447 lines). Both of those mix menu UI with WhatsApp session parameters, the verify-session check, the overwatch bypass by `recipient`, discount maths and the checkout call [V]. Some container-level logic (opening-hours display, voucher gate) is duplicated between the two containers for now. That is an **accepted, time-boxed duplication**, logged for the later decision.
3. **Channel-session seam** (`lib/storefront/session.ts`). Interface: `{ customerRef, checkoutRef, mode, minimumOrder, canCheckout(), checkout(basket), afterPayment }`. `WebCookieSession` ships in R3. `WhatsAppLinkSession` for the Ordelo page ships with R4 (Ordelo menu link carries a short-lived signed token, **not** raw `recipient`/`thread_id`).
4. **Ordelo offers kept separate from restaurant offers, still client-side (D8).** Add an optional `ordelo` offers block to `RestaurantConfig` (`ordeloOffers: { discountPercentage, discountPercentageCollection, discountCollectionThreshold, voucher }`). The Ordelo page reads **only** it through one helper, `resolveOffers({storefront, restRef, mode, subtotal, voucher})`. If the block is absent, the Ordelo page shows **no discount** rather than silently inheriting the restaurant's direct offers. Direct offers keep today's flat keys and today's code path.

**Later: restaurant-specific UI decision (R5, D21).** The options are:

- **(a) Converge.** `/restaurant/[id]` becomes a shell over the same blocks with `storefront:'direct', channel:'whatsapp_link'`. Extract `resolveOffers` for direct offers, and move the duplicated container logic into shared blocks.
- **(b) Stay different.** Keep `MenuContainer`/`BasketDrawer` for direct, but extract the leaf blocks both use, so fixes (allergens, add-on validation, rounding) land once.

Decision triggers:

- Restaurant owners want Ordelo-page features (order page, web checkout) for their own customers → **(a)**.
- A restaurant brand needs a bespoke layout → **(b)**, with its own shell.

Before either option, add Playwright before/after tests on live `/restaurant/[id]` links, because that page takes today's revenue.

**Backend dimension.** `origin_channel` can't tell an `ordelo-agg-agent` WhatsApp order from a restaurant-agents WhatsApp order. Both are `whatsapp`. **Recommended:** add `food_order.storefront` (`direct` | `ordelo`, default `direct`, immutable like `origin_channel`) in the R1 migration. Existing and WhatsApp restaurant orders are `direct`; web and `ordelo-agg-agent` orders are `ordelo`. It records who funds the discount and which commission applies, and it drives reporting. See Q11.

## 9. API contracts

### 9.1 Browser → Next.js (`app/api/web/*`)

The browser never sends `recipient`, `thread_id`, `cust_id` or tokens in bodies. Those live in HttpOnly cookies that the Next route reads and forwards. Every Next → Ordelo call adds `X-Ordelo-Web-Key: <server secret>`.

| Next route | Method | Ordelo call | Notes |
|---|---|---|---|
| `/api/web/eligibility?postcode=SP1+2AB&mode=delivery` | GET | `GET /web/eligibility` | Sets `ordelo_loc`. |
| `/api/web/checkout-sessions` | POST | `POST /web/checkout-sessions` | Sets the `ordelo_co` cookie (signed, HttpOnly, 2 h). |
| `/api/web/address` | POST | `POST /order-hooks/capture-address` (existing; `recipient`=W-id from the cookie) | The notifier guard skips the restaurant-app hook for W-ids. |
| `/api/web/orders` | POST | `POST /web/orders` | `Idempotency-Key` header; sets `oat_{orderNumber}`. |
| `/api/web/orders/{orderNumber}` | GET | `GET /web/orders/{orderNumber}` + `X-Order-Access` | ETag on `last_event_id`. |
| `/api/web/orders/lookup` | POST | `POST /web/orders/lookup` | Status-only session cookie (1 h). **Pending Q14.** |
| `/api/web/orders/{orderNumber}/whatsapp` | POST | `POST /web/orders/{orderNumber}/handoff-codes` | R4 |

### 9.2 Ordelo `/web/*` (new router, `watomation/routers/web_hooks.py`; requires `X-Ordelo-Web-Key`)

**Eligibility** (wraps `get_min_order_value` for each web-enabled restaurant and **distinguishes failures**):

```http
GET /web/eligibility?postcode=SP1%202AB&mode=delivery&rest_refs=ELAS,SFCS,BNAT
200
{
  "postcode": "SP1 2AB", "lat": 51.07, "lon": -1.79, "town_slug": "salisbury",
  "restaurants": [
    {"rest_ref":"SFCS","status":"deliverable","min_order_value":12.0,"estimated_delivery_fee":2.99,"distance_miles":1.4},
    {"rest_ref":"ELAS","status":"out_of_range"},
    {"rest_ref":"BNAT","status":"unavailable","reason":"pricing_service_error"}
  ]
}
```

`status` ∈ `deliverable | out_of_range | unavailable | closed`. Today `-1` means both "out of range" and "service failed" [V] (`order_service.get_min_order_value`). The new helper returns a typed result (`None` from `_call_pricing_service` → `unavailable`; a car option missing or flagged → `out_of_range`) [A: confirm the pricing service's out-of-range signal, §21].

**Start checkout:**

```http
POST /web/checkout-sessions
{"rest_ref":"SFCS","mode":"delivery","visitor_id":"v_9f…","town_slug":"salisbury",
 "utm":{"source":"google"},"referrer_host":"google.com","device_class":"mobile","postcode_district":"SP1"}
201
{"thread_id":"WEB-2b9c…","cust_id":"W7K2M9QX4TPA","expires_at":"2026-09-29T19:40:00Z"}
```

**Create web order** (reuses `create_order_with_items`; returns server fees):

```http
POST /web/orders
Idempotency-Key: 5d0c6c1e-…            # per basket version, generated client-side, kept in sessionStorage
{"thread_id":"WEB-2b9c…","cust_id":"W7K2M9QX4TPA","rest_ref":"SFCS","order_type":"delivery",
 "order_items":[{"sku":"burger_1","quantity":2,"price":8.0,"product_name":"Burger","modifications":["No onions"]}],
 "notes":"Flat 3, ring twice","client_estimate":{"items_total":16.0,"discount_pct":20}}
201
{"order_number":"SFCS-QKZD-31","order_id":"QKZD-31",
 "items_total":16.0,"service_charge":0.99,"delivery_fee":2.49,"small_order_fee":0.0,"total":19.48,
 "min_order_value":12.0,"payment_url":"https://checkout.stripe.com/c/pay/cs_…",   # no expiry: Ordelo doesn't set one (D22)
 "access":{"token":"<raw 32-byte base64url>","page_path":"/town/salisbury/orders/SFCS-QKZD-31"}}
409  {"error":"idempotency_conflict"}            # same key, different body hash
422  {"error":"below_minimum","min_order_value":12.0}   # web only; §11
422  {"error":"restaurant_closed","next_open":"2026-09-30T11:30:00+01:00"}
422  {"error":"out_of_range"} | 503 {"error":"pricing_unavailable"}
```

Replaying the same `Idempotency-Key` with the same body returns the same 201 payload **without** a new order or payment URL. Only an `access.token` rotation is allowed, because Ordelo stores only hashes and can't re-show the raw token. The Next route keeps the cookie from the first response.

**Order view:**

```http
GET /web/orders/SFCS-QKZD-31
X-Order-Access: <raw token>  |  X-Order-Lookup: <lookup session id>
200
{"order_number":"SFCS-QKZD-31","origin_channel":"web","mode":"delivery","detail_level":"full",
 "display_status":"rider_assigned","last_event_id":1842,"updated_at":"…",
 "payment":{"state":"authorised","captured":false},
 "restaurant":{"name":"Salisbury Fried Chicken","phone":"01722433714","address":"…"},
 "pickup_time":{"at":"2026-09-29T18:40:00+01:00","is_estimate":false},
 "delivery":{"address":"Flat 3, 10 Example St, SP1 2AB","customer_code":"47","rider_first_name":"Sam"},
 "items":[…],"charges":{…},"timeline":[{"type":"payment_authorised","at":"…"},…],
 "support":{"call_restaurant":"tel:01722433714","whatsapp_available":true}}
```

`status_only` omits `delivery.*`, `items`, `charges`, `contact` and `customer_code`.

**Lookup (pending Q14: no phone is collected, D24, so the second factor below has to change or the fallback is dropped):** `POST /web/orders/lookup {"order_number":"SFCS-QKZD-31","phone":"07700 900123"}` returns `200 {"lookup_session":"…","detail_level":"status_only"}` or `404` (same body for a wrong number and a wrong phone). Limits: 5 attempts per order per hour and 20 per IP-hash per hour.

**Hand-off code (R4):**

```http
POST /web/orders/SFCS-QKZD-31/handoff-codes   (X-Order-Access required)
201 {"wa_link":"https://wa.me/44XXXXXXXXXX?text=Track%20my%20order%20SFCS-QKZD-31%20%C2%B7%20code%207KX9QP","expires_at":"…"}
```

### 9.3 Payment service contract (unchanged, D22)

Web orders use the payment service exactly as WhatsApp orders do [V at payment-service `58158ca`]. Nothing is added to the request, and the payment service is not redeployed.

**Create** (`FoodOrder.payment_uri` → `POST {stripe_url}/threads/{thread_id}/orders/{order_id}/payment-url`). For a web order, `thread_id` is the web thread (`WEB-…`); the payment service only stores it as Stripe metadata.

```json
// delivery: FoodOrder.gen_payment_intent_payload()
{"items":[…],"currency":"GBP","action":"delivery","manual_mode_capture":true,"notes":"…","restRef":"sfcs"}
// collection: payment.generate_takeaway_manual_payment_url() (ADR-0002)
{"total_amount":16.0,"items":[…],"currency":"GBP","action":"collection","restaurant_confirmation_code":"N/A",
 "manual_mode_capture":true,"notes":"…","printonlyjob":false,"restRef":"sfcs"}
// response
{"url":"https://checkout.stripe.com/c/pay/cs_…","paymentIntendID":"…"}   // Ordelo reads only "url"
```

**Capture** (rider accepts the job for delivery; pickup-time boundary for collection) and **cancel** (decline or no rider) use the same path with `payment_mode` `capture` / `cancel` and `restRef`, unchanged.

**What Ordelo receives.** Stripe posts `checkout.session.completed` straight to `/payment-hooks/payment-complete` (§2.1 step 8). It is not signed by anyone Ordelo checks (D23). The fields Ordelo uses are already in Stripe's event:

```http
POST /payment-hooks/payment-complete
{"id":"evt_…","type":"checkout.session.completed",
 "data":{"object":{"id":"cs_…","payment_intent":"pi_…","amount_total":1948,
   "metadata":{"orderID":"QKZD-31","threadID":"WEB-2b9c…","restRef":"sfcs","action":"delivery","captureMode":"manual"}}}}
```

**Consequences of keeping the contract** (all handled in Ordelo or deferred):

| Not available from the payment service | Effect for web | Handling |
|---|---|---|
| Per-order `success_url` / `cancel_url` | Customer lands on the restaurant's fixed URL (wa.me for elas and sfcs) | Deferred, §13.1 (D26) |
| Session expiry | Checkout stays payable for Stripe's default 24 h | Late-payment guard in M2 (Q17) |
| Idempotent session creation | A retried create can leave an orphan session | Only the newest URL is shown; the orphan expires (§13) |
| Name / phone collection | None collected | Not needed (D24) |
| Fail-closed `restRef` | Unknown `restRef` is charged on Elas's account | M6 rejects unknown `rest_ref`s (F13) |
| Signed forward | — | No forward exists; Stripe calls Ordelo directly, unsigned (D23) |

### 9.4 Ordelo → ordelo_agg (R4)

- `POST {ORDELO_AGG_APP_URL}/order-event-hooks/ORDELO/customer-event`
  - Body: `{"order_number","event_type","occurred_at","destination","detail_level","data"}`
  - Signed with an HMAC secret shared between Ordelo and `ordelo_agg` (new in R4; unrelated to the payment webhook).
- `POST /web/whatsapp-bind` (agg → Ordelo)
  - Request: `{"code":"7KX9QP","sender":"447700900123","wa_thread_id":"ORDELO_AGG-…"}`
  - Response: `200 {"order_number","detail_level","view":{…}}`, `410 expired_or_used`, or `404`.

---

## 10. Sequence diagrams

### 10.1 Web delivery: checkout → payment → fulfilment

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant N as Next.js (web)
  participant O as Ordelo
  participant DB as Postgres
  participant P as Pricing
  participant PS as Payment svc
  participant S as Stripe
  B->>N: POST /api/web/eligibility (postcode)
  N->>O: GET /web/eligibility
  O->>P: pricing per restaurant (total_food_value=0)
  O-->>N: deliverable/out_of_range/unavailable
  N-->>B: set ordelo_loc cookie → /town/{town}
  B->>N: browse menu (client prices as today, D8)
  B->>N: POST /api/web/checkout-sessions
  N->>O: POST /web/checkout-sessions
  O->>DB: create_thread('WEB', NULL); web_session_meta
  O-->>N: thread_id, W-id → ordelo_co cookie
  B->>N: POST /api/web/address
  N->>O: POST /order-hooks/capture-address (recipient=W-id)
  O->>DB: upsert customer_master(W-id), cust_rest_map
  Note over O: restaurant-app address hook skipped for W-ids
  B->>N: POST /api/web/orders (Idempotency-Key)
  N->>O: POST /web/orders
  O->>DB: availability + eligibility checks; insert food_order(origin=web)+items (RPC)
  O->>P: final order value (customer_master W-id lat/lon)
  O->>PS: payment-url (thread=WEB-…, existing payload, manual capture)
  PS->>S: Checkout Session (manual capture)
  O->>DB: order_access_grant; subscription(web_page)
  O-->>N: fees, total, payment_url, token → oat cookie
  B->>S: pay (card details only; no name or phone collected, D24)
  S->>PS: checkout.session.completed (stores order → PaymentIntent)
  S->>O: checkout.session.completed (direct Stripe webhook, unsigned, D23)
  O->>DB: payment_event insert (unique evt) ; UPDATE … WHERE requires_payment
  Note over O: web branch: no restaurant-app call (D27)
  O->>DB: init_delivery (p_cust_id = W-id; customer_name = W-id)
  O->>DB: order_customer_event(payment_authorised)
  S-->>B: redirect to the restaurant's fixed success URL (wa.me today; gap D26, §13.1)
  B->>N: customer reopens the order page (saved link or cookie) → poll GET order view
  Note over O,DB: unchanged: confirmation → dispatch → inflight → capture → rider agent
  O->>DB: publish(rider_assigned / food_collected / rider_near_customer / delivered)
  B->>N: order page polls every 15 s
```

### 10.2 Webhook replay and out-of-order handling

```mermaid
sequenceDiagram
  participant S as Stripe
  participant O as Ordelo M2
  participant DB as Postgres
  S->>O: evt_1 (authorised)
  O->>DB: INSERT payment_event(evt_1) ok
  O->>DB: UPDATE food_order SET requires_capture WHERE order_id=… AND payment_status='requires_payment' → 1 row
  O-->>S: 200 applied (init + publish queued once)
  S->>O: evt_1 again (retry)
  O->>DB: INSERT payment_event(evt_1) → unique violation
  O-->>S: 200 duplicate (no side effects)
  S->>O: evt_2 (another authorised for same order, e.g. second session)
  O->>DB: INSERT ok ; UPDATE … → 0 rows
  O->>DB: payment_event(kind=rejected_state)
  O-->>S: 200 (alert: double authorisation → ops cancel that PaymentIntent)
```

### 10.3 WhatsApp hand-off (R4)

```mermaid
sequenceDiagram
  participant B as Browser (order page)
  participant N as Next.js
  participant O as Ordelo
  participant W as WhatsApp (Ordelo customer number)
  participant A as ordelo_agg app
  B->>N: "Get updates on WhatsApp"
  N->>O: POST handoff-codes (X-Order-Access)
  O-->>N: wa_link (code 7KX9QP, 24h, single use)
  B->>W: opens wa.me with prefilled text, taps Send
  W->>A: inbound message (sender 4477…)
  A->>A: get_or_create_thread('ORDELO_AGG', sender)
  A->>O: POST /web/whatsapp-bind {code, sender, wa_thread_id}
  O->>O: consume code; detail level per Q15 (no collected phone to compare, D24)
  O->>O: subscription(whatsapp_agg, sender, level); web_customer_link per Q15
  O-->>A: current order view (catch-up)
  A->>W: free-form summary (inside 24h window)
  O->>A: later events via notifier outbox
  A->>W: utility template if window closed, else free-form
```

### 10.4 Web collection

The flow is the same as 10.1 without address and eligibility. `init_takeaway` then runs the existing confirmation flow (D13). The order page shows "Waiting for restaurant" until `pickup_time` is set, then "Ready around HH:MM". A `pickup_time_updated` event changes the time. Capture happens at the pickup-time boundary (ADR-0002); web delivery captures when a rider accepts the job (D25).

---

## 11. Basket, fulfilment selection and quotation

**Principle under D8:** the client computes item prices and discounts **exactly as today**. The server is authoritative for **fees, eligibility and the charged total** (it already is: `final_order_value` from pricing is what Stripe charges [V]).

| Topic | Launch behaviour | Later (R5) |
|---|---|---|
| Browsing vs quoting | Menus browse freely. The **binding quote is the `POST /web/orders` response** (a persisted order row with `final_order_value`). The review screen shows the server's fees and total before the Pay button. | A server-side quote object with expiry and repricing from `*_menu`. |
| Postcode vs full address | The postcode gives an **estimate** (eligibility, min spend, indicative fee from the district centroid via pricing). The **full address** (geocoded house-level lat/lon) is required before create-order; fees are recomputed then. | — |
| Estimate ≠ final | If the server total differs from the client estimate by ≥ 1p, the review screen highlights "Delivery fee updated for your address: £x → £y" and requires an explicit tap. | — |
| Minimum spend | **Current rule [V]: discounted items subtotal ≥ min, before fees** (client). Web adds a **server check** in `/web/orders` using `get_min_order_value` for the W-id location and `total_price` (the discounted items sum the client sent). The WhatsApp flow is unchanged. | Evaluate on the server-repriced subtotal. |
| Mode, restaurant, address or postcode change | Changing **mode** re-applies the client discount (mode-specific, as today) and drops the pending order (new Idempotency-Key). Changing **address or postcode** requires a new create-order. Changing **restaurant** shows "Start a new basket? Your SFCS basket will be cleared". **One restaurant per basket.** | Multi-restaurant baskets: no. |
| Basket persistence | `localStorage` keyed `basket:v1:{rest_ref}` with a `menu_version` (hash of the SKU list) and `saved_at`. Wrap it in try/catch. Items whose SKU is missing or `available=false` in the fresh menu are removed with a notice. Discard after 24 h. | Server baskets for accounts. |
| Stale offers | Discounts are read from config at render time (as today). Vouchers keep today's client gate. | Offers table (R5). |
| Idempotency key | Hash of `(rest_ref, mode, items, notes, address hash)` + a random salt per checkout visit, so the same basket and the same visit produce the same key. | — |

**Accepted-risk note (D8), to keep visible in the code:** a tampered browser can submit lower item prices or a discount of its own choosing. Mitigations at launch that need no pricing change:

- **R3 monitoring:** a nightly job compares `order_item.price` with `{rest}_menu.price × (1 − configured max discount)` and alerts on anything below.
- Restaurants see the item totals on their receipts.

Server-side pricing is in R5.

---

## 12. Availability and collection-time rules

| Rule | Launch | Where |
|---|---|---|
| Opening hours and order cutoff | Enforced **server-side** in `/web/orders` (and shown client-side) using `restaurant_master.service_hours_json` and the per-service cutoff minutes (`migrations/add_order_cutoff_minutes.sql`). Reuse the restaurant-agents `WeeklySchedule` semantics (new orders close 15 min before the interval ends [V, domain model]); port a small Python evaluator into Ordelo. | M6 |
| Temporary pause / emergency close | Frontend `forceStatus` (config) **and** an Ordelo `ordelo_config` key `{REST_REF}_WEB_ORDERING_PAUSED` checked in `/web/orders`, so ops can pause without a frontend deploy. | M6 |
| Sold-out items | Menu `available=false` is hidden or disabled (as today). An item that sells out between menu load and order is not detected server-side at launch (D8) [B]. | R5 |
| Delivery capacity (no riders) | Not predicted. The existing timeout → `no_rider_found` → cancel authorisation → page message. Optional: `{REST_REF}_WEB_DELIVERY_PAUSED` for ops. | existing + M6 |
| ASAP vs scheduled | **ASAP only.** Scheduled orders are later. | — |
| Collection time | **Not set by the customer (D13).** The existing confirmation flow sets it; the page shows "Waiting for restaurant" and then the time. After a timeout it's auto-accepted with the default pickup minutes [V]. Label it "estimate" until `restaurant_accept`/`auto_accept` sets `pickup_time`, then "confirmed", and "updated" on `pickuptime_adjusted`. | existing |
| Restaurant can't meet the time | They use the existing adjust-pickup callback → `pickup_time_updated` event → page and WhatsApp. | existing |
| Rejection or timeout after payment | Takeaway decline cancels the authorisation (existing) and publishes `restaurant_declined` + `payment_released`. Delivery decline is **disabled** (F8); fix it before enabling. A restaurant timeout means auto-accept, so no customer-facing rejection. | existing + M3 |

---

## 13. Payment and order creation under retries and partial failure

**Ordering (existing and kept):**

1. Order row created (`requires_payment`).
2. Checkout Session created.
3. Customer authorises (manual capture).
4. Webhook sets `requires_capture` and inits fulfilment.
5. Capture when a rider accepts the job (delivery) or at the pickup-time boundary (takeaway). Always manual capture for web (D25).
6. Cancel on decline or no rider.

A restaurant never sees an unpaid web order, because init only happens on authorisation. (The one exception is a forged `payment-complete` event, an accepted risk under D23.)

| Failure mode | Handling |
|---|---|
| Double click / multiple tabs | `Idempotency-Key` (unique on `food_order.idempotency_key`) returns the same order and URL. Two genuinely different baskets are two orders; that's a legitimate repeat. |
| Repeated create while the payment URL call fails | The order exists with `payment_url` NULL → the same key retries `generate_payment_intent_url` only. The payment service has no idempotency key (D22), so if the first call reached Stripe this creates a second session. Only the newest URL is shown; the orphan expires unused after 24 h. |
| Duplicate webhook | `payment_event.provider_event_id` unique → 200 no-op. |
| Out-of-order or late webhook (order already captured or cancelled) | Conditional UPDATE affects 0 rows → `rejected_state` + alert. **Never** regress `payment_status`. |
| Two authorisations for one order (two sessions) | Nothing upstream prevents it (D22). The second authorisation is `rejected_state` + alert, and ops cancel that PaymentIntent in the Stripe dashboard. Don't use the payment service's cancel for this: it looks the PaymentIntent up by order number and may pick the first one. |
| Browser closed after paying | Irrelevant: the webhook drives state. The customer returns via the cookie or `/o/{token}` (lookup pending Q14). |
| Post-payment redirect | Goes to the restaurant's fixed URL, not to Ordelo (D26, §13.1). The order page never writes state. |
| Late payment (web) | Checkout stays payable for 24 h (D22). **Proposal (Q17):** if authorisation arrives more than 35 min after the order was created, or the restaurant is now closed, M2 doesn't init; it cancels the authorisation through the existing cancel call and publishes `payment_released`. Stripe notifies the payment service and Ordelo separately, and the payment service stores the PaymentIntent only when its own notification lands, so a cancel that arrives first fails with "no payment details found": retry it with backoff (2, 5, 15 s). |
| Unknown `rest_ref` | The payment service would fall back to `elas` (F13). M6 returns 422 before calling it. |
| Webhook OK but init fails (e.g. `init_delivery` raises) | Today it's logged and lost [V]. **R1:** after M2 applies, the init runs in a background task. A new pg_cron **reconciler** (every 2 min) finds `requires_capture` orders older than 2 min with no summary row and re-invokes init (the summary PK makes it idempotent), then alerts ops. |
| Notifier or agent down | The outbox retries with backoff (1, 5, 15, 60 min; max 6) and then `failed` + alert. Core flow is unaffected. |
| Capture fails | Existing ADR-0002 retry/reconciliation. Record `capture_failed` in `payment_event` and alert. |
| Cancel fails | Record `cancel_failed`. The page shows "We're releasing your payment; contact the restaurant if it's still pending in 5 days" [A: the UK card-issuer release window varies]. |
| Signature | **Not verified, as today (D23).** No Stripe webhook signing secret is configured in Ordelo or the payment service [V]. Replays are harmless (conditional update + `payment_event`). A forged event for an unpaid order would start fulfilment; capture then fails at rider acceptance or pickup time (no stored PaymentIntent) and alerts (M-4). If this is revisited, Stripe already issues a signing secret for every webhook endpoint, so verification is an Ordelo-only change. `/payment-complete-test/{order_id}` is disabled unless `ENABLE_PAYMENT_TEST_ROUTES=true` (off in prod). |
| Duplicate-order protection | For WhatsApp: unchanged (`retain_thread`). For web: none beyond the Idempotency-Key. A soft warning ("You placed a similar order 3 minutes ago — continue?") when the same `ordelo_co` or visitor has a paid order with an identical basket hash in the last 10 min. |

### 13.1 Known gap: post-payment redirect (deferred, D26)

**What happens.** The payment service sets every Checkout Session's success and cancel URL from fixed per-restaurant config (`internal/config/config.go` L166–219) [V]:

| Restaurant | Success / cancel URL today | What a web customer sees after paying or cancelling |
|---|---|---|
| elas | `https://wa.me/message/AIDICBLAE4KZH1` | WhatsApp opens on Elai's chat with a pre-filled message. Elai's agent knows nothing about the web order. |
| sfcs | `https://wa.me/message/KLHBN7UOKO7UE1` | Same, for SFC. |
| bnat | `https://restaurant.ordelo.app/restaurant/bnat` | The WhatsApp menu page, without its session parameters. |

Payment and fulfilment are unaffected: the webhook drives state, and the order page works from the saved link or cookie. The gap is only where the browser lands.

**At launch:** accepted as is (D26). Proposal [B]: the checkout review screen shows "Save your order link" before Pay (§16) and says Stripe may open WhatsApp afterwards.

**Options for the later fix:**

1. **Redirect page owned by Ordelo (recommended).** Point each restaurant's success/cancel URL at a small page, e.g. `https://ordelo.app/pay/return?r=elas`. If the browser holds a web checkout cookie it goes to that order page; otherwise it goes to the same wa.me link as today, so WhatsApp customers see no change. The payment-service *contract* stays the same, but its URLs are hard-coded, so this is a three-string change and a redeploy of the payment service.
2. **Open Stripe in a new tab.** The order page stays open and polls. No payment-service change, but the Stripe tab still ends on wa.me, which is awkward on mobile.
3. **Per-order `success_url` / `cancel_url` in the request.** The cleanest result, but it changes the payment-service contract (the option rejected for launch, D22).

Tracked in R5.

---

## 14. WhatsApp hand-off (R4)

### 14.1 Policy facts (Meta official docs, checked 2026-09-29)

- **Customer service window:** "A 24 hour customer service window" opens when the user messages the business. Non-template messages are allowed only inside it. — [Pricing](https://developers.facebook.com/docs/whatsapp/pricing)
- **Pricing:** since 1 July 2025 pricing is **per message**. Non-template messages inside the window are free; **utility templates are free inside an open window and charged outside it**; marketing templates are always charged. — same source
- **Utility vs marketing:** a utility template must be non-promotional and "specific to or requested by the user (clearly related to their order…)". Miscategorisation leads to warnings and 7- or 30-day utility restrictions. Order-status templates must carry **no** promo copy. — [Template guidelines](https://developers.facebook.com/docs/whatsapp/updates-to-pricing/new-template-guidelines)
- **Opt-in:** it must state that the person is opting in to receive WhatsApp messages **and name the business**. It can be collected on a website. Separate per-category opt-ins are recommended but not mandatory, and opt-out requests must be honoured. — [Getting opt-in](https://developers.facebook.com/docs/whatsapp/overview/getting-opt-in)

**Consequences for the design:**

1. The customer **sends the first message** (wa.me pre-fill), which opens the window. Most delivery lifecycles finish inside 24 h, so free-form works then.
2. Still, **register utility templates** for every §7.4 event: `order_update_status`, `order_pickup_time`, `order_rider_near` (with code), `order_delivered`, `order_cancelled_payment_released`. The notifier then picks template vs free-form per `last_inbound_at`.
3. The web CTA copy counts as the opt-in text: *"Get updates for this order from **Ordelo** on WhatsApp. We'll only message you about this order. Reply STOP to stop."* Transactional scope only.
4. **Marketing consent is separate** and not collected at launch. `cust_rest_map.has_consent` is per restaurant; an Ordelo-brand consent would be a new record [B].

### 14.2 Code, message, binding

- **Code:** 6 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, about 30 bits. Stored as `sha256`, expires after 24 h, **single use**, and at most 3 unconsumed codes per order (older ones are revoked on issue).
- **Pre-filled text:** `Track my order SFCS-QKZD-31 · code 7KX9QP`. No name, address, phone or amount. The order number is display-only; **binding needs the code**.
- **Resolution** (`POST /web/whatsapp-bind`):
  - Valid and unconsumed → consume, record the sender, create a `whatsapp_agg` subscription.
  - **Detail level: pending Q15.** The previous rule (sender equals the collected phone → `full`, otherwise `status_only`, D16) has nothing to compare against, because web orders collect no phone (D24).
- **Replay / forwarded link:** a used code returns `410` → the agent replies "This link was already used. Open your order page to get a new one." A forwarded **unused** code binds the forwardee at the Q15 detail level.
- **Repeated requests from the same sender and order:** idempotent (the unique active subscription index) → the agent resends the current status.
- **Existing WhatsApp thread:** `get_or_create_thread('ORDELO_AGG', sender)` reuses it. AgentState keeps `subscribed_orders: [order_number…]`; replies always name the order. **Multiple active orders** are listed and the customer picks one.
- **Upgrading a detail level:** no self-service at launch; restaurant or ops can change it [B] (replaces the mismatched-phone case, Q15).
- **Opt-out:** "STOP" → deactivate all of that sender's `whatsapp_agg` subscriptions. The order page still works.

### 14.3 Agent entry point: dedicated post-payment entry, not checkpoint resume

| Option | Verdict |
|---|---|
| Resume the web thread's checkpoint | **Rejected.** The web thread has no graph checkpoint (it's a checkout container), and resuming would mix checkout semantics into a support conversation. |
| **Dedicated entry** (recommended) | On bind, the agg app runs its graph with an authoritative system message (the pattern of `order_event_hooks.payment_complete` [V]): *"AUTHORITATIVE ORDER SUBSCRIPTION: customer is following order X (paid, web). Never take orders or payments. Use `get_order_status` to answer."* It loads **M5** for catch-up. Its tools are read-only (`get_order_status`, `call_restaurant_info`, `request_rider_location` via the existing `/wa-request-location`, `send_feedback` via the existing feedback hook). No create-order, pay or capture tools exist, so double charging and duplicate restaurant notifications are impossible by construction. **Scope note (D20):** in a later step `ordelo-agg-agent` also becomes an ordering entry. It sends the customer a signed link to the **same Ordelo page** (`WhatsAppLinkSession`, §8.1), and ordering still happens on the page through the same Ordelo checkout. The agent itself never gains order or payment tools. |

**Events before the customer opens WhatsApp:** stored in `order_customer_event`. On bind, the agent sends one catch-up summary and does **not** replay each event.

**restaurant-agents constraints [V]:** CONSTITUTION/AGENTS require apps to serve a configured `rest_ref` + WABA namespace, and new graph semantics need an app-owned `GraphAdapter`. `ordelo_agg` has no restaurant `rest_ref`. It needs a `RestaurantIdentity(rest_ref="ORDELO", waba_namespace="ordelo_agg")` or an ADR amending the identity invariant [B].

**Web without WhatsApp stays complete:** the order page is the primary tracking surface. The WhatsApp CTA is optional and never blocks.

---

## 15. Customer order page (tracking + help)

**Content (full detail):**

- Status header with a step tracker (§7.3). Label **estimate vs confirmed** times; "Last updated 18:32".
- Restaurant card: name, **phone (tap to call)**, address and map link for collection.
  - Restaurant contact phones today live in restaurant-agents `identity.py` (`contact_phone`) [V]. For launch, add `contactPhone` to the frontend `RestaurantConfig` (D18 style); later `restaurant_master.contact_phone`.
- Delivery: the address (masked in status-only), delivery instructions and the **customer hand-off code** (shown only once the rider is assigned, only at full detail, with "Share this with your rider").
- Rider: first name once assigned. Live location through the Ordelo proxy only (F10), not the raw `live-location-map/{order_number}`.
- Items, modifications, notes, a charges breakdown (items, discount as the client computed it, service, delivery, small-order, total), payment state ("Authorised — you'll be charged when…", "Charged", "Released").
- Receipt: printable view. Stripe emails its own receipt when it has an email [A].
- Help: "Call the restaurant" (primary, D14), "Problem with your order?" → the existing `/customer-hooks/restaurant-feedback` (it WhatsApps admins; ephemeral [V]), and WhatsApp updates (R4).
- Cancellation or refund status when it applies, with plain-language wording.

**Transport: polling.**

- `GET` every **15 s** while visible and non-terminal, **60 s** when hidden (`visibilitychange`), stopped at terminal states.
- `If-None-Match` on `last_event_id` → `304`.
- Exponential backoff on errors (15 → 30 → 60 s) with an "Offline, retrying" banner; the last known state stays visible with its timestamp.

Rationale: the existing admin portal already polls (30 s, visible tab only [V], `app/rest-admin/orders/OrdersView.tsx` ~L110). Supabase Realtime would need anon/RLS access to order tables, but today's server client uses the **secret key with JS-enforced tenancy** [V], and realtime would leak across orders without RLS work. SSE through Next on Amplify is possible, but long-lived connections on serverless are fragile. Revisit SSE when there's volume.

**Stale state and overdue:**

- If `now > pickup_time + 20 min` and the order isn't picked up: "Running a little late — the restaurant has been notified". Ops/admin alerts already exist via `rider_pickup_alert` [V].
- If `delivered` hasn't arrived by `pickup_time + 60 min`: show "Call the restaurant" prominently.
- `no_rider_found` → "We couldn't find a rider. Your payment has been released."

---

## 16. Security, access and privacy

- **Guest checkout:** browse, basket and checkout without an account. **No name or phone is collected (D24).** Email is whatever Stripe Checkout collects by default for its receipt [A]. No OTP (D5).
- **Order access:**
  - At `/web/orders`, M4 issues a `page_token` (32 random bytes, base64url). Only its SHA-256 is stored. It expires at order time + 30 days.
  - The Next route sets `oat_{orderNumber}` (**HttpOnly, Secure, SameSite=Lax, Path=/town, Max-Age 30 d**). The checkout review screen (before Pay) and the order page show "Save your order link" (`/o/{token}`) with a copy button. (The return page is deferred, D26.)
  - `/o/{token}` exchanges the token for the cookie and redirects, so the token never stays in the address bar, history or analytics.
  - **Another device:** use the saved link (the lookup fallback is pending Q14).
  - **Refresh / return later:** the cookie.
- **The order number alone grants nothing.** Because order numbers are guessable (daily global sequence + 4 letters), every order-view request needs a token or a lookup session.
- **Customer vs admin permissions:** separate routes, cookies and data scopes. Shared UI components receive already-redacted view models.
- **Keep secrets and PII out of URLs, analytics and logs:**
  - No phone, postcode, address or token in URLs (postcode goes in a cookie; only `postcode_district` is stored in meta).
  - Redact `middleware.ts` and `/api/menu` query logging (F9).
  - Analytics events carry `rest_ref`, `mode`, `town` and hashed ids only.
  - `Referrer-Policy: strict-origin-when-cross-origin` globally and `no-referrer` on `/o/*`.
- **Server-to-server auth:** `/web/*` requires `X-Ordelo-Web-Key` (in AWS Secrets Manager via `config/aws_setting.py`). The legacy open Ordelo routes stay reachable [V] and are listed in §21.
- **Abuse:**
  - Rate-limit checkout-session creation (per IP-hash, 20/h) and lookup.
  - Stripe Radar covers card fraud [A].
  - Orders abandoned at `requires_payment` are harmless (no init).
- **Retention [B]:** W-id `customer_master` rows, `web_session_meta` and `order_lookup_attempt`. Proposal: anonymise the address 90 days after completion (keep order financials for accounting), meta after 13 months, and lookup attempts after 30 days. Needs your privacy notice and a lawful-basis decision.
- **Privacy notice** must name Ordelo (and each restaurant as the seller) and cover Stripe, WhatsApp (if opted in), analytics cookies (a cookie banner is needed if non-essential analytics are used, under UK PECR [A]) and retention.

---

## 17. Customer-experience and operational requirements

### 17.1 Launch requirements

| Area | Requirement |
|---|---|
| Mobile & slow networks | 360 px first. Skeletons (existing `SkeletonCard`). Menu images lazy and sized. A basket that survives reloads. Order-page polling that tolerates flaky networks. |
| Accessibility | WCAG 2.2 AA: labelled inputs, focus order in modals (existing `Modal`), 44 px targets, status changes announced via `aria-live="polite"`, colour-independent status pills. |
| Address entry | Postcode lookup (existing `/api/postcode-lookup`) plus **manual entry**. Fields: flat/unit, building, house number, street, town, postcode, and **delivery instructions** (≤ 200 chars, appended to `notes` with a prefix until a column exists). |
| Allergens & dietary | Show `dietaryRequirements` (existing) plus a persistent notice: "Allergies? Call {restaurant} on {phone} before ordering." Link it to an allergen policy page. [B/A] UK FSA guidance for distance selling of non-prepacked food expects allergen information to be available **before the purchase is concluded and at delivery**. Verify with the FSA's distance-selling guidance ([FSA](https://www.food.gov.uk/business-guidance/allergen-information-for-non-prepacked-foods-best-practice-distance-selling-and-pre-ordering), [selling food for delivery](https://www.food.gov.uk/business-industry/caterers/startingup/distanceguide)) and decide whether per-item allergen data is needed in `*_menu`. |
| Modifier validation | Client validates `required` addon steps (existing types). The server doesn't validate at launch (D8). |
| Transparent fees | Show service, delivery and small-order fees on the review screen **before** Pay, with a short explanation of each. |
| Receipts | Order page receipt view. The Stripe email receipt if an email is collected [A]. |
| Support ownership | [B] Who answers "where's my order?": the restaurant (phone on page) or Ordelo ops? Proposal: restaurant for food issues, Ordelo ops (overwatch) for payment and delivery. Put an Ordelo support email on the page. |
| Terms | Customer terms naming the seller (restaurant) and platform (Ordelo), and the cancellation/refund policy (D14). |

### 17.2 Later enhancements (not at launch)

Accounts and saved addresses, reordering, scheduled orders, promotions and marketing consent, server-side pricing/offers (D8), self-cancel (D14), multi-town restaurants from the DB (D18), SSE, rider ETA, ratings and reviews, Apple Pay/Google Pay tuning (Stripe handles it).

---

## 18. Release plan (dependency-driven, reversible)

Principle: **the UI prototype ships first, but only against fixtures.** No production web order is possible until R1a and R1b are live and the R2 payment-path checks pass. Every release is additive and has an independent rollback.

```
R0 (FE fixtures) ─────────────────────────────┐
R1a (Ordelo payment/order foundation) ──► R2 (payment-path check) ──► R3 (web live, 1 restaurant)
          └──► R1b (customer notifier) ─────────────────────────────┘ ──► R4 (WA hand-off) ──► R5 (later)
```

### R0: Web UI prototype on fixtures (restaurant-frontend only)

- **Changes:**
  - `app/(web)/…` pages (§8).
  - `lib/web/fixtures/*.json` scenarios: eligible, out-of-range, closed, pricing-down, each order status, status-only view.
  - `lib/web/api.ts` with a `fixtures | live` switch (`NEXT_PUBLIC_WEB_ORDERING_MODE`).
  - `TOWNS` registry + `slug`, `towns[]`, `contactPhone`, `webOrderingEnabled` on `RestaurantConfig`.
  - Basket persistence.
- **No** Ordelo calls, **no** `/api/web/*` → Ordelo proxying yet (routes return fixtures).
- **Deploy:** Amplify preview branch, whole site `noindex`, basic auth.
- **Acceptance:** every §7.3 status renders; Lighthouse mobile a11y ≥ 90; 360 px layouts; WhatsApp routes (`/restaurant/[id]` with params) behave identically (manual smoke).
- **Rollback:** delete the preview branch. Nothing in prod changes.
- **Guardrails if R0 is merged to the production branch before R3** (so it stays zero-impact):
  - `app/page.tsx` (today's home) and a new `(web)` root page both resolve to `/`. Keep the landing under `/town` until R3, or keep the old home page.
  - `MenuContainer`/`BasketDrawer`/`CartContext` are not modified (§8.1).
  - The web flag defaults to off when absent. `amplify.yml` only copies whitelisted variables into `.env.production`.
  - Preview-only `noindex` comes from preview config, never from shared code.

### R1a: Ordelo payment and order foundation (behaviour-preserving for WhatsApp)

- **SQL (run manually, D31):** `ordelo_datamodels/migrations/ordelo_agg_r1.sql`, sections 001–002 and the R1a RPCs/job. Section 003 (R1b tables) may be run at the same time; nothing reads it until R1b.
- **Code:**
  1. M1 `order_reference`: unchanged output for recipients ending in four digits (unit test for equality with `create_order_reference`); random four letters from a 23-letter unambiguous alphabet for W-ids, with a retry on `order_id` collision (max 3).
  2. F3 fix (check `success` before `from_order_id`).
  3. F4: `create_food_order_with_items(p_order jsonb, p_items jsonb)` RPC does both inserts in one transaction. Used when `ORDER_CREATE_RPC_ENABLED` is on; the compensating path stays as the fallback.
  4. `create_order_with_items` and `CreateOrderRequest` take optional `origin_channel` (`whatsapp`|`web`, default `whatsapp`) and `storefront` (`direct`|`ordelo`, default `direct`). They're only written when not the default, so WhatsApp inserts are byte-identical and work before the SQL runs (D29).
  5. M2 inbox, used when `PAYMENT_INBOX_ENABLED` is on (off → today's path, plus the D27 web skip). Ignores event types other than `checkout.session.completed`. Event id = Stripe's `id`, else `authorised:<order_id>`. Outcomes: `applied` (init + restaurant app for WhatsApp), `duplicate` and `rejected_state` (no side effects), `unknown_order` (logged). Always 200, so Stripe stops retrying. No signature check (D23); no late-payment guard (Q17, R3).
  6. `payment-complete-test` only works when `ENABLE_PAYMENT_TEST_ROUTES` is on; when it is, it goes through the same M2 path.
  7. `capture-address` skips the restaurant-app `order-address-update` hook for a W-id (moved from R3, D29).
  8. Init reconciler, **alert-only**: a SQL job finds `requires_capture` orders older than 2 min with no summary row, created after `PAYMENT_INIT_RECONCILER_SINCE`, and posts them to `/payment-hooks/init-reconciler`, which alerts overwatch once per order.
  9. All new Supabase REST calls wrapped in `asyncio.to_thread`.
- **Flags** (`ordelo_config` keys, read with a 60 s cache; a missing key means off): `ORDER_CREATE_RPC_ENABLED`, `PAYMENT_INBOX_ENABLED`, `ENABLE_PAYMENT_TEST_ROUTES`. Reconciler: `PAYMENT_INIT_RECONCILER_SINCE` (timestamp) and the pg_cron schedule.
- **restaurant-agents:** no change (D23).
- **Pre-deploy check:** run the SQL and flip flags outside service hours, after confirming no order is mid-fulfilment:
  ```sql
  SELECT order_number FROM delivery_summary WHERE status NOT IN ('completed','timedout')
  UNION ALL
  SELECT order_number FROM takeaway_summary WHERE status NOT IN ('completed','declined')
  UNION ALL
  SELECT order_number FROM food_order WHERE payment_status = 'requires_payment' AND order_dt = CURRENT_DATE;
  ```
  Expect no rows, apart from test and abandoned orders you recognise.
- **Payment inbox compatibility [V]:** restaurant-agents `/paid3100` (`on_message_graph_handler.py` ~L203) posts `{"data":{"object":{"metadata":{"orderID":…}}}}` with **no event `id`**. Stripe's own events always carry one. M2 therefore uses `provider_event_id = id` when present and otherwise `authorised:<order_id>`, so events without an id are still accepted and de-duplicated per order.
- **Acceptance:**
  - Replaying a `payment-complete` payload 3× gives one init and one restaurant notification.
  - A non-`checkout.session.completed` event returns 200 and changes nothing.
  - On the test restaurant: WhatsApp delivery + takeaway + pay-at-restaurant end-to-end with identical customer messages, with each flag on.
  - `ORDER_CREATE_RPC_ENABLED` on: an order-item failure leaves no `food_order` row.
- **Monitoring:** `payment_event` kinds per hour; reconciler alerts.
- **Rollback:** turn the flag off (no redeploy), or redeploy the previous image. The SQL is additive.
- **Guardrails** (kept from 2026-09-30):
  1. Init reconciler in **alert-only** mode, scoped to orders created after `PAYMENT_INIT_RECONCILER_SINCE`.
  2. No signature check (D23), so restaurant-agents `/paid3100` needs no change.
  3. Confirm nobody uses `/payment-complete-test` manually before deploying (it is off unless `ENABLE_PAYMENT_TEST_ROUTES` is set).
  4. Release notes: replayed payment webhooks no longer re-send receipts.
  5. Run the SQL first, then deploy code with all flags off, then enable one flag at a time on the test restaurant.
  - [V] Both `FoodOrder` models use pydantic's default `extra='ignore'`, so the new `food_order` columns don't break `select("*")` or the restaurant-agents payload. restaurant-agents `delivery.py` compares `payment_status == 'requires_capture'`, which is why no new status values are added.

### R1a addendum: test payments on request (D32)

- **SQL (run manually):** `ordelo_datamodels/migrations/ordelo_agg_r1_test_payment.sql`: `food_order.payment_mode TEXT NULL CHECK (payment_mode IN ('live','test'))` and `create_food_order_with_items` writing it. `NULL` = decided by today's rule.
- **Ordelo:** `CreateOrderRequest.test_payment` (default false). `test_payment_allowed(recipient, rest_ref)`: overwatch recipient **or** `rest_ref` in `TEST_PAYMENT_REST_REFS` (comma-separated, 60 s cache). Honoured → `payment_mode='test'` is written at insert; refused → order stays live and a warning is logged. `FoodOrder.payment_uri` uses the test service when `payment_mode='test'` **or** today's overwatch + delivery rule. `create-order` returns `payment_mode` (`test`/`live`). `payment_mode` is excluded from the `FoodOrder` payload sent to restaurant apps (byte-identical).
- **Front end:** `/restaurant/[id]?…&isTest3100=true` → `BasketDrawer` → `/api/checkout` forwards `test_payment: true`; the order summary shows a "Test payment" label only when Ordelo answers `payment_mode: "test"`. Ordelo web page: `?isTest3100=true` on any web page is remembered for the browser tab (`isTest3100=false` clears it); `/api/web/orders` passes `test_payment` (fixtures mimic Ordelo with `bnat` as the test restaurant; live mode in R3).
- **Before use:** run the SQL, then `INSERT INTO ordelo_config (config_key, config_value) VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT');`.
- **Status (2026-10-01):** implemented, uncommitted. Ordelo: `utils_common/payment_ms/payment_mode.py`, `config/feature_flags.py` (`config_csv`), `FoodOrder.payment_mode`/`uses_test_payment`, `order_hooks.create_order`, `order_service`; tests pass (one pre-existing failure). SQL checked twice on scratch Postgres 16. Front end: `lib/testPayment.ts`, `BasketDrawer`, `/api/checkout`, order summary, `/api/web/orders`, fixtures, `CheckoutFlow`, `OrdeloMenuContainer`; `tsc` and lint clean.

### R1b: Customer notifier (needed by R3, not by R2)

- **SQL:** section 003 of `ordelo_agg_r1.sql` (subscriptions, customer events, outbox).
- **Code:**
  1. M3 notifier with **Adapter A** (restaurant app) replacing the 10 call sites, and **Adapter B** (web page, no-op). The existing `get_restaurant_webhook_url_async` paths and payloads stay byte-identical.
  2. `create_order_with_items` creates the `whatsapp_restaurant` subscription for WhatsApp orders and `web_page` for web orders.
  3. M2's web branch publishes `payment_authorised`.
- **Flag:** `CUSTOMER_NOTIFIER_ENABLED` (off → legacy direct calls retained in code for one release).
- **Compatibility:** any WhatsApp order without a subscription is routed to its restaurant app by the notifier fallback (replaces a backfill).
- **Acceptance:** characterisation tests record the URL and body for each of the 10 hooks before and after, and they're identical; outbox retry when a target is down (T8).
- **Rollback:** `CUSTOMER_NOTIFIER_ENABLED=false`.
- **Guardrails:** restaurant-app adapter **retries = 0** (record the outcome only); notifier falls back to the restaurant app for any WhatsApp order with no subscription; enable on the test restaurant first.

### R2: Payment-path check (no payment-service change, D22)

- **Changes:** none in the payment service; nothing to deploy.
- **Prerequisites:** R1a deployed with `PAYMENT_INBOX_ENABLED` on in the test environment.
- **Checks** (Stripe test mode: `stripe_url_test`, or `bnat`, which runs on the test key [V]):
  1. Create a web-style order (D29): `SELECT create_thread('WEB', NULL)` for the web thread; `POST /order-hooks/capture-address` with a W-id `recipient` (e.g. `W7K2M9QX4TPA`; no restaurant-app call); then `POST /order-hooks/create-order/{rest_ref}` with that W-id, the `WEB-…` thread, `"origin_channel":"web"` and `"storefront":"ordelo"`. It returns a Checkout URL from the existing payment endpoint.
  2. Paying it delivers `checkout.session.completed` to **both** the payment service (PaymentIntent saved in `payment_details`) and Ordelo `payment-complete`. Record, for every Stripe account in use, the Ordelo endpoint URL and its subscribed events from the Stripe dashboard (§21, assumption 1).
  3. Ordelo applies the event once, takes the web branch (no restaurant-app call, D27), and a replay is a no-op.
  4. Capture on rider acceptance and cancel on no-rider both work for the W-id order.
  5. Record where Stripe sends the browser (expected: the restaurant's fixed URL, §13.1).
- **Acceptance:** all five checks pass and are written up in the release notes.
- **Rollback:** nothing to roll back.

### R3: Web ordering live (flagged: one town, one restaurant, then widen)

- **Entry gate (deferred from R0, D34).** restaurant-frontend, web code only. **Items 1–5 fixed 2026-10-01** (uncommitted on `dev`; `tsc` and lint clean; logic checked with a throwaway script). Item 6 is still open.
  1. ✅ Restaurant-switch confirmation is skipped: `PersistedCart.tsx` saves the new basket before `OrdeloMenuContainer.tsx` checks for another active basket. Capture the previous restaurant first; clear storage only after the user chooses. *Fix:* `lib/storefront/basket.ts` `otherActiveBasket` scans stored baskets instead of trusting the active pointer; "Start new basket" calls the new `clearOtherBaskets`.
  2. ✅ Checkout drops the Ordelo voucher: `CheckoutFlow.tsx` calls `resolveOffers` without the stored `ordelo_web_voucher:{id}`. Dormant until a restaurant has `ordeloOffers` (Q13). *Fix:* `readStoredVoucher`/`storeVoucher` in `lib/storefront/offers.ts`, used by both the menu page and checkout. Needs a browser check once Q13 configures a voucher.
  3. ✅ Receipt keeps only 20 basket lines while 50 are accepted (`lib/web/fixtures/index.ts`). Fixture code, but the live R3 order/receipt must keep every accepted line or reject larger baskets (mind cookie size). *Fix:* `MAX_ORDER_LINES = 20` in `lib/web/types.ts`; more lines, or a snapshot cookie over 3,800 chars, gets `422 basket_too_large` (checkout also checks before submitting); the receipt keeps every line. **R3: Ordelo `/web/orders` must enforce the same limit (or a higher one it stores in full).**
  4. ✅ Capture wording: `CheckoutFlow.tsx` and `lib/web/status.ts` say the card is charged when a rider picks up; it is when the rider accepts. The review page also says "authorised now" before payment.
  5. ✅ Stale D24 copy: the review screen and the fixture pay page say name and phone are collected. *Not changed (depends on Q14):* the order-lookup copy that still mentions a phone number, in `app/(web)/orders/find/page.tsx`, `app/(web)/town/[town]/orders/[orderNumber]/page.tsx` and `components/ordelo/PaymentReturn.tsx`.
  6. Lighthouse mobile accessibility ≥ 90 (R0 acceptance, not yet measured).
- **Migrations:** §6.2 (004, 005, 007; 006 removed); `job_close_thread` filter.
- **Ordelo:**
  - M4, M5, M6.
  - `/web/*` router with `X-Ordelo-Web-Key`.
  - M2 web branch: skip the restaurant app (D27), publish `payment_authorised`, apply the late-payment guard (Q17).
  - `rider_agent.py:send_customer_contact`: for a `customer_id` that isn't a phone number, send no contact card and tell the rider no number is on file (D24, Q16).
  - M6 uses manual-capture calls only (D25) and rejects any `rest_ref` the payment service doesn't know (F13).
  - The takeaway-decline direct WhatsApp send goes through the notifier (skip for web).
  - `customer_hooks.update_address` skipped for W-ids (`capture-address` already skips them from R1a, D29).
  - Availability/pause checks; eligibility typed result.
  - Abandoned-checkout sweep (web threads inactive after 2 h).
  - Web test-mode switch: `food_order` from a restaurant listed in `ordelo_config.WEB_TEST_REST_REFS` uses `stripe_url_test` (replaces the overwatch-recipient trick for web).
- **Frontend:** `/api/web/*` live proxies; cookies; log redaction (F9); `robots.txt`/sitemap; legal pages; the price-floor monitor job (D8).
- **Flags:**
  - `webOrderingEnabled` per restaurant (config) **and** `WEB_ORDERING_ENABLED_REST_REFS` in `ordelo_config` (server-side kill switch checked in `/web/checkout-sessions` and `/web/orders`).
  - `WEB_WHATSAPP_CTA_ENABLED=false`.
- **Acceptance (test restaurant, Stripe test mode, then one live restaurant):** the §19 matrix rows marked R3 pass. The restaurant receives the web order on existing WhatsApp admin flows exactly as for WhatsApp orders. The rider is told no customer number is on file. The order page shows each stage.
- **Monitoring:** §20 dashboards live before the first real order.
- **Rollback:** flip the server kill switch (new web checkouts get 503 "Online ordering is paused, call the restaurant"). **In-flight web orders keep fulfilling**, because fulfilment doesn't depend on web code; order pages keep working. Frontend rollback is an Amplify redeploy.

### R4: WhatsApp hand-off (ordelo_agg)

- **Prerequisites:** the new WABA number (D3); approved utility templates (§14.1); the restaurant-agents ADR for a non-restaurant app identity [B].
- **restaurant-agents:** `apps/ordelo_agg` (identity, prompts, app-owned GraphAdapter with read-only tools); `/order-event-hooks/ORDELO/customer-event` route; composition test.
- **Ordelo:** Adapter C; `/web/orders/{n}/handoff-codes`; `/web/whatsapp-bind`; migration 008; STOP handling.
- **Frontend:** CTA on the order page (`WEB_WHATSAPP_CTA_ENABLED`); the return page is deferred (D26). If `ordelo-agg-agent` ordering is in scope (D20), add `WhatsAppLinkSession` to the Ordelo page (signed short-lived menu-link token; resolves to the agent's WhatsApp thread and the customer phone) and ship the agent's `send_menu_link` tool.
- **Acceptance:** §19 hand-off rows; an event outside the 24 h window is delivered via template.
- **Rollback:** disable the CTA flag. Existing subscriptions are deactivated by a script, and Adapter C is skipped when `ORDELO_AGG_ENABLED=false`. Web tracking is unaffected.

### R5: Later

**Restaurant-specific UI decision (D21, §8.1):** converge `/restaurant/[id]` onto the shared shell or keep it separate with extracted shared blocks. Retire the time-boxed container duplication either way.

**Post-payment redirect for web (D26, §13.1):** pick one of the three options; option 1 is recommended.

**Payment-service hardening (separate track, F11–F12):** verify Stripe signatures in its webhook; enforce Ordelo's service token (after checking API Gateway).

Server-side pricing from `*_menu` + offers/vouchers in the DB (D8); a quote object with expiry; self-cancel before acceptance (D14); towns and storefront in the DB (D18); checkout_ref + payment path without thread_id (§4); random order refs for WhatsApp too (removes the phone-digit leak); accounts; scheduled orders; SSE; fix F8 before enabling delivery decline.

---

## 19. Test matrix

Unit and integration tests use pytest + pytest-asyncio (Ordelo, restaurant-agents), with mocks per CLAUDE.md. Frontend has no framework: add Playwright for the web flows (the container has Chromium [A: CI support]).

| # | Scenario | Channel | Mode | Expected | Phase |
|---|---|---|---|---|---|
| T1 | Happy path | WA | delivery | Messages identical to baseline; one subscription `whatsapp_restaurant` | R1 |
| T2 | Happy path | WA | takeaway online + pay-at-rest | Unchanged; capture at pickup boundary | R1 |
| T3 | Order ref for 12-digit recipient | WA | — | Equals legacy `create_order_reference` | R1 |
| T4 | Order ref for W-id / collision | web | — | Random ref; unique-violation retry succeeds | R1 |
| T5 | payment-complete ×3 same evt | both | both | 1 init, 1 notify, 2 `duplicate` | R1 |
| T6 | payment-complete for captured order | both | both | 0 rows; `rejected_state`; alert | R1 |
| T7 | Event without an `id` (the `/paid3100` shape) | both | both | Accepted once; de-duplicated per order (`authorised:<order_id>`) | R1 |
| T8 | Notifier target down | WA | delivery | Outbox retries; order still dispatches and captures | R1 |
| T9 | Init failure after authorisation | both | delivery | Reconciler inits within 2 min; alert | R1 |
| T10 | Web happy path | web | delivery | Order page stages; rider told no number is on file; restaurant admin flow unchanged; no restaurant-app call | R3 |
| T11 | Web happy path | web | collection | "Waiting for restaurant" → pickup time → updated time → ready | R3 |
| T12 | Postcode out of range / pricing down | web | delivery | `out_of_range` vs `unavailable` distinct messages | R3 |
| T13 | Address changed after estimate | web | delivery | Fee change highlighted; explicit confirm; new order | R3 |
| T14 | Mode switched in basket | web | both | Discount re-applied from config; old order dropped | R3 |
| T15 | Double click / two tabs same basket | web | both | Same order and URL (Idempotency-Key) | R3 |
| T16 | Two different baskets paid | web | both | Two orders (legit); soft duplicate warning shown | R3 |
| T17 | Browser closed after paying | web | both | Webhook completes order; return via `/o/{token}` works | R3 |
| T18 | Stripe redirect for a web order | web | both | Lands on the restaurant's fixed URL (D26); the order page via the saved link shows the right state | R3 |
| T19 | Checkout expired / cancelled | web | both | Order stays `requires_payment`; page "Payment not completed"; basket resumable | R3 |
| T20 | Restaurant closed / cutoff / paused | web | both | 422 with next-open; UI blocks checkout | R3 |
| T21 | Below minimum (server) | web | delivery | 422 `below_minimum` | R3 |
| T22 | Takeaway decline | web | collection | Auth cancelled; `restaurant_declined` + `payment_released` on page; no WA send to W-id | R3 |
| T23 | No rider found | web | delivery | `no_rider_found`; released; page wording | R3 |
| T24 | Order number only, no token | web | — | 401/lookup form; no PII | R3 |
| T25 | Lookup wrong second factor ×6 (only if Q14 keeps a fallback) | web | — | Uniform 404 then rate-limited | R3 |
| T26 | Token for order A used on order B | web | — | 403 | R3 |
| T27 | Status-only view | web | — | No address/code/items/charges | R3 |
| T28 | Logs/analytics contain no phone/token/postcode | web | — | Grep of Amplify + Ordelo logs clean | R3 |
| T29 | `job_close_thread` ignores WEB threads | — | — | No WA send to NULL recipient | R3 |
| T30 | Kill switch on with orders in flight | web | both | New checkout 503; in-flight complete; pages work | R3 |
| T31 | Hand-off with a valid code | web→WA | both | Detail level per Q15; catch-up summary | R4 |
| T32 | Hand-off code used by someone else (forwarded) | web→WA | both | Detail level per Q15 | R4 |
| T33 | Code reused / expired / forwarded unused | web→WA | — | 410 / 410 / binds forwardee at the Q15 level | R4 |
| T34 | Same sender, second order | web→WA | — | Two subscriptions; agent disambiguates | R4 |
| T35 | Event after 24 h window | web→WA | — | Utility template sent | R4 |
| T36 | Agent down during events | web→WA | — | Outbox retry; page unaffected | R4 |
| T37 | STOP | web→WA | — | Subscriptions deactivated | R4 |
| T38 | Web order is still `origin_channel='web'` after hand-off | — | — | Immutable trigger holds | R4 |
| T39 | Web payment after the late-payment cut-off (Q17) | web | both | No init; authorisation cancelled (retried until the payment service has stored it); page shows payment released | R3 |
| T40 | Rider asks for the customer's contact on a web order | web | delivery | "No number on file" reply; no contact card carrying the W-id | R3 |
| T41 | Web create-order for a `rest_ref` the payment service doesn't know | web | both | 422; the payment service is never called (F13) | R3 |
| T42 | Web payment-complete never calls a restaurant app | web | both | No request to `order-payment-complete/{recipient}/{thread_id}` (D27) | R3 |

---

## 20. Monitoring

**Funnel** (privacy-safe analytics events: `rest_ref`, `mode`, `town`, visitor hash): `landing_postcode_submitted` → `eligibility_shown{deliverable_count}` → `menu_viewed` → `basket_add` → `checkout_started` (web thread) → `address_submitted` → `order_created` → `stripe_redirected` → `payment_authorised` (server) → `order_completed`. Conversion per step, per restaurant and per mode. **Sessions = web threads + visitors** (`web_session_meta`).

**Reconciliation SQL** (pg_cron every 5 min → ops WhatsApp/overwatch, reusing `notify_overwatch` [V]):

| Check | Condition | Meaning |
|---|---|---|
| M-1 | `payment_event.kind='authorised'` exists AND order still `requires_payment` > 2 min | Webhook applied but update failed |
| M-2 | `requires_capture` AND no summary row > 2 min | Init failed (reconciler also retries) |
| M-3 | `payment_event.kind = 'rejected_state'` | Double authorisation or out-of-order event |
| M-4 | `capture_failed`, `cancel_failed` | ADR-0002 reconciliation |
| M-5 | Web order `requires_payment` with a Stripe PaymentIntent succeeded (payment-service side query) | Missed webhook |
| M-6 | Summary `restaurant_unconfirmed` past timeout + 5 min | Confirmation job stalled |
| M-7 | Outbox `failed` or pending > 15 min | Notification failures |
| M-8 | Price-floor monitor (D8) | Possible tampered prices |
| M-9 | `delivered` missing at `pickup_time + 90 min` | Fulfilment failure |

**Service health:** Ordelo `/web/*` latency and error rate; pricing `unavailable` rate; payment-service create failures; order-page poll error rate; WhatsApp template send failures (R4).

---

## 21. Assumptions, blocking decisions and unresolved questions

**Assumptions [A]:**

1. Stripe calls Ordelo's `payment-complete` directly, through a webhook endpoint registered on each Stripe account in use (the payment service never forwards to Ordelo [V]). Confirm in the Stripe dashboard during R2.
2. The pricing service's out-of-range signal needs confirming. Today the helper returns `-1` for failures and `None`/missing car options [V].
3. Menu service and `{rest}_menu` tables: shape not inspected beyond notebooks (price stored as text).
4. `thread` is one table shared by OrdeloAgent and restaurant-agents in the same Supabase project, and `job_close_thread` may still be scheduled.
5. Who sets `takeaway_summary.status='completed'` wasn't traced.
6. Stripe emails receipts only if an email is collected.
7. The UK card-authorisation release time varies by issuer.

**Blocking decisions and open questions [B]:**

| # | Question | Blocks | Proposed default |
|---|---|---|---|
| Q1 | restaurant-agents identity invariant for a non-restaurant app (`ordelo_agg`): new ADR or `rest_ref="ORDELO"`? | R4 | ADR: introduce `ServiceIdentity` for platform apps |
| Q2 | Retention periods for W-id customer rows, meta and lookup logs; lawful basis; cookie banner | R3 | §16 proposal |
| Q3 | Support ownership and support contact on the order page | R3 | Restaurant for food; Ordelo ops for payment and delivery |
| Q4 | Allergen information obligations for web distance selling; do we need per-item allergen data? | R3 | Notice + call-restaurant at launch; confirm with the FSA |
| Q5 | Server-side minimum-spend check on web only while WhatsApp stays client-side? | R3 | Yes (web only) |
| Q6 | Marketing consent for the Ordelo brand (not per restaurant) | Later | Not at launch |
| Q7 | ~~Mismatched-phone upgrade path (partner vs typo)~~ **Superseded by Q15** (no phone collected, D24) | — | — |
| Q8 | Legacy unauthenticated Ordelo routes (`/order-hooks/*`, debug, `payment-complete-test`): lock down scope and timing | R3 hardening | Shared-secret header on all frontend→Ordelo routes in R3; debug routes behind env flag |
| Q9 | Sold-out between menu load and payment | Later | Restaurant calls the customer; pricing/stock server check in R5 |
| Q10 | Delivery decline (F8) before it's ever enabled | Before enabling decline | Fix to cancel + `timedout`-style path |
| Q11 | ~~Add `food_order.storefront` (`direct`/`ordelo`) now?~~ **Answered yes (D28).** | — | — |
| Q12 | Restaurant-specific UI: converge or stay different (D21) | R5 | Decide when the first trigger in §8.1 occurs |
| Q13 | Initial `ordeloOffers` per restaurant (none vs mirror direct offers) | R3 | None until each restaurant agrees Ordelo terms |
| Q14 | Lookup fallback without a phone (D6, D24): drop it at launch, or use another second factor (e.g. the delivery postcode)? | R3 | Drop at launch; secret link + cookie only |
| Q15 | WhatsApp hand-off detail level with no collected phone to match (D16, D24) | R4 | `full` for a valid code, because codes are only issued from a full-access order page |
| Q16 | What a rider does when a web customer can't be found and there is no number on file | R3 | Rider follows the delivery instructions in the notes, then escalates through the existing ops path |
| Q17 | Late-payment cut-off for web (sessions stay payable for 24 h, D22) | R3 | Cancel the authorisation when paid > 35 min after order creation or after the restaurant has closed |

---

## 22. Implementation checklist (for a coding agent)

Work one release at a time. Don't start R3 code paths that create real orders before R1a, R1b and R2 acceptance.

**R0: restaurant-frontend**

- [ ] Add `TOWNS` + `slug`, `towns`, `contactPhone`, `webOrderingEnabled`, `previousSlugs` to `config/restaurants.ts` (types + data).
- [ ] `app/(web)/page.tsx` landing with postcode gate; `town/[town]/page.tsx`; `town/[town]/[rest]/page.tsx` as the Ordelo storefront shell: new `OrdeloMenuContainer` composing the existing leaf components, with `MenuContainer`/`BasketDrawer` **not modified** (§8.1); `checkout/page.tsx`; `checkout/return/page.tsx`; `town/[town]/orders/[orderNumber]/page.tsx`; `orders/find/page.tsx`; `o/[token]/route.ts`.
- [ ] `lib/web/api.ts` (fixtures | live) + `lib/web/fixtures/*`.
- [ ] Basket persistence in `contexts/CartContext.tsx` (web mode only; try/catch around storage).
- [ ] `OrdeloBasket` (new) + `lib/storefront/session.ts` (`WebCookieSession`) + `lib/storefront/offers.ts` (`resolveOffers`, reading `ordeloOffers` only); goes to `/checkout`. `BasketDrawer` is untouched.
- [ ] Shared `OrderTimeline`, `StatusHeader` and `RestaurantHelpCard` components (redacted view models only).

**R1a: OrdeloAgent** (no restaurant-agents change). Code and SQL written 2026-10-01 (uncommitted on `release/ordelo-agg`); not yet deployed.

- [x] `ordelo_datamodels/migrations/ordelo_agg_r1.sql` (001–003, RPCs, reconciler); owner runs it manually (D31). Checked on a scratch Postgres 16: runs twice cleanly; RPC outcomes and rollback verified.
- [x] `config/feature_flags.py`: `ordelo_config` flags with a 60 s cache; missing key = off.
- [x] `utils_common/order_management/order_reference.py` (M1) and `customer_keys.py` (W-id helpers) + tests; called from `order_service.create_order_with_items`.
- [x] `create_order_with_items` + `CreateOrderRequest`: optional `origin_channel` / `storefront` (D29); RPC `create_food_order_with_items` behind `ORDER_CREATE_RPC_ENABLED`; F3 fixed in `order_hooks.create_order`.
- [x] `utils_common/payment_ms/payment_events.py` (M2, behind `PAYMENT_INBOX_ENABLED`); `payment_hooks.payment_complete_path` delegates; web orders skip the restaurant app (D27); `payment_complete_test_path` gated (`ENABLE_PAYMENT_TEST_ROUTES`).
- [x] `order_hooks.capture_address` skips the restaurant-app hook for W-ids.
- [x] Init reconciler: SQL job `job_payment_init_reconciler()` + `/payment-hooks/init-reconciler` (alert-only; alerts once per order via `payment_event` kind `init_reconcile_alerted`).
- [ ] **Schedule the reconciler (pg_cron) — deferred by the owner (D33).** Production Ordelo serves `/payment-hooks/init-reconciler` and `ORDELO_APP_URL` points at it, so it can be scheduled whenever wanted.
- [x] **Go-live (2026-10-01):** deployed to production; real paid WhatsApp order, overwatch test-payment takeaway, and full WhatsApp takeaway and pay-at-restaurant runs verified by the owner.
- [x] SQL run by the owner (2026-10-01); flags `PAYMENT_INBOX_ENABLED` and `ORDER_CREATE_RPC_ENABLED` on in the test environment (`rider-agent-test.ordelo.app`).
- [x] Endpoint verification on the test environment (2026-10-01, BNAT, W-id `WVERIFYTEST1`, cleaned up): 15/15 checks passed, covering web-style create-order on both insert paths, the once-only outcomes (applied, duplicate, rejected_state, unknown_order, ignored, invalid), the test-route gate, today's path with the inbox off, and the reconciler job end to end (Supabase → `/payment-hooks/init-reconciler` → overwatch WhatsApp). Server logs confirm the restaurant-app call is skipped for web orders on both paths.
- [x] **R1a declared complete by the owner (2026-10-01)** on the strength of the SQL run and the endpoint verification above. A full WhatsApp delivery/takeaway/pay-at-restaurant run with the flags on was not part of that verification; do one before the production rollout.

**R1b: OrdeloAgent**

- [ ] `utils_common/notify/customer_notifier.py` (M3) with `RestaurantAppWebhookAdapter`, `WebPageAdapter`; outbox dispatcher + pg_cron sweep; replace the 10 call sites listed in §2.2. Notifier fallback for WhatsApp orders without a subscription.
- [ ] Characterisation tests for those 10 payloads (before/after).
- [ ] Subscriptions created in `create_order_with_items`; M2 web branch publishes `payment_authorised`.

**R2: payment-path check** (no payment-service change; run the §18 R2 checks).

**R3: OrdeloAgent + restaurant-frontend**

- [x] Entry gate from R0 (D34), items 1–5: fixed 2026-10-01 (restaurant-frontend `dev`, uncommitted).
- [ ] Entry gate item 6: Lighthouse mobile accessibility ≥ 90.
- [ ] Order-lookup copy that mentions a phone number (after Q14).
- [ ] Ordelo `/web/orders` enforces `MAX_ORDER_LINES` (20) or a higher limit stored in full.
- [ ] Migrations 004, 005, 007; `job_close_thread.sql` filter; admin views `origin_channel`.
- [ ] M4 `order_access.py`, M5 `customer_order_view.py`, M6 `web_checkout.py`; `watomation/routers/web_hooks.py` registered in `fapp_ordelo_agent.py`.
- [ ] M2 web branch: skip the restaurant app (D27), publish to the notifier, late-payment guard (Q17).
- [ ] `ordelo/agents/rider_agent.py:send_customer_contact`: no contact card for a non-phone `customer_id`; tell the rider no number is on file.
- [ ] M6: manual-capture calls only (D25); reject `rest_ref`s the payment service doesn't know (F13).
- [ ] `takeaway_hooks._handle_restaurant_decline` → notifier; `order_hooks.capture_address` + `customer_hooks.update_address` skip W-ids.
- [ ] Availability evaluator (service hours + cutoff + pause keys); typed eligibility helper.
- [ ] Abandoned web-thread sweep; web test-mode switch in `FoodOrder.payment_uri`.
- [ ] Frontend: `/api/web/*` routes with `X-Ordelo-Web-Key`; cookies; redact logging in `middleware.ts` and `app/api/menu/route.ts`; `robots.txt`, sitemap, legal pages.
- [ ] Monitoring jobs M-1…M-9; price-floor monitor.

**R4: restaurant-agents + OrdeloAgent + frontend** (§14, §18).

**Docs:** done 2026-10-01: OrdeloAgent `CONTEXT.md` (web ordering terms), `docs/adr/0003-web-orders-never-reach-restaurant-apps.md`, `0004-web-payments-use-existing-payment-service-contract.md`, `0005-web-orders-use-synthetic-keys-and-no-contact.md`. Still to do when implementing: restaurant-agents glossary/domain model and ADR for `ordelo_agg` (R4); `docs/ordelo-restaurant-frontend-agents.md` endpoint catalogue.
