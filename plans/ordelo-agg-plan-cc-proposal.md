# Ordelo web ordering and WhatsApp coexistence — separate proposal

Prepared: 30 September 2026. Source inspection: 29–30 September 2026. Status: proposed, planning only. No application, database, deployment, payment, or WhatsApp state was changed during this investigation.

**Destination confirmed:** `/Users/basavaraj/bloop/OrdeloAgent/plans/ordelo-agg-plan-cc-proposal.md`. On 30 September 2026, the owner requested a separate proposal. The existing `ordelo-agg-plan-cc.md` and `ordelo_agg_plan_cc_decision_log.md` are preserved. This proposal does not supersede their recorded choices; conflicting recommendations remain alternatives requiring a later decision.

## 1. Recommended design

Build web ordering as another adapter to the same persisted FoodOrder and Ordelo fulfilment workflow. Give web guests a browser session, a restaurant-scoped checkout session, an authoritative quote, and secure order access. A conversation is optional. The payment and fulfilment implementation must progress when no customer WhatsApp thread exists.

Use `/town/{town_slug}` for discovery. At the restaurant menu, show a persistent **Delivery / Collection** selector. Allow browsing before selecting either, but require a mode before displaying mode-specific offers or creating a payable quote. Delivery postcode provides an early estimate; capture the complete address before the final quote and payment. Collection requires no delivery address.

Keep immutable `origin_channel` on **food_order**. Keep fulfilment mode separately, and keep mutable notification subscriptions in their own order-scoped records. A web-originated order remains web-originated when WhatsApp is added.

Introduce checkout identity explicitly. Temporarily pass an opaque checkout compatibility ID as legacy `thread_id` to payment-service; do not insert it into the conversation `thread` table. The inspected payment implementation uses that value as metadata and does not read a conversation. Move new payment contracts to order/payment-attempt IDs, then make actual conversation linkage nullable and separate.

Launch the public UI first only as a fixture-backed prototype or browse-only experience. Real checkout depends on backend security, quotes, durable payment processing, secure tracking, rejection/refund behavior, and order-scoped address snapshots. Web ordering can then launch before `ordelo-agg-agent`; restaurant admins and riders may continue their existing WhatsApp workflows.

### Decision register

| Decision | Recommended approach and rationale | Relevant alternative / tradeoff | Affected implementation; dependency |
|---|---|---|---|
| Discovery | Town is discovery context; canonical restaurant identity is `rest_ref` | Town-exclusive restaurants would hide neighbouring service areas | Frontend routes/config; discovery catalogue and explicit mappings |
| Mode selection | Restaurant header before mode-specific prices, offers, and quotation; browsing allowed earlier | A compulsory town-level choice adds friction and may promise unsupported service | MenuContainer/BasketDrawer; shared availability and quote contract |
| Address timing | Postcode estimate early, complete address before payable quote | Full address before menu prevents wasted baskets but raises abandonment | New checkout address flow; premises lookup/manual validation |
| Order origin | `food_order.origin_channel` immutable; operational fulfilment and subscriptions separate | A single mutable `channel` conflates acquisition with communications | Additive migration and ingestion adapter |
| Customer identity | UUID guest subject/customer identity; phone is a contact/legacy bridge | Keep phone PK forever: easy today, difficult with changed/shared numbers and non-UK users | Customer migration and order snapshots; see §5 |
| Thread compatibility | Separate `checkout_session_id`; temporary metadata bridge, no conversation row | Synthetic active WA thread creates cron, retention, and graph side effects | Ordelo FoodOrder/payment adapter; v2 payment contract |
| Authority | Deep Order Processing module in Ordelo + transactional Postgres commands | Put rules in Next.js or LLM tools: duplicate invariants and unreliable progress | Payment/SQL/restaurant callbacks; preserve FoodOrder authority ADRs |
| Guest access | HttpOnly browser grant; recover through verified email code, optionally SMS | Order number in URL alone leaks private information | Customer access module; transactional email integration |
| Pricing | Server-derived quote using stable SKU/modifier IDs, integer pence and explicit rule version | Reuse client prices/minimum URL params: unsuitable for public checkout | Menu/pricing adapter contracts and immutable quote |
| Payment | Persist order before provider initiation, manual authorisation, existing capture milestones initially | Immediate capture simplifies flow but changes refund/fulfilment risk and existing ADR | payment-service, Ordelo inbox/outbox, reconciliation |
| Restaurant timeout | For new web orders: cancel/release unless explicit configured auto-accept | Preserve timeout auto-accept: only with deliberate merchant agreement and honest customer copy | Acceptance policy snapshot; owner decision pending |
| Collection time | Assign directly only under an explicit merchant acceptance/capacity policy; otherwise show estimate pending acceptance | Assign every collection a confirmed time without kitchen agreement: unreliable commitment | Existing acceptance-policy SQL; per-mode policy extension |
| Tracking transport | Authenticated polling initially, same persisted projection for web and WA | SSE/realtime later after transport, authentication, and scale validation | Dedicated customer DTO; frontend hosting constraints |
| WA adoption | Optional order-update opt-in after authorisation, with order page primary | Require WA at checkout: reduces reach and still does not establish marketing consent | Secure attach and independent notification delivery |
| Aggregator agent | Dedicated post-payment attachment into order-bound support/progress state | Replay checkout checkpoint: risks duplicate ordering and wrong current thread | Future app-owned graph adapter and approved runtime architecture |

## 2. Evidence, inspected scope, and limits

### 2.1 Source snapshot

Read the supplied Ordelo `agents.md`, frontend `AGENTS.md`, `docs/ordelo-restaurant-frontend-agents.md`, Ordelo `CONTEXT.md`, and both accepted Ordelo ADRs. Adjacent source repositories were available, so payment and Restaurant Agent contracts were inspected rather than treated as black boxes. Read restaurant-agents governing `AGENTS.md`, `CONSTITUTION.md`, domain model, glossary, and relevant ADRs. Applied the requested grill-me and improve-codebase-architecture skills; their architecture vocabulary informs the module/seam decisions below. The requested task already selects the scope, so no unrelated refactor or glossary mutation is proposed as work in this planning turn.

| Alias used in citations | Absolute repository | Inspected HEAD | Scope |
|---|---|---|---|
| O | `/Users/basavaraj/bloop/OrdeloAgent` | `7697e15` | Ordering, payment, SQL, restaurant/rider/takeaway hooks, location, customer and thread contracts |
| F | `/Users/basavaraj/bloop/restaurant-frontend` | `a75312e` | Customer ordering UI and server routes, restaurant configuration, addresses, portals/access |
| R | `/Users/basavaraj/bloop/restaurant-agents` | `eeb6a3c` | Shared customer Agent runtime, app identity, payment/order/rider callbacks and conversation lifecycle |
| P | `/Users/basavaraj/bloop/payment-service` | `58158ca` | Go payment request handling, Stripe authorisation/capture/cancel, return URLs, receipt and webhook implementation |

References such as `O:watomation/routers/payment_hooks.py:payment_complete_path` mean the named symbol in that repository; line numbers are navigational aids in this source snapshot. In R, `runtime/` below abbreviates `packages/restaurant-agent-runtime/src/restaurant_agent_runtime/`.

O already contains unrelated modified SQL/notebook files and untracked integration documentation. F was clean. Findings describe the current working files, including existing unrelated edits, and do not certify deployed production behavior. Preserve that work during implementation. Do not execute the historical SQL files as wholesale migrations: some contain DROP statements, ad-hoc queries, and obsolete definitions.

**Verified** means observed in inspected code/documentation; **recommended** means new design; **assumption** means a proposed working choice; **blocking verification** means evidence required before real checkout. No live DB introspection, provider calls, messages, deployments, builds, or application tests were run for this plan.

### 2.2 Existing end-to-end behavior

| Stage | Verified behavior | Source / symbol |
|---|---|---|
| Browse | Root lists frontend-configured restaurants. Direct menu visits can browse without customer context | F:`app/page.tsx:Home`; `config/restaurants.ts:getAllRestaurants` (292) |
| Menu identity | Menu catalogue key may differ from ordering key: Wren uses Elai menu data and Wren ordering | F:`config/restaurants.ts` (116–120); `app/api/menu/route.ts:GET` (49); `app/api/checkout/route.ts:POST` |
| WA menu access | Menu query carries recipient, thread_id, minimum_order, distance, order_type | F:`app/restaurant/[id]/page.tsx:RestaurantPage` (15–31) |
| Session validation | Page and basket compare the active restaurant-agent thread with query thread. Missing context blocks checkout; mismatch/error routes to WA recovery | F:`RestaurantPage.validateSession` (38–80); `components/BasketDrawer.tsx:handleCheckout` (64); `app/api/verify-session/route.ts:GET`; O:`order_hooks.py:get_active_thread` (400) |
| Authorization weakness | Checkout proxy checks phone/thread presence but does not independently authenticate owner or repeat the active-thread comparison; active-thread preflight is not duplicate-payment protection | F:`app/api/checkout/route.ts:POST`; O:`order_hooks.py:CreateOrderRequest`, `create_order` |
| Basket | Global React cart is memory-only and has no restaurant identity; navigation may carry items into another restaurant, reload loses them | F:`app/layout.tsx:CartProvider`; `contexts/CartContext.tsx:CartProvider` (43) |
| Menu/options/promotions | Availability and modifiers normalized from external menu; browser computes option charges and promotions. Submitted modifiers become display strings | F:`app/api/menu/route.ts:GET` (142–151); `AddonCustomizationModal.tsx` (22–29); `BasketDrawer.tsx` (104–141); `config/restaurants.ts:getEffectiveDiscountPercentage` |
| Minimum/prices | Basket checks URL-provided minimum against discounted client subtotal; server sums submitted prices without menu relookup. Cart display `price` and submitted `discountedPrice ?? price` may differ | F:`BasketDrawer.tsx` (56–74,108); `CartContext.tsx` (115); O:`order_service.py:create_order_with_items` (172) |
| Hours | Frontend loads service_hours_json; lookup failure/null becomes 24/7 in UI, and a recipient bypass exists. Checkout does not repeat hours checks | F:`lib/restaurantHours.ts:getServiceHours` (22); `MenuContainer.tsx` (166–212) |
| Address | Frontend postcode lookup geocodes a postcode, then asks for house/building. capture-address upserts phone-keyed customer and notifies restaurant-agent; completion returns to WA | F:`address-update/page.tsx:handleLookup`, `handleSubmit`; `api/postcode-lookup/[postcode]/route.ts:GET`; O:`order_hooks.py:capture_address` (342) |
| Eligibility | Ordelo minimum endpoints exist; current frontend has no direct caller. Pricing helper can return -1 for service failure as well as an unusable quote | O:`order_hooks.py:get_min_order_value` (62), `get_min_order_value_by_postcode` (137); `order_service.py:get_min_order_value` (123), `_call_pricing_service` |
| Create | Generates order_id/order_number, inserts food_order and items, initially requires_payment, calculates delivery fees from mutable customer coordinates, generates hosted payment URL | O:`order_hooks.py:create_order`; `order_service.py:create_order_with_items`; `food_order_pymodel.py:from_order_id`, `update_final_order_value_in_db` |
| Atomicity | Parent/item insertion uses separate operations and compensating deletion on failure, not one transaction | O:`order_service.py:create_order_with_items`; `order_db_ops_new.py` |
| Summary | sessionStorage holds pre-payment summary; missing storage redirects home. Backend create response omits subtotal/total although frontend reads them and falls back to arithmetic | F:`BasketDrawer.tsx` (153–198); `order-summary/page.tsx:OrderSummaryPage`, `handlePayNow`; O:`order_hooks.py:create_order` return |
| Payment initiation | Legacy path `/threads/{thread_id}/orders/{order_id}/payment-url`; manual capture used for delivery and online takeaway; takeaway action becomes collection on payment wire | O:`food_order_pymodel.py:payment_uri`, `gen_payment_intent_payload`; `payment_ms/payment.py:generate_payment_intent_url`, `generate_takeaway_manual_payment_url`; O:ADR0002 |
| Payment internals | threadID is metadata, no conversation lookup found. Stripe return URLs are fixed restaurant configuration, including WA links; per-web-checkout return URL is absent | P:`internal/transport/http/handler.go` (127); `internal/stripe/payment.go` (118–154); `internal/config/config.go` (178–215) |
| Authorization | Ordelo callback reads metadata.orderID, unconditionally writes requires_capture, schedules restaurant-agent notify plus init_delivery/init_takeaway | O:`payment_hooks.py:payment_complete_path` (106), `handle_payment_complete` (38), `init_delivery_summary` (80) |
| Webhook wiring gap | payment-service webhook saves PaymentIntent on completed manual Checkout but inspected source does not itself notify Ordelo. Deployed Stripe/gateway event delivery to Ordelo is unverified | P:`internal/stripe/webhook.go:HandleWebhook` (65–103); O:`payment_hooks.py:payment_complete_path` |
| Restaurant acceptance | SQL summaries and hooks drive admin confirmation; configured auto-accept resolves pickup time transactionally, distinct from timeout fallback | O:`jobs_n_functions/resolve_initial_restaurant_acceptance.sql`; `init_delivery.sql`; `init_takeaway.sql`; ADR0001 |
| Delivery capture | Rider inflight hook schedules capture, admin receipt, restaurant-agent notification and rider graph init | O:`delivery_hooks.py:delivery_inflight_graph_init_hook` (522), `capture_delivery_payment` (175); `inflight.sql` |
| Collection capture | First finalized pickup time triggers capture/print; INSERT path covers configured auto-accept. Pay-at-restaurant has print-only path | O:`takeaway_hooks.py:pickup_time_updated_hook` (534), `capture_takeaway_payment` (423); `takeaway_summary.sql:trigger_takeaway_pickup_time_set`, `trigger_takeaway_pickup_time_insert`; ADR0002 |
| Payment completion ambiguity | Capture does not add a new persisted payment_status in current Ordelo model; requires_capture alone cannot prove captured or refunded | O:ADR0002; capture handlers; P:`payment.go:CapturePayment` |
| Capture partial failure | Stripe capture precedes restaurant payout transfer; transfer can fail after capture. A generic HTTP failure therefore does not imply nothing was charged | P:`payment.go:CapturePayment` (183–200); `handler.go` capture branch |
| Cancel/refund | Existing CancelPayment calls PaymentIntent.Cancel; no post-capture refund operation found in inspected payment interface | P:`payment.go:CancelPayment` (206–216); O:`payment_ms/payment.py:cancel_payment` |
| Delivery progress | Rider verifies restaurant/customer codes, pickup changes dispatch pickedup, completion calls dispatch_complete_func. Customer updates go through restaurant-agent hooks | O:`rider_agent.py:verify_restaurant_confirmation_code`, `verify_customer_confirmation_code`; `agent_app_handlers.py:post_rider_event_restaurant_cc`, `post_rider_event_customer_cc`; `dispatch_complete_func.sql` |
| Order visibility | Existing restaurant portal is authenticated, tenant-scoped server Supabase reads; no customer durable tracking view in current checkout | F:`lib/rest-admin-session.ts:getRestAdminSupabase`; `rest-admin/orders/OrdersView.tsx`; O:`migrations/admin_orders_views.sql` |

### 2.3 Dependencies and launch-blocking findings

1. **Thread is a conversation that also carries checkout context.** It identifies checkpoint state, current customer workflow, active-session validation, payment metadata/paths, callbacks, and retention. These functions must be separated; renaming it to session would keep the coupling.
2. **Phone is identity and routing today.** `customer_master.cust_id VARCHAR(12)` is the primary key; `cust_rest_map` has `(cust_id,rest_ref)` and FK to that customer. FoodOrder.recipient, summary.customer_id, init RPC arguments, WA sends, and order-number generation expect the phone. Source: O:`masterdata.sql` (48–73), `customer_master_pymodel.py:CustomerMaster`, `food_order.sql`, `order_num_gen.py:create_order_number`, `init_delivery.sql`, `init_takeaway.sql`.
3. **Source constraints:** food_order has order_number PK, order_id UNIQUE, recipient/thread_id/action NOT NULL; order_item references order_id with cascade delete. No thread FK or one-order-per-thread UNIQUE is present in this inspected DDL. thread PK is thread_id; recipient uses VARCHAR(12), active lookup is agent/recipient scoped. This is not proof of live constraints. Source: O:`food_order.sql` (30–69), `thread_mgmnt_ddl.sql:get_active_thread`, `get_or_create_thread`.
4. **Address race:** init_delivery reads mutable customer_master at authorization time; a separate checkout or address edit can alter the delivery destination. Fees similarly load mutable profile coordinates. A payable order must contain immutable contact/address/coordinate snapshots. Source: O:`init_delivery.sql` (109–124), `food_order_pymodel.py:update_final_order_value_in_db`.
5. **Background work can be lost.** FastAPI BackgroundTasks acknowledgements prove scheduling, not durable completion; exceptions can be logged and returned as success. SQL/webhook processing requires durable effect ledgers and repair before public checkout. Sources: O:`payment_hooks.py`, `delivery_hooks.py`, `takeaway_hooks.py`, `summary.sql`, `inflight.sql`.
6. **Rejection differs by mode.** Delivery decline currently returns status to unassigned without a demonstrated cancellation/refund; collection attempts cancellation but can report payment cancelled after an exception. Timeout can auto-accept in both branches. Sources: O:`delivery_hooks.py:_handle_restaurant_decline` (1334–1360), `_handle_restaurant_timeout` (1378+); `takeaway_hooks.py:_handle_restaurant_decline` (207–242), `_handle_restaurant_timeout` (266+). New web policy must be explicit and payment outcomes verified.
7. **Unsafe public ingress is concrete source behavior.** No signature/event ledger was found in the inspected payment-service webhook or Ordelo payment-complete route. Test replay can force requires_capture; customer address/session/checkout routes lack owner authentication. Deployment-layer protections are unknown. Restrict test/debug endpoints and authenticate ingress before exposing real web ordering. Sources: O:`payment_hooks.py:payment_complete_test_path`, `thread_hooks.py` debug routes; P:`webhook.go:HandleWebhook`; F:`middleware.ts` matcher, customer routes.
8. **WA sender trust requires a decision.** restaurant-agents deliberately disables Meta validation under accepted ADR0022/CONSTITUTION. Secure attachment cannot trust a forged sender field. Use a verified gateway with origin access restricted, or obtain owner approval for a superseding ADR after fixing namespace credential alignment. Do not silently reverse this accepted decision. O also constructs WA client with validate_updates=False (`fapp_ordelo_agent.py`, around 152).
9. **PII is logged today.** F middleware logs full query/URI, recipient/thread/referer; checkout/pay-local logs identifiers; address lookup logs postcode/provider data. New routes must redact PII/tokens; preserve legacy links through a limited exchange adapter and stop propagating their query strings. Sources: F:`middleware.ts` (161–178); `api/checkout/route.ts` (38–48); `api/pay-at-restaurant/route.ts` (48–59); postcode route.
10. **Client contact must not select privileged behavior.** Ordelo FoodOrder.payment_uri uses recipient membership in overwatch_list to select test payment for delivery; frontend hours have a recipient bypass. An anonymous guest typing a number must not activate test or admin behavior. Sources: O:`food_order_pymodel.py:payment_uri` (192); F:`MenuContainer.tsx`.
11. **Lifecycle jobs are conversation-specific.** job_close_thread sends goodbye messages; stale restaurant-thread job derives restaurant from thread_id prefix and inspects retained root checkpoints. A synthetic web thread could be misrouted, closed, or used to message a customer without opt-in. Sources: O:`job_close_thread.sql`, `job_terminate_stale_active_threads.sql` (9–17,42–70); `thread_handler.py`.
12. **Tracking currently loses conversation continuity.** Collection pickup-time callback announces time then closes the conversation. Payment callback validates supplied thread payload but graph invocation resolves active recipient thread; it can differ from the paid order's thread. Sources: R:`runtime/watomation/routers/order_event_hooks.py` (payment hook and 408–437); `runtime/rest_agent/agent_runner.py`. Dedicated order binding is required.
13. **Location URL is not order access security.** Current `/location-hooks/live-location-map/{order_number}` is a readable-number location endpoint. Never expose it unprotected as the private web tracking implementation. Source: O:`location_hooks.py:live_location_map`.
14. **Restaurant routing must fail closed.** Payment-service `Config.GetRestaurant` falls back to `elas` for unknown restaurant keys. New checkout/payment commands must reject an unknown `rest_ref` before creating a session, selecting credentials, transferring funds, or printing a receipt. Preserve explicit known aliases, not an implicit fallback. Source: P:`internal/config/config.go:GetRestaurant` (51–65), `internal/transport/http/handler.go:getPaymentAPI`.
15. **Postcode pricing must retain restaurant identity.** The inspected postcode minimum route does not pass its `rest_ref` into the pricing helper. Verify and correct this adapter before reusing it for public discovery or quotes; test two restaurants with the same postcode input. Source: O:`watomation/routers/order_hooks.py:get_min_order_value_by_postcode` and `utils_common/order_management/order_service.py:get_min_order_value`.
16. **Operational contact is not customer identity.** Rider contact sending reads `delivery_summary.customer_id` and uses it as both phone and WA ID. A UUID or synthetic web customer key cannot replace that field without changing its consumers. Add/read order-scoped `customer_phone` for operational calls, and only set a WA ID when the endpoint is proven to be a WhatsApp contact. Route direct customer sends, including collection decline, through notification preferences. Sources: O:`ordelo/agents/rider_agent.py` (customer contact sender around 593–607), `takeaway_hooks.py:_handle_restaurant_decline`.

### 2.4 Unknowns to verify rather than invent

- Live DB columns, FKs, indexes, RLS, active triggers/functions/cron schedules; historical SQL files and comments differ. Introspect an approved staging DB using database-operations before drafting executable migrations.
- Configured pricing deployment, authoritative menu writer/version/availability/modifier IDs, coverage algorithm, min-spend semantics, delivery capacity feeds. Local legacy pricing files are evidence of older implementations, not proof of the deployed `ms_pricing_url` implementation. O:`config/microservices_setting.py`, `food_order_pymodel.py:get_final_order_value` and `_call_pricing_service` define the observed contract.
- Which Stripe event reaches Ordelo, its verified forwarding chain, provider account selection, version, payment-method support, capture window, cancellation/refund/transfer reversal behavior, provider session IDs and return configuration in deployed infrastructure.
- Actual fulfillment jobs in production, restaurant opening/pause/capacity authority, and how physical takeaway collection is recorded. Never treat ready or elapsed time as collected without evidence.
- Production CDN/edge authentication, request logging, host cache behavior and worker/realtime capabilities.
- Customer transactional email/SMS sender availability; inspected receipt-alert email code is operational and does not establish a customer notification system.
- New aggregator WABA, business identity, merchant responsibilities, support hours, refund authority, controller/processor arrangements and retention schedules.

## 3. Shared architecture and ownership

### 3.1 Modules and interfaces

Deepen the **Order Processing module** in Ordelo. Its interface should accept checkout commands and verified external events and return persisted results. Its implementation concentrates catalog validation, quote binding, immutable order snapshots, idempotency, valid transitions, and effect scheduling. Web and WhatsApp are two real adapters at this seam; locality improves because one rule change reaches both channels. The deletion test matters: deleting this module would move the rules into Next.js, graph tools, payment callbacks, and SQL webhook handlers again.

Retain Postgres functions/constraints for atomic state changes. Keep the existing fulfilment workflow as the implementation behind Order Processing; do not replace all SQL jobs or introduce a new microservice merely to support a second UI. Give payment, pricing/catalog and notification implementations explicit internal adapters where there are actual external contracts or test doubles. Tests cross the same command/event interface as callers; avoid tests that only mirror private helper code.

The **Customer Access module** owns browser/check-out/order grants, verification and notification attachment. It has depth because cookies, expiry, recovery, sender proof and replay handling sit behind a small ownership-check interface. It never grants admin rights.

The **Order Progress module** exposes one versioned customer projection from authoritative records/events. Browser and agent both consume it. It hides legacy status strings, multiple summaries, timestamps and payment reconciliation, giving callers a consistent interpretation.

### 3.2 Authority table

| Fact | Authority | Consumers / rule |
|---|---|---|
| Ordered items, restaurant, quoted charges, contact/delivery snapshots | Persisted FoodOrder + immutable accepted quote | Web UI, restaurant portal, agent, payment receipt; checkpoints cannot overwrite |
| Valid order transitions | Ordelo Order Processing commands + transactional SQL guards | Restaurant/admin/rider/agent adapters request transitions; no independent business-rule copies |
| Payment authorization/capture/refund | Stripe/payment implementation, reconciled into payment_attempt/order projection | Browser redirect and agent statements cannot create payment success |
| Restaurant acceptance/pickup commitment | Persisted acceptance policy and verified admin/kitchen action | Configured auto-accept is creation-time policy, not a late cached boolean |
| Delivery assignment/pickup/completion | Ordelo dispatch/inflight workflow and verified rider commands | Customer order page projects confirmed events, not graph speculation |
| Collection preparation/readiness/collection | Restaurant actions plus persisted collection workflow | Readiness and collection are separate; add missing collection confirmation command |
| Contact identity/ownership | Customer Access verification records | Typing an existing phone cannot load or modify another customer's profile |
| Conversation continuity | Thread + LangGraph checkpoint | Only conversation routing; order processing survives its closure |
| Notification permission/delivery | Order subscription plus delivery ledger | Subscription does not change origin or fulfilment mode |

Restaurant-agents ADR0005/0006 already establish FoodOrder authority and external payment/fulfilment authority. Resolve whether both repositories operate the same deployed tables during staging inventory; consolidate writes into the shared Ordelo commands rather than create a second order aggregate.

### 3.3 State dimensions and transition table

Represent these separately in the v2 projection. Initially keep legacy fields for old callers and map them explicitly:

- Order lifecycle: `awaiting_payment`, `pending_acceptance`, `accepted`, `completed`, `rejected`, `cancelled`, `failed`.
- Payment: `unpaid`, `initiating`, `action_required`, `authorized`, `capture_pending`, `captured`, `release_pending`, `released`, `refund_pending`, `partially_refunded`, `refunded`, `failed`, `unknown`.
- Acceptance: `not_requested`, `pending`, `accepted`, `rejected`, `timed_out`; method `manual`, `configured_auto`, or approved legacy `timeout`.
- Preparation: `not_started`, `preparing`, `ready`; food-ready must be confirmed if shown as a fact.
- Delivery: `not_started`, `searching`, `assigned`, `picked_up`, `delivered`, `failed`.
- Collection: `not_started`, `awaiting_collection`, `collected`, `no_show`.

These are proposed contract names, not claims that existing SQL enums accept them. Do not write them into legacy constrained columns before migration. `unknown` payment is a reconciliation state, not permission to charge again.

| Trigger | Required guard / durable command | Order / acceptance / fulfilment result | Payment result and customer treatment |
|---|---|---|---|
| Pay clicked | Owned checkout, current accepted quote, open service, valid items; atomic checkout consumption | Create awaiting_payment order/items/snapshots/event before provider call | initiating attempt; return same attempt for replay |
| Provider action required or browser returns early | Verified provider state; owned order read | Remain awaiting_payment | action_required/pending; show checking, never success from URL |
| Provider authorizes | Verified event/account/amount/currency/order/attempt; transition once | pending_acceptance; initialize exactly one matching summary and acceptance deadline | authorized; explain funds held until acceptance/fulfilment milestone |
| Configured auto-accept | Explicit per-mode policy snapshot, valid capacity/prep calculation | accepted/preparing; set committed pickup time | Collection capture scheduled; delivery capture still waits assignment initially |
| Manual acceptance | Authorized admin scope/order/version; time policy valid | accepted/preparing; delivery searching or collection awaiting_collection | Collection capture at finalized pickup time; delivery remains authorized until assignment |
| Rider assigned | Accepted delivery, valid assignment, authorization valid | assigned; emit confirmed assignment | capture_pending; capture exactly once using provider key |
| Capture confirmed | Provider state reconciled, correct amount | Permit kitchen/rider release under chosen policy | captured; payout and printing are independent retryable effects |
| Food ready | Verified restaurant action; accepted nonterminal order | preparing→ready; collection awaiting_collection; delivery unchanged | No new charge; notify eligible subscriptions |
| Rider pickup | Assigned same dispatch, verified code, capture confirmed or explicitly approved exception | picked_up; immutable pickup event | Captured remains captured |
| Delivery confirmed | Valid assigned/pickedup dispatch and confirmation | completed / delivered | Receipt/progress updates; no implicit refund |
| Collection confirmed | Authorized restaurant collection action, valid order | completed / collected | Captured or explicitly settled pay-at-rest; do not infer from ready/time |
| Restaurant rejects | Order not already completed; reject beats stale assignment/acceptance using lock/version | rejected; cancel dispatch/init effects | Release authorization; if already captured, refund workflow; display pending until verified |
| Acceptance deadline expires | Fresh persisted state still pending; web policy defaults no fallback acceptance | timed_out acceptance; rejected/cancelled order | Release pending then released; ops alerted if release fails |
| No rider / delivery failure | Persisted dispatch timeout or authorized ops failure command | failed; stop inappropriate dispatch/notifications | Release if uncaptured; refund assessment if captured; show action and support ownership |
| Customer cancellation requested | Owned order, policy allows; serialize against capture/accept/pickup | cancelled if approved; otherwise request pending/manual review | Release/refund according to actual provider state; never promise generic refund instantly |
| After-capture refund requested | Authorized support/merchant policy; refund amount <= captured minus prior refunds | Preserve fulfilment history; attach cancellation/refund reason | refund_pending→refunded/partial only after provider confirmation; payout reversal handled separately |
| Duplicate/stale event | Unique event/object guard, transition/current provider state checked | No replay of init, print, admin alert or assignment | No regression captured→authorized; acknowledge durable receipt |

Serialize reject/cancel/assignment/capture commands per order. A rejected order cannot accept a late rider assignment. If capture races rejection and succeeds, reconciliation creates the refund effect rather than losing the captured-money fact.

## 4. Identifier responsibilities and lifecycles

| Identifier | Responsibility | Created / expired | Required before payment? |
|---|---|---|---|
| `customer_id` UUID / guest subject | Stable internal person/profile link; never the browser credential | Guest subject when checkout starts; profile can be created lazily; merge only with verified evidence | Guest subject required; account/profile optional |
| `phone_e164` / legacy `recipient` | Contact and current WA routing endpoint | At checkout; normalization plus verification status/timestamp; can change | Contact required; WA account/session not required |
| `browser_session_id` | Anonymous device/session ownership of baskets/checkouts/grants | First stateful interaction; cryptographically random HttpOnly cookie; proposed idle 30 days with revocation | Yes for web stateful flow; no account |
| `basket_id` | One-restaurant item choices/revision | First add; proposed 7-day persistence; invalidated/revalidated on changes | Items required, distinct entity optional inside checkout JSON |
| `checkout_session_id` UUID | Checkout container with restaurant, mode, snapshots, basket/quote revisions, idempotency and lifecycle | Checkout start; proposed 24-hour draft expiry; consumed once into order | Yes |
| `quote_id` UUID | Immutable server quotation and policy/input/version binding | Every material recalculation; proposed 10-minute payable expiry | Yes; must be current at initiation |
| Internal order ID | FoodOrder identity; keep existing order_id and order_number compatibility | Persisted transaction before provider call; retained under records policy | Yes before provider initiation |
| `public_order_id` random UUID | Stable route locator, independent of short display reference | At order creation; does not expire as locator | Yes for safe return/tracking URL; not a credential |
| `order_number` | Human reference for restaurant, receipt, support | Existing generation retained until replacement; never used as access proof | At order creation |
| `payment_attempt_id` UUID | One logical payment authorization attempt and provider resources | Before provider session creation; immutable association; explicit attempt replacement | Yes |
| `provider_session_id`, `payment_intent_id` | Provider reference and reconciliation | Recorded on successful/uncertain provider initiation; update from verified events | Resolve before final payment facts; not browser authorization |
| `conversation_thread_id` | One agent conversation/checkpoint lifecycle | Only when WA conversation starts/attaches; can close independently | No |
| `legacy_payment_context_id` | Temporary payment metadata/path bridge for web checkout | Once per checkout/order; immutable with context_kind=checkout | Only until v2 payment contract; never active conversation row |
| `notification_subscription_id` | Order-scoped permission/endpoint/purpose and status | Explicit opt-in or transactional contract event; revocable; reactivation recorded | No for WA; independent email delivery available at launch |
| `order_access_grant_id` | Browser subject permission to read one order/allowed commands | At creation/verified recovery; proposed 30-day scope; revoke/rotate | Yes by order creation; refreshed separately from conversation |
| `handoff_challenge_id` | Short-lived correlation for browser-to-WA attachment | Owned order page action; proposed 15-minute expiry | No; phase after payment |

### 4.1 What to do with today's thread

The current thread remains a real conversation record. Preserve it for WhatsApp-originated legacy orders and existing active/inflight conversations. Its current active lookup may prevent stale basket submission, but it is not an authoritative checkout/order idempotency key.

For web compatibility, the new checkout generates an opaque random context ID and records `context_kind='checkout'`. Put this ID in the legacy FoodOrder.thread_id/payment-service path only until all callers support explicit checkout and nullable conversation IDs. Do not create a `thread` row, checkpoint, active session or retention exception. Skip legacy customer-agent callbacks for web orders without a proven conversation subscription. Do not skip core summary initialization, admin receipt, rider dispatch or payment effects.

The compatibility ID must stay immutable when the customer attaches WA. Payment keys/path lookups must not change mid-order. Store actual conversation linkage in `order_conversation`; do not overwrite food_order.thread_id with a later WA thread during the bridge period.

**Exit path:** deploy v2 payment/order requests keyed by `order_id` + `payment_attempt_id`, with optional conversation ID; dual-read old/new records; migrate consumers; allow legacy thread_id only for historical/WA compatibility; eventually make it nullable/rename legacy field. Never repurpose thread-table lifecycle for browser expiry.

### 4.2 Phone-primary-key migration without an unsafe big bang

Add UUID identity alongside existing customer_master.cust_id; a separate guest subject can be created without claiming an existing phone-keyed customer's profile. Store the name, phone, email, verification state and complete address on the order/checkout snapshot. For v2 init_delivery/init_takeaway, read snapshots rather than mutable master rows. Legacy summary.customer_id can remain contact phone temporarily if old callbacks require it, while new fields retain UUID linkage.

Do not upsert an existing customer profile/address based solely on an unverified web phone. The new v2 init/pricing path must accept order snapshots and avoid that dependency. If live constraints require a legacy customer row, create a narrowly scoped bridge for a new contact without overwriting an existing profile, and still use the immutable order snapshot as destination. Prefer removing that requirement in the new RPC before launch.

Introduce verified contact mappings and profile merges later. A shared family phone does not automatically prove one person, a recycled number does not grant historic orders, and verification of a new order's phone does not grant every legacy order on that number. UUID foreign-key migration is additive and gradual; inspect all existing summary/customer/cust_rest_map consumers before changing their types.

## 5. Minimum proposed data model

These are conceptual additive migrations. Implement executable SQL only after live schema inventory. Keep FoodOrder as the aggregate; do not create a competing `web_orders` ledger.

| Record | Minimum fields / constraints | Introduced when |
|---|---|---|
| `food_order` additions | `public_order_id UUID UNIQUE NOT NULL` for new orders; `rest_ref` explicit FK after validating legacy mappings; nullable `customer_uuid`; `origin_channel` CHECK web/whatsapp/unknown_legacy immutable; `checkout_session_id` UNIQUE for new checkout-backed orders; `quote_id`; `payment_context_kind`; immutable contact/address/pricing/policy snapshots; lifecycle/version fields or transactional companion row | Backend foundation before live web orders |
| `checkout_session` | UUID PK, guest/browser subject, rest_ref, canonical mode, basket JSON/revision, contact/address snapshot revision, active quote_id, draft/payment_pending/consumed/expired lifecycle, order linkage, timestamps/expiry. Reject updates once payment is pending | Backend foundation |
| `checkout_quote` | UUID PK; checkout_id; basket/address/mode/menu/pricing/promotion/availability versions and input hash; currency; eligibility reason; immutable line/fee/discount breakdown; minimum basis and value; totals in integer pence; created_at/expires_at; reservation reference if supported | Quotation phase |
| `payment_attempt` | UUID PK, order_id FK, attempt ordinal UNIQUE per order, quote_id, expected amount/currency, provider/account/session/intent IDs, explicit status, capture/release/refund amounts, authorization expiry, timestamps/error classification. Unique provider resource bindings; one payable/in-progress attempt per order enforced | Payment foundation |
| `payment_event_inbox` | Provider/account/event_id UNIQUE, event/object type/id, body hash or restricted encrypted payload, verification received_at, processing status/retries/error. Persist receipt before 2xx | Payment foundation |
| `order_event` + `order_effect` | Order ID/version/event type/timestamp/actor and safe payload; UNIQUE(order_id,version). Durable effects with UNIQUE(event_id,effect_type,target), pending/leased/succeeded/retry/dead-letter, attempt count/next_attempt/error. Financial operation keys separate from messaging/print keys | Payment and fulfilment reliability |
| `customer_access_session` + `order_access_grant` | Hash of opaque browser secret, guest subject, expiry/revocation; grant UNIQUE(session_id,order_id), permissions/read/cancel-request/attach, audit. No universal grant by phone | Guest access phase |
| `order_notification_subscription` | Order FK, channel email/whatsapp/sms, purpose order_updates, endpoint/contact mapping, pending/active/revoked/expired; verification/consent timestamps, business/WABA scope, policy copy version; uniqueness preventing duplicate active same-endpoint subscription | Email before launch; WA when handoff ships |
| `notification_delivery` | Event/effect/subscription uniqueness, provider message ID, queued/sent/delivered/failed states, attempts. Can be effect-table extension instead of separate table | Independent notifications |
| `order_conversation` | Order FK + actual thread ID + agent/business identity + created/closed times; supports several orders in one conversation and new conversation after old closure | WA attach/aggregator phase |
| `wa_handoff_challenge` | Hash of opaque correlation code, order_id, issuing browser grant, expected contact/business, expiry/consumed recipient/thread and audit; atomic consumption | WA handoff phase |
| Discovery catalogue | Town slug/label; stable restaurant public slug→rest_ref/menu source; restaurant-town many-to-many with listing role (located/serves); alias history. Initially server-owned config is sufficient; DB tables only when admins need editing | Discovery phase |

`origin_channel` describes where checkout began. The existing browser menu launched from WhatsApp is **whatsapp-originated**, even though food selection occurs in a browser. Set it from the trusted legacy-link exchange, not an arbitrary request body. Define `unknown_legacy` for history lacking reliable provenance; do not assert every old row came from WhatsApp merely because it has a thread ID. Analytics can separately record referral/source and menu surface.

`fulfilment_mode` is delivery/collection in new contracts; adapt collection→legacy `action='takeaway'` and payment action collection. Different notification channels do not require separate order records. Marketing stays in the per-customer/per-business consent ledger; an order-update subscription must not automatically set `cust_rest_map.has_consent=true`.

### Constraint and migration rules

- Money uses integer minor units (GBP pence), or exact NUMERIC with enforced rounding; remove float arithmetic from new authoritative computations. Preserve legacy representations through adapters until migrated.
- Validate quantity > 0 and bounded; immutable priced line snapshots store SKU plus modifier group/option IDs and display text. Reject invalid combinations, cross-restaurant items, stale offers and negative totals.
- Atomically insert order, lines, snapshots, payment attempt intent and durable initiation effect. A request-key ledger binds key + authenticated subject + operation + request hash + result; same key/different input returns 409.
- `checkout_session_id` uniqueness makes one consumed checkout produce one order. No UNIQUE(phone), UNIQUE(active_customer_order), or UNIQUE(thread_id) on orders; legitimate repeat orders are allowed.
- Provider event ID uniqueness handles redelivery; operation uniqueness handles different events reporting the same authorization. A status/version predicate handles business races.
- Prefer explicit rest_ref over parsing order_number everywhere new. Preserve CHKS/ELAS and Wren aliases intentionally after mapping verification.
- Keep old status CHECK constraints and views functional; use a v2 projection/companion state during migration if renaming legacy columns would break jobs.
- Backfill public IDs for tracking only after choosing historical-access policy. Backfill provenance conservatively. Build concurrent indexes where needed, then validate constraints in a controlled window.
- Deploy additive migrations and backward-compatible readers first. Rollback disables new writes; it does not drop columns/tables containing paid orders.

## 6. Guest experience, contact collection, and order security

### 6.1 Guest checkout recommendation

No account is required to discover restaurants, browse, build a basket or pay. Do not interrupt discovery with login or WA installation.

At restaurant selection, ask mode; for delivery offer postcode estimate. During checkout collect name, reachable phone, and transactional receipt/recovery email. **Assumption for initial web release:** email is required because it supplies independent receipt, recovery and important updates when the browser closes. Explain its purpose; marketing opt-in remains separate and unticked. If mandatory email is unacceptable, a tested SMS receipt/recovery implementation must replace it before launch; a browser-only cookie cannot solve lost-device recovery.

Collect full delivery address only for delivery: address lines, building/flat/unit, street/locality/postcode, server-resolved coordinates and delivery instructions. Collection needs name/contact and chosen venue/time, no home address. Put allergy requirements in a separate restaurant-visible field with explicit kitchen handling; do not treat free text as a guarantee of allergy-safe preparation.

Phone format validation is required, while phone OTP before every online card checkout is optional. Recommendation: do not require OTP for every low-risk card order initially; require it when risk controls trigger, changing a protected contact, claiming/merging a profile, or enabling later cash collection. Normalize E.164; translate to current digit-only UK fields only in the compatibility adapter. The existing VARCHAR(12) limit is not universal E.164 support. Launch can explicitly limit delivery market/contact support while planning its widening.

Unverified phone/email fields grant no access to historic orders or customer_master. Return the order-created grant to the originating browser. Verify an email/SMS recovery challenge before granting a new device access. Successful WhatsApp receipt supplies verified control of that WhatsApp endpoint only after trusted Meta ingress; it is not a customer account merge.

### 6.2 Secure access model

The browser receives a cryptographically random Secure, HttpOnly, SameSite=Lax cookie; persist only its hash. Bind each order to an explicit grant. An order locator in `/orders/{public_order_id}` reveals no private data without that grant. Same-origin CSRF/Origin checks protect mutations; cookie attributes alone are insufficient. The Next.js server authenticates customer ownership and invokes Ordelo with an authenticated, limited internal identity; Ordelo also enforces resource scope. Keep service credentials off the browser.

Returning or refreshing on the same device reuses its grant and fetches the persisted order; sessionStorage is not the recovery authority. A new device opens the clean order locator and verifies a one-time email code sent to the order's recorded endpoint. Use generic responses for recovery, rate limits, TTL, attempt caps and revocation. Email receipt links contain only the order locator; recovery credentials are entered in a form rather than placed in ordinary URLs. Optional SMS follows the same model. Do not make a guest search by phone sufficient for order listing.

Expiry proposals: draft checkout 24 hours, quote 10 minutes, order browser grant 30 days, recovery code 10 minutes, WA correlation 15 minutes. These are explicit configurable assumptions; align grant lifetime with support/refund needs and retention. Do not copy admin four-hour expiry or brittle exact user-agent binding into customer tracking.

Private pages and all customer DTO responses: `Cache-Control: private, no-store`, appropriate `Vary`, `noindex,nofollow`, restrictive referrer policy and no third-party page/session recording. Server/CDN shared caches must never store them. Order item/address/contact payloads do not go to analytics. Redact all credentials and PII from request logs, referers, errors, screenshots and diagnostics. A CSP and output escaping protect notes/menu content; use provider-hosted payment so card details never pass through Ordelo.

### 6.3 Admin separation

Keep `/rest-admin/orders` and its existing tenant-authenticated APIs. Shared visual components can render customer/admin data, but use different DTOs, authorization grants and command permissions. The town tracking route cannot become a way to list all town orders. Customer may read their own order and request allowed support actions; restaurant admin may read tenant orders and confirm preparation/collection; support needs explicitly scoped privileged commands and audit.

The current admin server Supabase key bypasses RLS and depends on JavaScript tenant filtering. Do not expose that client/projection to customers. Add tests for cross-tenant routes, raw client escapes, role confusion and forged context headers. Harden direct service ingress and test/debug routes alongside web launch.

## 7. Page routes, API contracts, and discovery

### 7.1 Public/private page routes

| Page route | Purpose / access | Canonical and compatibility rules |
|---|---|---|
| `/` | Public town/location chooser plus browse entry | No identity required; optionally remember discovery town |
| `/town/{town_slug}` | Public town restaurant listing | Requested path; slug lowercase/hyphenated; town is discovery context |
| `/town/{town_slug}/restaurants/{restaurant_slug}` | Public contextual menu URL | Resolve slug→rest_ref; can render same menu with town breadcrumbs; canonical SEO URL is restaurant page |
| `/restaurants/{restaurant_slug}` | Public canonical restaurant menu/direct link | Stable restaurant discovery independent of serving several towns |
| `/checkout/{checkout_session_id}` | Private owned checkout | UUID is locator; authenticated cookie/subject and ownership check; noindex/no-store |
| `/orders/{public_order_id}` | Private canonical guest tracking/help page | Grant required; clean return page after payment; noindex/no-store |
| `/town/{town_slug}/orders/{public_order_id}` | Optional contextual tracking alias requested by owner | Same order grant and DTO; town confers no permission; canonical clean order route or context-preserving render |
| `/order-access` | Private recovery entry | Generic request/verification forms; no PII query params |
| `/rest-admin/orders` | Existing admin list | Independent tenant authentication; keep route |
| `/restaurant/{legacy_id}` | Existing WA menu compatibility | Validated legacy session exchange, preserve active session handling during migration; sanitized navigation thereafter |
| `/address-update`, `/order-summary` | Existing WA routes | Keep for legacy; new web flows use owned checkout/review and persisted order page |

The restaurant's physical town and advertised delivery towns need not coincide. A restaurant can appear under several discovery towns; display venue location and service estimate truthfully. An arbitrary town selection must not authorize delivery; actual address and selected restaurant decide coverage. Offer nearby discovery alternatives for no results/out-of-range orders, with clear customer confirmation before changing restaurant.

Slugs are public names; rest_ref is the permanent operational identifier; menu catalogue key is an explicit separate mapping. Never infer one from the other. Slug changes create server-maintained aliases and permanent redirects on public pages; private order locators survive town/restaurant renames. Unknown restaurant/town gives a proper 404 without side effects. Invalid town/menu pairing can redirect to canonical restaurant or show it as neighbouring service if policy supports that relationship.

SEO: server-render public town/menu descriptions and structured data from verified merchant facts; canonical URLs avoid duplicate town menus, sitemap includes only public pages. Availability/hours markup must reflect real data, and ratings must have provenance. Checkout, recovery, private orders and API endpoints are excluded from indexing and shared caches. Robots.txt alone is not authorization.

### 7.2 Browser API versus internal contracts

Proposed APIs use `/api/v2` in Next.js. Ordelo uses authenticated `/v2` contracts. These are proposed paths, not currently implemented. Browser calls only Next.js; Next.js forwards a scoped server identity to Ordelo. Slugs belong to pages/discovery; transactional payloads use stable rest_ref.

| Browser-facing contract | Internal contract / owner | Important input, output and guard |
|---|---|---|
| `GET /api/v2/towns` | Server discovery catalogue | Public labels/slugs and availability summary |
| `GET /api/v2/towns/{slug}/restaurants` | Discovery + restaurant availability | Restaurants with explicit rest_ref/public slug/menu source mapping; estimates do not assert address eligibility |
| `GET /api/v2/restaurants/{rest_ref}/menu` | Catalog adapter | Versioned SKU/modifier/offer/allergen/stock model; presentation cache separate from payment validation |
| `POST /api/v2/checkouts` | `POST /v2/checkouts` | Create browser-owned checkout; rest_ref + mode; session cookie; idempotency key |
| `PATCH /api/v2/checkouts/{id}` | `PATCH /v2/checkouts/{id}` | Items/options/contact/address/mode + expected revision; ownership; increments revision; invalidates quote |
| `POST /api/v2/address-lookups` | Address adapter | Postcode/address query in body; limited results/rate limits; no profile mutation |
| `POST /api/v2/checkouts/{id}/eligibility` | `POST /v2/checkouts/{id}/eligibility` | Provisional postcode/full-address eligibility; typed service/out-of-range errors |
| `POST /api/v2/checkouts/{id}/quotes` | `POST /v2/checkouts/{id}/quotes` | Server authoritative price/eligibility; quote_id, expiry, breakdown and policy versions; no client price input |
| `POST /api/v2/checkouts/{id}/payment-attempts` | Order Processing command | quote_id + checkout_revision + accepted_quote_hash + Idempotency-Key; creates/reuses order and attempt; clean tracking/payment URL |
| `GET /api/v2/orders/{public_id}` | `GET /v2/orders/{public_id}` | Order grant; dedicated safe DTO, payment/acceptance/fulfilment/refund projection/version |
| `POST /api/v2/orders/{public_id}/cancel-requests` | Order Processing cancellation command | Order grant and policy; idempotency; request versus confirmed cancellation distinguished |
| `POST /api/v2/order-access/challenges` / `/verify` | Customer Access | Generic response and email/SMS code verification; no phone-based historic access |
| `POST /api/v2/orders/{public_id}/whatsapp-handoffs` | Customer Access | Owned order; business/phone-bound short-lived correlation challenge; later phase |
| `DELETE /api/v2/orders/{public_id}/subscriptions/{id}` | Customer Access | Revoke that order-update subscription, audited and idempotent |
| None: provider ingress | Authenticated `/v2/payment-events` | Verify Stripe raw signature directly, or verified provider forwarding signature; durable inbox, event/resource/account/amount checks |
| None: restaurant/rider ingress | Order Processing internal commands | Verified role/rest_ref/order/dispatch/version; legacy callbacks adapt here; not public browser operations |
| None: WA attach ingress | Authenticated `/v2/order-notifications/whatsapp/attach` | Trusted Meta message ID/sender/business + challenge; idempotent subscription/binding; no checkout replay |

Internal direct calls must enforce authentication even when the frontend checks cookies. Restrict DB-trigger/worker ingress through verified signatures or service identities/network policy; do not rely on no CORS as authentication. Web requests must not set arbitrary callback/return URLs (SSRF/open redirect risk). Validate allowlisted hosted-payment URLs and server-selected return routes.

### 7.3 Example requests and responses

Fictional values below illustrate new contracts. Timestamps, money and expiry are examples, not live configuration.

```http
POST /api/v2/checkouts
Idempotency-Key: guest-checkout-creation-uuid
Content-Type: application/json
Cookie: __Host-ordelo-customer=<opaque-http-only-cookie>

{"rest_ref":"ELAS","fulfilment_mode":"delivery"}
```

```json
{"checkout_session_id":"c0c6ab55-1308-4f25-84a4-49c105ee3aa2","revision":1,"status":"draft"}
```

```http
PATCH /api/v2/checkouts/c0c6ab55-1308-4f25-84a4-49c105ee3aa2
Content-Type: application/json

{
  "expected_revision": 1,
  "items": [{"sku":"example-meal","quantity":2,"modifiers":[{"group_id":"side","option_id":"rice"}]}],
  "contact": {"name":"Example Customer","phone":"<phone_e164>","email":"<receipt_email>"},
  "delivery_address": {"line1":"<premises>","line2":"<flat_or_unit>","locality":"<town>","postcode":"<postcode>","lookup_id":"<server_address_reference>","instructions":"<optional>"}
}
```

Server resolves coordinates and validates address; client lat/lon is not authoritative. Full manual entry uses the same validation/geocoding contract, with a clear unsupported/unresolved-address outcome.

```http
POST /api/v2/checkouts/c0c6ab55-1308-4f25-84a4-49c105ee3aa2/quotes
Content-Type: application/json

{"checkout_revision":2}
```

```json
{
  "quote_id":"ad7e7372-c0f5-4b59-a2df-92e9065fce20",
  "checkout_revision":2,
  "currency":"GBP",
  "eligibility":{"result":"eligible","precision":"premises","distance_miles":3.1},
  "minimum_spend":{"amount_minor":1500,"basis":"food_after_discounts_excluding_fees","qualifying_amount_minor":2160,"met":true},
  "lines":[{"sku":"example-meal","quantity":2,"unit_base_minor":1200,"line_discount_minor":240,"line_total_minor":2160}],
  "totals":{"food_before_discounts_minor":2400,"discount_minor":240,"food_after_discounts_minor":2160,"delivery_fee_minor":300,"service_fee_minor":150,"small_order_fee_minor":0,"total_minor":2610},
  "menu_version":"example-menu-v4",
  "pricing_policy_version":"example-policy-v2",
  "quote_hash":"<canonical-input-and-price-hash>",
  "created_at":"2026-09-29T17:00:00Z",
  "expires_at":"2026-09-29T17:10:00Z",
  "collection_or_delivery_estimate":{"kind":"estimate","earliest":"2026-09-29T17:45:00Z","latest":"2026-09-29T18:00:00Z"}
}
```

```http
POST /api/v2/checkouts/c0c6ab55-1308-4f25-84a4-49c105ee3aa2/payment-attempts
Idempotency-Key: stable-payment-submit-uuid
Content-Type: application/json

{"quote_id":"ad7e7372-c0f5-4b59-a2df-92e9065fce20","checkout_revision":2,"accepted_quote_hash":"<quote_hash>"}
```

```json
{
  "order":{"public_order_id":"7bc1c1dd-dfa3-4dad-bf55-a2521c0c933e","order_number":"ELAS-DEMO-1","origin_channel":"web"},
  "payment_attempt_id":"06515be8-7b01-460d-aabd-cbf182c51fb6",
  "payment_status":"initiating",
  "payment_url":"https://<allowlisted-provider-host>/<checkout>",
  "tracking_path":"/orders/7bc1c1dd-dfa3-4dad-bf55-a2521c0c933e"
}
```

If provider initiation is still being reconciled return 202 with same attempt and owned status path; do not invent a URL or start another order. A changed/expired quote returns 409 with code `QUOTE_CHANGED`/`QUOTE_EXPIRED`, current replacement quote if available, and a human-readable explanation. The customer must accept changed totals before payment.

```json
{
  "public_order_id":"7bc1c1dd-dfa3-4dad-bf55-a2521c0c933e",
  "order_number":"ELAS-DEMO-1",
  "version":9,
  "origin_channel":"web",
  "fulfilment_mode":"delivery",
  "payment":{"status":"authorized","captured_minor":0,"authorized_minor":2610,"refund_status":"none"},
  "acceptance":{"status":"accepted","method":"manual"},
  "preparation":{"status":"preparing"},
  "fulfilment":{"status":"searching_for_rider"},
  "times":{"pickup":{"kind":"confirmed","at":"2026-09-29T17:35:00Z"},"delivery":{"kind":"estimate","earliest":"2026-09-29T17:45:00Z","latest":"2026-09-29T18:00:00Z"}},
  "last_confirmed_event_at":"2026-09-29T17:12:00Z",
  "checked_at":"2026-09-29T17:12:10Z",
  "support":{"restaurant_phone":"<public-business-contact>","order_support_path":"<configured-support-path>"},
  "notifications":{"whatsapp":"not_subscribed","email":"active"}
}
```

Customer DTO may include own items, address, charges and receipt under grant, but excludes restaurant pickup code, bank/payout/commission values, internal thread state, private rider number and other customers. Delivery customer confirmation code is available only to the owning customer when appropriate; restaurant code is a separate authorization secret. Full support/cancellation DTO definitions are required before implementation.

## 8. Basket, fulfilment selection, and quote lifecycle

### 8.1 Basket policy

One basket per restaurant per active checkout. Recommend one active displayed basket initially; switching restaurants asks to replace it, explaining that totals/offers differ. Do not silently send mixed-restaurant items. A later saved-baskets feature can preserve separate drafts, but this does not justify multi-restaurant payment at launch.

Persist non-sensitive basket selections locally with schema version, restaurant identity, menu version and updated_at, and synchronize authoritative checkout revisions on the server. Do not store full address/contact/access secrets in localStorage. On refresh or a new tab fetch current server checkout and show conflicts rather than applying stale state. Use revision checks for concurrent edits; browser storage events/BroadcastChannel may improve UI, but DB guards are the authority.

| Customer change | Required behavior |
|---|---|
| Town only | Keep selected restaurant/basket; discovery context changes, no coverage promise. If actually switching restaurant, apply replacement rule |
| Restaurant | Confirm basket replacement; new restaurant checkout; invalidate prior quotes/attempts; explicit catalogue/rest_ref mapping |
| Delivery↔collection | Keep valid items; recalculate every offer/fee/minimum/time rule; require acceptance of removed offers or unavailable mode-specific items |
| Postcode/address/flat/premises | Invalidate delivery quote; resolve coordinates and full address revision; no mutation of an already-paid order |
| Delivery instructions only | Revise order snapshot; recalculation if instructions imply changed access/route; otherwise quote remains valid only if canonical input policy allows |
| Items/options/quantity | Validate options/stock; increment basket revision; new quote and discounts/minimum |
| Menu/offer/hours/capacity version changes | Revalidate on quote/payment; show removed/sold-out items and explicit before/after amount; do not auto-substitute |
| Quote expires | Keep basket and address; new quote, show any change, require renewed acceptance |
| Payment already initiated | Freeze payable checkout; cancel/expire old provider session and reconcile before edits/new attempt. Never leave two payable sessions for different totals |
| Payment complete | Basket consumed once; receipt/order snapshot fixed. “Order again” creates a new checkout and fresh quote |

### 8.2 Estimate versus binding quote

Postcode-only lookup is sufficient to guide discovery and provisional eligibility if pricing supports a centroid estimate. Label it clearly and never guarantee a border-of-zone delivery based on centroid. A server-resolved full address/premises location is required for final route eligibility and delivery charges. Support manual addresses where lookup misses new buildings or flats; unresolved geocoding requires a defined support/validation path before taking payment.

A final quote must include: selected restaurant and mode; eligibility and reason; address/location precision and server-resolved input binding; menu/items/modifiers; discount allocations; fee components; min spend and qualifying base; currency; exact totals; rule versions; service time/slot/capacity assumptions; issue/expiry; canonical input hash. Returning just min_order_value is not a final quote.

**Recommended minimum rule for launch:** net food value after item/offer/voucher discounts, excluding delivery, service, small-order fees and tips. This matches the intent of current client minimum comparison but corrects its inconsistent base. Merchant approval is a blocking business decision because existing pricing/offer behavior is not fully verified. If merchant chooses gross or eligible-category minimum, encode that rule/version and display it explicitly. A pre-discount promotion threshold is a separate predicate and must not silently redefine the delivery minimum. Small-order fee cannot override below-minimum rejection unless that policy is deliberately supported.

Example: food £24, discount £2.40, net food £21.60, delivery £3, service £1.50, total £26.10. A £15 minimum is met by £21.60. Fees never help satisfy that minimum. Round per documented line/allocation rules so provider amount, receipt, payout calculations and customer total reconcile exactly.

Mandatory recalculation: material item/modifier/quantity change; mode change; postcode/premises/address coordinates; coupon/offer change; restaurant change; expired quote; menu/pricing/availability revision; slot change. Recheck availability and policy at payment initiation even within TTL. After payment starts, honor the frozen quoted amount; do not silently reprice an authorized order.

Classify errors: invalid postcode/address, out_of_range, below_minimum, service_closed/paused, capacity_unavailable, item_unavailable, offer_expired, quote_expired, pricing_unavailable. Pricing outage is not “we do not deliver there.” Fail closed for payment if authoritative checks cannot complete; browsing may remain available.

## 9. Availability and collection-time policy

Venue hours, delivery/collection service windows, date exceptions, temporary pause, menu stock, lead time, cutoff and capacity are distinct. New-order checks belong server-side. Existing paid-order support remains available after closing; do not expire an order because the menu is closed. Use Europe/London for merchant schedules and UTC timestamps; test DST, midnight, split intervals and holidays.

Launch with ASAP ordering. Scheduled orders are later unless merchant capacity/calendar, payment authorization timing and advance cancellation rules are ready. A schedule chooser without dependable slot reservation is misleading. Delivery capacity may be a coarse operational pause at launch; display estimate and do not guarantee a rider. Acceptance/cancellation timeout thresholds must be configured and monitored.

Current configured auto-accept already calculates pickup time via the database acceptance-policy module, shared by delivery/collection. Preserve that design. To satisfy directly assigned web collection time, extend it with an explicit per-mode/per-channel approved acceptance policy and quote/init input; do not set the existing restaurant-wide auto_accept just to enable collection and accidentally change delivery/WA behavior.

- **Configured auto-accept + capacity contract:** confirm collection time immediately after authoritative authorization/init transaction. Snapshot prep policy and calculate from authorization/acceptance time, kitchen load and next service availability. It is a confirmed merchant commitment, and adjustment is an explicit audited event.
- **Manual acceptance:** show “Estimated ready around…” before acceptance, not a confirmed pickup time. Restaurant confirms/revises it; first finalized time triggers capture under ADR0002.
- **Cannot meet time:** restaurant can propose an updated estimate/commitment or reject before capture under policy. Customer sees change and cancellation option where supported. After capture, rejection requires refund processing, not PaymentIntent.Cancel.
- **Ready/collected:** ready event updates persisted order before notifications. The current ready callback primarily forwards to restaurant-agent; add an authoritative ready/collected command so web-only orders progress. A ready message, pickup_confirmed status, or elapsed pickup time must not mark actual collection completed.

Pending owner response, the proposed web timeout rule is release authorization and reject/cancel after a configured deadline; explicitly configured auto-accept is the exception. Existing WA timeout behavior stays behind its legacy policy until a separately tested rollout. Operational staff must own failed release/refund and overdue orders.

## 10. Payment creation, retries, failures, and reconciliation

### 10.1 Creation order and capture policy

1. Authenticate ownership; validate the checkout revision, accepted quote, current availability and price versions. Resolve contact/address entirely into snapshots.
2. In one transaction, consume/lock the checkout, create FoodOrder and priced lines/snapshots, reserve a logical payment attempt, and enqueue its initiation effect. Order must exist before a provider can authorize payment for it.
3. Call payment-service with attempt-scoped provider idempotency and trusted server amounts. Persist Checkout Session/PaymentIntent IDs and selected account. If the response is uncertain, keep the same attempt and reconcile; do not generate a new order/session blindly.
4. Browser redirects to hosted payment. Use a server-generated allowlisted clean success URL and cancel URL for that order, with no phone, address, thread, credential or arbitrary URL parameter. Preserve legacy WA defaults for old callers. Return page fetches persisted state; it cannot mark authorization/capture.
5. Receive and verify provider events; persist them to durable inbox, acknowledge, then process authorization once. Initialize order acceptance and fulfilment via durable commands regardless of conversation existence.
6. Preserve current initial capture timing: delivery at assignment; collection at finalized pickup time. A directly committed auto-accepted collection can therefore capture soon after authorization. Capture result is recorded independently from transfer and print result.
7. Customer page and receipt distinguish authorized/held funds from captured/paid. Actual provider state determines release versus refund.

This extends ADR0002 with explicit financial ledgers and durable orchestration. Add a proposed/superseding ADR for the changed behavior; preserve history rather than rewrite the accepted ADR. No immediate-capture migration is required for web reach. If merchants choose immediate capture, treat it as a separately approved payment-policy change with a real refund path and test evidence.

### 10.2 Idempotency and concurrency

- Disable Pay visually after click, but enforce idempotency server-side. Key lives with the logical submit operation and survives retries, reloads and tabs. Payment/provider keys must be generated by server or strictly scoped; no arbitrary user key can collide across owners.
- Checkout consumption and row/version lock prevent two orders from one checkout even when tabs use different request keys. Same key/same input returns saved result; same key/different input returns conflict. Persist business deduplication beyond the provider's own idempotency retention.
- Several attempts may belong to an order, but only one can be payable/in progress. Before replacement, confirm older attempt is expired/cancelled/failed and cannot later authorize. Unknown attempt state blocks replacement until reconciled.
- Customer may deliberately create another checkout/order with identical items. Offer a warning if an active similar order exists, with clear “View existing order” / “Place another order” choice. Never prohibit all simultaneous orders by phone or active WA thread.
- Validate event signature/raw payload, allowed event type, provider account, object, expected amount/currency, restaurant and attempt/order metadata. `checkout.session.completed` alone must be interpreted according to payment method and capture mode; verify authorized/capturable amount before dispatch. Support only tested payment methods initially.
- Inbox deduplicates by provider/account/event ID. Order command guard deduplicates authorization even if multiple event types report it. Fetch provider state when event order is ambiguous; no captured→requires_capture regression.
- Durable effects are individually idempotent: init summary, restaurant acceptance notification, capture, transfer, kitchen print, email, WA and progress projection have separate keys/status. Never replay capture to retry a printer or payout.

Stripe's current documentation describes duplicate delivery, non-guaranteed event order, signature verification and asynchronous event handling. Provider idempotency is available but does not replace the database business key. References: [Stripe webhooks](https://docs.stripe.com/webhooks), [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests), [Separate authorization and capture](https://docs.stripe.com/payments/place-a-hold-on-a-payment-method). These are provider design guidance; current deployed Ordelo event wiring is still a blocking verification.

### 10.3 Failure matrix

| Failure | Durable state / next action | Customer and operations behavior |
|---|---|---|
| Order transaction fails before provider | No payable order/session; safe same-key retry | Checkout retained; no charge claim |
| Order exists, provider initiation fails definitively | Attempt failed, order awaiting_payment; controlled replacement | Explain retry; keep snapshot/history |
| Provider initiation times out | Attempt unknown; query/retry same provider key | “Checking payment setup”; do not charge/start another attempt |
| Customer closes browser after authorizing | Provider event processes independently | Receipt/email and recoverable order page; no client callback dependency |
| Browser returns before webhook | Awaiting verified provider result | Poll briefly; show checking; suppress Pay again while unknown |
| Provider authorizes but Ordelo notification delayed | Provider reconciliation finds attempt/order, persist missing event | Pending acceptance accurately; alert if mismatch exceeds SLA |
| Provider authorizes unknown/missing order | Quarantine event, inspect metadata/account; no fulfillment without order | Ops resolves using immutable provider context; release/refund orphan payment under policy, do not invent food items |
| Summary init/restaurant notification fails | Authorization event accepted; durable init/notification effect retries; one summary via unique order key | “Waiting for restaurant”; acceptance deadline enforces release if unresolved |
| Customer address changes in another checkout | Paid order uses its snapshot | No destination change; subsequent order independent |
| Capture succeeds, response/payout fails | Fetch provider status; mark captured; retry transfer separately | Show paid once confirmed; finance alert, no repeat capture |
| Capture fails definitively | Authorization remains valid/failed according to provider; block handover/release policy | Explicit payment problem and operator action, not false paid |
| Capture result uncertain | capture_pending/unknown + reconciliation | Preserve money state; gate food release according to approved operational exception policy |
| Print fails after capture | Print effect retry/manual kitchen fallback | Order remains paid; restaurant needs reliable ticket/support alert |
| Restaurant rejects before capture | Release effect, verify PaymentIntent cancellation | “Order rejected; payment release pending” then verified released |
| Restaurant rejects/cancels after capture | Refund effect + applicable transfer reversal | “Refund requested/processing”; promised amount and time only from approved policy/provider confirmation |
| Late authorization after expiry/rejection | Reconcile and release/refund rather than fulfil canceled order | Explicit canceled/payment-correction status; ops alert |
| Duplicate/out-of-order events | Deduplicate, guard valid transition, reconcile | No duplicate order, ticket, rider job or message |
| Agent unavailable | Core effects continue; WA notification queued/failed separately | Web/email updates and support remain usable |

### 10.4 Reconciliation and operations

Implement a periodic worker scanning uncertain attempts, authorization without summary, accepted orders missing capture effects, capture pending, capture/transfer/print divergence, cancellation/refund pending and dead-letter notifications. Join expected local amounts/order versions to provider authoritative resources. Record repair actions and alerts with safe IDs; no sensitive payloads in ordinary logs.

Proposed operating thresholds, to tune in staging: alert unknown initiation/authorization mismatch after 2 minutes; authorization with no acceptance/summary after 1 minute; capture result unknown after 1 minute; print failure immediately to restaurant/ops; refund/release retry exhausted immediately; overdue fulfilled-order checkpoints use merchant/rider policy. A support queue is required, not just error logs.

Expose provider-state lookup and safe retry commands in payment-service. Add real refunds and transfer-reversal accounting before web orders can enter after-capture cancellation. Existing `cancel_payment` only cancels an authorization; do not label every cancellation a refund. Customer support may start a manual refund as a controlled pilot fallback only if there is an auditable operational procedure, timely owner and reconciled customer status; automate it before scale.

## 11. Secure, optional WhatsApp handoff

### 11.1 Recommendation and value

Offer “Get updates for this order on WhatsApp” after authoritative authorization or later on the order page. Keep “Continue tracking here” equally usable. The benefit is easier transactional updates and customer-initiated support, not automatic marketing identity collection. The web order already has needed contact details; a WA opt-in adds a verified communication endpoint and preference.

Initially ship web ordering without the aggregator if necessary. Leave the WA update CTA disabled/absent until trusted sender validation, attachment mapping and notification routing exist. A generic restaurant WA support link can be offered, clearly labeled as support rather than automatic order subscription.

### 11.2 Prefilled link and proof

The owned order page POSTs to create a 15-minute, high-entropy, business-scoped **correlation challenge**. Prefill: `Please send me WhatsApp updates for my order. Link code: <opaque-code>`. Do not include phone, address, payment intent, thread ID, customer access secret or readable order number. The correlation code alone must not grant order read permission.

Prefer official `wa.me` for fewer third-party processors. If retaining requested `wa.link`, treat its shortener/logging as a data-sharing dependency and verify custom dynamic text/expiry behavior; alternatively use an Ordelo first-party redirect to the business's official WA link. The correlation code is the only short-lived opaque value allowed in that handoff URL, and it is insufficient without additional sender/browser proof. Do not include it in analytics, server access logs or third-party session recording. This is distinct from an order-access bearer token, which never appears in ordinary URLs.

For the initial implementation, bind the challenge to the order's contact phone and destination business/WABA. On trusted inbound message:

1. Verify Meta signature or trusted gateway assertion and restrict direct-origin access. Reject forged ingress before graph/message side effects. Record Meta message ID for deduplication.
2. Hash/lookup code, check expiry, order, issuing browser grant, target business and expected phone; verify sender normalized to that endpoint. A forwarded link from another number does not attach and receives no order details.
3. Atomically consume the challenge and create/reactivate one order_updates subscription, with consent copy/version, verified sender and timestamp. Record a deterministic conversation-order binding.
4. Return current safe order snapshot and latest status, even if order progressed or completed before customer clicked. Do not replay past checkout/restaurant/payment actions.
5. Establish subscription watermark/current order version, then deliver events after it with unique event/subscription keys. Close the snapshot/next-event race transactionally or by rereading version after attachment.

**Mismatched phone:** do not auto-change customer/order recipient. Direct the customer back to the owned browser order page for verified correction or explicit alternate notification-endpoint pairing. Later alternative: create a pending attachment from the new WA sender and require confirmation from the authenticated order browser; only then activate it. The same order/browser proof is required even if the sender already has a WA thread.

**Replay/retry:** consumed code + same proven sender/order returns “already subscribed” and current status; no duplicate subscription, graph initialization or notifications. Consumed code + another sender/business is rejected. Expired code requires a fresh action from an owned browser order page. Rate-limit attempts. Revoke challenge on contact/grant changes. Opt-out deactivates delivery without altering order origin or order processing; re-opt-in records a new authorization/audit event.

### 11.3 Attaching the agent safely

Prefer a **dedicated post-payment entry point** over resuming an unrelated checkout checkpoint. It loads FoodOrder, payment and fulfilment projection from the shared module; validates the subscription/order binding; enters support/progress behavior. Never call create-order, init_delivery/init_takeaway, capture, printer, or restaurant-payment-complete as a consequence of attachment.

| Option | Usefulness / risk | Decision |
|---|---|---|
| Resume existing paid-order checkpoint | Good only when checkpoint belongs to same proven customer/order/business and graph supports explicit resume. Today's callback/current-thread behavior is unsafe to reuse blindly | Optional later with strict binding/version tests |
| Seed new thread then “call payment complete” | Looks easy but current callback triggers conversation assumptions and can duplicate workflow side effects | Reject |
| Dedicated attach_paid_order/order-support entry | Deterministically loads authoritative order and enables post-payment tools without checkout replay | Recommended |

Use one conversation→many order bindings or one order→many historical conversations explicitly. With multiple active orders, show an order chooser; tool calls require a selected authorized order ID. Events route by subscription/order binding, not “latest active thread for phone.” A currently active WA conversation may already be ordering another restaurant/order; do not overwrite its selected order or address silently. Allow a separate aggregator thread or explicit order selection.

New `ordelo-agg-agent` can share underlying post-payment business tools and projection but is a separate future application design. R constitution mandates isolated app runtime/client, restaurant-prefixed routes and app-owned graph adapters for incompatible state/routing. Do not turn the existing single-identity runtime into an arbitrary-rest_ref dispatcher or copy shared modules into an app. Choose a separate aggregator application/repository, WABA identity and authorization model, or an owner-approved constitutional extension; record an ADR. Existing app code is reusable evidence, not permission to violate its invariants.

### 11.4 Current messaging and consent rules — verified 29 September 2026

WhatsApp's official policy requires recipient permission for subsequent contact and respect for opt-outs. A user message opens/resets the 24-hour service window; outside it, approved templates are required. Automated support needs a clear escalation path. Opening a link without sending a message does not establish this inbound-message window or activate the subscription. [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/).

Order confirmations/changes are utility-message use cases; promotional additions need their own messaging treatment. Prepare approved order-update templates, correct business identity and opt-out controls before handoff launch. Account/template approvals and current pricing must be checked for the actual WABA before release. [WhatsApp utility messages](https://whatsappbusiness.com/products/conversation-categories/utility/).

Keep transactional updates separate from marketing permission. The ICO distinguishes administrative service messages from direct marketing, and adding promotional material can change the classification. Use separate affirmative marketing choices; do not infer marketing consent from an order, phone collection or WA updates subscription. [ICO identify direct marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/direct-marketing-guidance/identify-direct-marketing/), [ICO electronic-mail marketing consent guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-direct-marketing-using-electronic-mail/how-do-we-comply-with-the-pecr-electronic-mail-marketing-rules/).

Developer-specific template pages returned HTTP 429 during this investigation; the accessible official policy verifies the window/template/opt-in requirements. Exact template classifications/approved names and deployed messaging controls remain release checks. Do not make a claim about free messaging or current message prices without separate verification.

## 12. Customer tracking, support, and notifications

The order page becomes the durable customer home after payment, including when WhatsApp is unused. Its first-load and refresh fetch current persisted state, not sessionStorage or graph checkpoint.

Show:

- Restaurant identity, address, public phone, opening/support contact information, order reference and fulfilment mode.
- Payment separately from restaurant acceptance: “Checking payment”, “Payment authorised”, “Restaurant reviewing”, “Accepted”, “Paid” only when capture confirmed.
- Confirmed preparation/readiness/assignment/pickup/delivery/collection events, with times and a concise timeline. Do not mark preparation as actual merely from the pickup-time estimate; label inference/expected activity.
- Pickup commitment and delivery range, each labeled estimate/confirmed, last updated and changed-time notice. Rider search is distinct from rider assigned.
- Priced items/modifiers, discounts/charges, delivery address/instructions for the owning customer, receipt/download or print view, payment/merchant summary and cancellation/refund detail.
- Immediate help: restaurant for food/preparation/allergens; Ordelo support for payment, missing/unavailable rider, incorrect order delivery and unresolved issues, with a named operating owner and hours. Do not force support through the LLM.
- WhatsApp subscription status/optional CTA, unsubscribe and web tracking reminder. Email remains independent.
- Late/no-rider/failed-delivery states with next action and support ownership; no fabricated rider ETA. Display “We are checking the delay” only when an actual ops action exists.

Begin with authenticated polling through Next.js. Reuse the admin OrdersView pattern (abort superseded reads, reject older results, keep last good state, visible-tab refresh). Suggested interval: 3–5 seconds while authorization is pending for a bounded period, then 15–30 seconds for active fulfilment; backoff/jitter on failure and reduce/stop when terminal. Immediately refresh on visibility, online/reconnect and return from payment. Show “Last confirmed update…” and “Updates temporarily unavailable” without erasing known state. Page remains readable on slow/mobile connections; full refresh is a fallback.

Use monotonic order version to suppress old responses. Notify on actual status changes without disruptive scrolling; screen-reader live announcements should be concise and non-repeating. A failed poll is not order cancellation. Completed/refunded orders can poll less often but retain receipt/support access.

SSE is a later option if hosting supports persistent connections and capacity: cookie-authenticated stream, per-order authorization, Last-Event-ID replay, reconnect heartbeat, polling fallback. Direct Supabase realtime needs strict order-level authorization/RLS and no server/service key; do not subscribe clients to broad tables. Current shared hosting and polling evidence favor polling initially.

For delivery map/location, authorize via order grant, mask unnecessary rider data, display observation age and consent/operational constraints. Native rider location request is on-demand and not guaranteed continuous tracking. Do not reuse public readable-number map access; a location failure never invalidates the order state. Live map can follow after status tracking unless required by the pilot.

Persist customer notifications separately from business transitions. Email/WA/sms failure cannot roll back an accepted order. Save queued/sent/delivered/failed distinctly; 2xx from a worker or enqueue is not delivered. Avoid duplicate updates when customer uses both interfaces; each active subscription can receive its chosen transactional updates and be revoked independently.

## 13. Practical customer and operational requirements

| Area | Launch requirement | Later enhancement |
|---|---|---|
| Mobile | Clear restaurant/mode/address summary; sticky basket/action without hiding content; keyboard/safe-area support; no forced app install | Installable PWA/push |
| Accessibility | Keyboard/focus management, labeled controls, accessible modifier errors, contrast, large targets, screen-reader price/status announcements, reduced-motion | Broader assistive-device lab coverage |
| Slow/offline | Menu loading/error/retry states, saved non-sensitive basket, prevent ambiguous repeated Pay, recover from interrupted redirects | Offline browse cache with explicit stale labeling |
| Address | Postcode estimate, premises lookup/manual entry, flats/buildings, instructions, clear invalid/out-of-range/service-failure messages | Saved addresses, map pin refinement |
| Menu | Reliable stock and modifier validation, sizes/options, accurate allergens/dietary content and restaurant contact | Search personalization, rich photography |
| Offers/fees | Transparent mode-specific offers and exclusions, minimum basis, complete amount before Pay, consistent receipt/payout arithmetic | Promotion engine, loyalty |
| Contact | Guest name/phone/email purpose notice, verification status, secure recovery | Accounts, verified profiles and merges |
| Payment | Tested manual-authorize/capture, durable retries, return/cancel recovery, release/refund path | Additional provider methods after lifecycle testing |
| Collection | Honest time estimate/commitment, persisted ready and collected actions, no-show/support policy | Scheduled slots and load forecasting |
| Delivery | Address snapshot, capacity/pause, no-rider/failure behavior, proof-of-delivery secret handling | Live route tracking and advanced ETA |
| Support | Staff owner, phone/web/email access, audit, cancellation/refund queue, printer fallback | Shared support inbox, richer self-service |
| Records | Item/fee/consent/policy snapshot, receipt, event/payment audit, retention/deletion procedure | Reordering and downloadable historic accounts |

Allergen information needs to be available before purchase and at delivery under FSA guidance; agree how restaurants keep it accurate and how delivery packaging provides it. Do not infer vegan means allergen-free. [FSA delivery checklist](https://www.food.gov.uk/print/pdf/node/14251), [FSA food/allergen guidance](https://www.gov.uk/guidance/starting-a-food-business#selling-food-for-delivery).

Before launch verify privacy notices, purposes/lawful bases, controllers/processors for Ordelo/restaurants/providers, retention for guest details/addresses/location/checkpoints, financial records and support notes, deletion/export requests, marketing and cookie/analytics choices, and merchant/platform disclosure. These are business/legal decisions needing current verification; this plan does not assert a universal retention period or a generic right to cancel prepared food. Confirm terms, refund policy, tax/receipt requirements and applicable allergen process with the responsible owner/adviser. If selling age-restricted items, defer them or implement verified applicable checks and policies.

## 14. Critical sequence diagrams

### 14.1 Web checkout and authoritative payment processing

```mermaid
sequenceDiagram
    participant C as Customer browser
    participant F as Next.js adapter
    participant O as Ordelo Order Processing
    participant D as Postgres
    participant P as Payment service / Stripe
    participant W as Durable worker
    participant A as Restaurant admin / kitchen
    C->>F: Select restaurant/mode; build basket
    F->>O: Owned checkout, address and item IDs
    O->>O: Catalog + availability + pricing validation
    O-->>F: Versioned quote with expiry and total
    F-->>C: Review full quote
    C->>F: Accept quote; Pay with stable submit key
    F->>O: Payment command with owner/revision/key
    O->>D: Atomic order/items/snapshots/attempt/effect
    O->>P: Create hosted session with provider key
    P-->>O: Session IDs + URL, or uncertain result
    O->>D: Persist provider binding
    O-->>C: Hosted payment URL + clean tracking path
    C->>P: Authorize payment
    P-->>C: Return to clean order page
    Note over C,F: Redirect never asserts payment success
    P->>O: Verified event, via confirmed ingress wiring
    O->>D: Persist inbox, authorization transition, init effect
    O-->>P: Acknowledge durable receipt
    W->>D: Lease init/acceptance effects
    W->>O: Initialize once from order snapshots
    O->>D: Summary + acceptance policy + events
    W->>A: Confirmation/ticket workflow
    C->>F: Poll owned order progress
    F->>O: Customer projection with grant
    O-->>C: Payment, acceptance, fulfilment and support
    Note over O,W: No customer conversation is required
```

### 14.2 Acceptance, capture and failure handling

```mermaid
sequenceDiagram
    participant A as Restaurant / configured policy
    participant O as Order Processing
    participant D as Postgres
    participant W as Durable worker
    participant P as Payment provider
    participant C as Customer tracking / subscriptions
    A->>O: Accept with pickup commitment, or reject
    O->>D: Guard order/version; record acceptance event
    alt Delivery accepted
        O->>D: Dispatch rider search
        D->>O: Verified rider assigned event
        O->>D: Schedule capture effect once
    else Collection accepted / finalized time
        O->>D: Schedule capture effect once
    else Rejected / approved timeout cancellation
        O->>D: Schedule release or refund from actual money state
    end
    W->>P: Idempotent capture / release / refund
    P-->>W: Confirmed result or uncertain outcome
    W->>D: Persist financial fact; reconcile uncertainty
    Note over W,P: Transfer and print retry independently of capture
    W->>C: Deliver event to active subscriptions
    C->>O: Read authoritative current projection
```

### 14.3 WhatsApp attach after payment

```mermaid
sequenceDiagram
    participant B as Owned browser order page
    participant O as Customer Access / Order Processing
    participant D as Postgres
    participant M as Trusted WhatsApp ingress
    participant G as Future aggregator agent
    B->>O: Request order-update handoff with order grant
    O->>D: Store hashed short-lived correlation challenge
    O-->>B: Prefilled link containing correlation code only
    B->>M: Customer sends opt-in message
    M->>O: Verified sender/business/message ID + code
    O->>D: Check order/phone/business/expiry; consume atomically
    O->>D: Subscription + explicit conversation-order binding
    O->>O: Load current authorized order projection/version
    O->>G: attach_paid_order entry with proven binding
    G-->>M: Current status + support options
    Note over O,G: No create-order, payment, summary-init or kitchen replay
    D->>O: Later order events
    O->>M: Deduplicated permitted order updates
```

## 15. Dependency-driven release plan

Each phase is independently reviewable. No deployment is authorized by this planning document. Real-order releases require approved staging/live canaries, operational ownership and monitoring. Do not use successful lint/build/offline tests as proof that provider/WA/authenticated production flows work.

### Phase 0 — evidence freeze and UI prototype

**Repositories:** F fixture-only town discovery, restaurant/mode selection, address/review/tracking mock flows; O planning/contract documentation only. Preserve unrelated working changes. Use current menu components and mobile interaction decisions.

**Schema/API compatibility:** no production schema or business writes. Freeze API examples and migration inventory. Keep existing `/restaurant/[id]`, WA query contracts, address/summary routes and all legacy fulfilment unchanged. Record deployed configuration/SQL/provider wiring gaps in a staging inventory.

**Flags:** `web_discovery_enabled`, `web_ordering_prototype`; prototype hard-disables real checkout endpoints/provider URLs and visibly uses test data. A browse-only public discovery release is possible after factual content/SEO checks.

**Acceptance:** customer can choose town/restaurant/mode, inspect offers/eligibility estimates, enter address, understand fees/times and view simulated successful/rejected/delayed orders. Fixture scenarios prove mobile/accessibility/slow-connection behavior. No fixture Pay can create a real order.

**Monitoring:** browse/menu performance and errors using safe analytics; no payment/conversion claims from fixtures.

**Rollback:** remove/disable prototype/discovery routes; existing WA UI continues. No database rollback.

### Phase 1 — shared identifiers, access and reliability foundation

**Repositories:** O owns new checkout/access/order projection/inbox/outbox models and worker; P gains trusted request/event handling and observable provider resource bindings; F adds authenticated customer API adapter and PII log redaction. R documentation/ADR coordination where contract changes affect shared consumers.

**Migrations:** additive FoodOrder identifiers/origin/rest_ref/snapshots/version, checkout/access/grants, payment attempts/inbox, order events/effects and indexes. Create v2 init paths reading order snapshots; do not rewrite legacy profile address for web guests. Introspect/check constraints first and backfill safely.

**Compatibility:** v1 payloads/paths remain supported; new fields optional for old callers. Legacy events acquire durable keys without changing actions. v2 writes remain disabled. Audit test/debug ingress; make payment/account selection server-owned, removing contact-number privilege for public web requests. Keep active WA threads/inflight orders under creation-time policy.

**Flags:** `web_checkout_enabled=false`, `v2_order_processing_enabled` limited to staging, `durable_payment_events_enabled` under controlled dual-read/single-effect ownership. Never run two workers that both execute the same unguarded financial effect.

**Acceptance:** fake provider and controlled staging events produce one order/event/effect; forged/wrong-account events rejected; private order access cross-user/tenant tests pass; browser grants survive refresh; invalid role headers fail. Worker restart repairs pending work. Existing WA contract/offline and approved live canary pass.

**Monitoring:** inbox backlog/age, effects/retries, authorization-to-summary delay, unauthorized request/rate-limit counts, missing snapshot/ID rows.

**Rollback:** disable v2 new-order writes, retain additive schema/readers and reconciliation for any already-created records. Roll back effect ownership only with a drain/handoff procedure; never replay financial operations.

### Phase 2 — authoritative catalogue, availability, quotes and checkout revisions

**Repositories:** O catalog/pricing/address/availability adapters and quote rules; F revisioned restaurant basket, mode selection, guest address/review and typed errors; external menu/pricing owners add missing contract fields/versioning. R legacy menu-link/session integration where quote data is passed.

**Migrations:** checkout_quote and immutable input/rule versions; optional discovery catalogue mapping. No paid web orders yet.

**Compatibility:** keep legacy minimum/fee paths; v2 quote does not accept client prices/coordinates as authority. Define exact restaurant/menu/alias mapping. Legacy WA baskets gain server-side ownership/session and price validation through a tested adapter; do not assume old query values authoritative. Preserve old links for a bounded compatibility window and redact/scrub queries. New access/handoff flows use explicit exchange endpoints and clean subsequent routes.

**Flags:** `web_quotes_enabled` per rest_ref/mode; live web payment disabled.

**Acceptance:** quote arithmetic reconciles; postcode estimate/final premises boundary cases; min-spend policy signed off; collection/delivery offers and modifiers validated; changed mode/address/version/expired quote blocks Pay; concurrent tab revisions cannot overwrite accepted quote; closed/paused/unavailable service fails closed.

**Monitoring:** quote success/latency/reasons, address lookup errors, stale offer/stock changes, mismatch between displayed and canonical amount, service outage classification.

**Rollback:** disable quote-enabled web checkout; preserve drafts. Existing paid WA processing remains. Do not revert to client-price payment for web.

### Phase 3 — payment lifecycle, return routes and safe fulfilment

**Repositories:** P adds per-channel allowlisted return route selection, attempt idempotency, signature/event verification, provider lookup, capture/transfer/print separation, release/refund support; O processes verified events/durable transitions and v2 summary initialization; F fetches durable payment return state. O SQL/acceptance/rejection/timeout hooks project events before notifications.

**Migrations:** financial operation/refund ledger, unique provider bindings; explicit rejection/cancellation policies and snapshot fields; event-producing trigger/command changes. Capture/readiness/collection commands consume persisted state and authorization; current constrained legacy statuses remain mapped.

**Compatibility:** old payment requests keep static WA defaults. New v2 payment request uses order/attempt, with temporary context ID only if required. Preserve delivery capture at assignment and collection capture at first finalized pickup time. Add an ADR extending ADR0002 for durable financial state/repair. No old inflight order is repriced or assigned a new policy.

**Flags:** `web_payment_enabled=false` until end-to-end staging gate; then internal allowlist per merchant/mode; `web_acceptance_timeout_policy`, `web_collection_auto_accept` explicitly merchant-approved. Flags govern new orders only; paid-order workers never depend on launch flag staying on.

**Acceptance:** controlled payment-service/Stripe test authorization and capture; return-before-webhook; webhook redelivery/order reversal; provider uncertainty; restart; payout/print failure after capture; rejection pre/post-capture; real release/refund reconciliation; closing browser; late payment; no agent running. Exactly one order/ticket/payment/init effect. Independent acceptance deadline and staff escalation tested.

**Monitoring:** attempt/order/provider discrepancies, capture/payout/print divergence, retry/dead-letter age, authorization expiry, refund/release pending, duplicate-effect prevention.

**Rollback:** disable new web payment initiation; leave clean order reads, provider ingress, workers, refunds and support operating for paid orders. Payment-service rollback must retain v2 or compatibility handling until web records drain; old binary lacking new return/refund/attempt behavior is not automatically a safe rollback.

### Phase 4 — complete web tracking and independent customer updates

**Repositories:** F customer order/help page and recovery forms; O progress DTO/authenticated polling, transactional email/subscription delivery, support/cancellation commands; O restaurant/rider event paths publish authoritative updates. Existing R customer-agent callbacks become optional notification effects for subscribed orders rather than an execution prerequisite.

**Migrations:** transactional notification subscriptions/delivery ledger; persisted collection ready/collected events if absent; support requests/audit can use shared order-event/effect records.

**Compatibility:** restaurant portal stays on its tenant APIs; shared UI components may be reused with distinct DTOs. Existing WA customer notifications continue through their bindings. Existing rider/admin WhatsApp operations continue. Web-order operations route to restaurant/rider business callbacks, while customer-agent payment callbacks are skipped unless a real conversation subscription exists.

**Flags:** `web_tracking_enabled`, `customer_email_updates_enabled`, `web_order_recovery_enabled`; all must support paid pilot records even when new checkout disabled.

**Acceptance:** guest refresh/later/new-device code recovery; unauthorized order number/UUID/phone access rejected; no shared cache/SEO leak; waiting/accepted/ready/assigned/pickedup/completed/rejected/released/refunded states accurate; agent outage does not break fulfilment. Customer browser closed still receives essential email. Notification failures retry without duplicate order operations.

**Monitoring:** customer read latency/stale projections, recovery success/abuse, email delivery failures, support response time, overdue orders and missing readiness/collection events.

**Rollback:** keep minimum read-only tracking/recovery/support available for existing paid orders; disable optional map/enhancements. Do not remove order access while orders are active.

### Phase 5 — one-restaurant collection pilot, then delivery pilot

**Dependencies:** Phases 1–4 accepted; merchant policy, support and refund owner established. Prototype alone is insufficient.

**Repositories:** F turn on real public checkout for allowlisted merchant/mode; O/P operational rollout/config only plus remaining pilot fixes; schema already compatible. Do not create special unshared pricing/order logic for pilot.

**Flags:** `web_checkout_enabled` by restaurant + mode; start online-paid collection where direct time policy is agreed, then delivery once rider/no-rider paths are proven. Disable web pay-at-restaurant initially unless verification/abuse/settlement workflow is approved; current WA pay-at-rest remains supported. If delivery is the business priority, pilot it first only after equivalent gate coverage.

**Acceptance:** approved small live canaries through hosted payment, kitchen receipt, acceptance, collection confirmation or rider pickup/delivery, customer email/tracking, support and cancellation/refund. Measure all money/status fields against provider. Test current WA links/active sessions/inflight orders during web activity, including same phone concurrent orders and different destinations.

**Monitoring:** funnel, confirmed authorization/capture, order mismatch, merchant acceptance latency/rejections, prep delay, rider allocation/timeouts, support/refund volume and notification delivery. Review pilot dashboard during operating hours.

**Rollback:** immediately disable new web checkout/payment for affected merchant/mode; keep existing order workers/tracking/refunds and restaurant/rider operations. No destructive migration rollback. Expand only after a defined sample/operating window and owner review.

### Phase 6 — secure WhatsApp order subscriptions

**Repositories:** O Customer Access handoff/subscription/notification routing; F optional order-page CTA/status/opt-out; R add explicit safe post-payment attachment adapter only within approved constitutional contract; P no new checkout behavior required.

**Migrations:** handoff challenges and conversation-order bindings; consent/audit and event watermark. Trusted Meta/gateway configuration verified. If existing validation policy must change, obtain approval for superseding ADR0022 before implementation.

**Compatibility:** existing active conversations and incoming order events retain routing. Subscription attach never reuses payment-context thread as conversation, never reinitializes checkout/summary and never changes web origin. Cross-business/forwarded links rejected.

**Flags:** `whatsapp_order_updates_enabled` per business/WABA; `secure_attach_enabled`. No CTA while backend cannot attach securely.

**Acceptance:** same/mismatched phone, expired/forwarded/replayed code, duplicate Meta message, multiple orders, existing thread ordering another restaurant, before-attach updates, terminal order attach, opt-out/re-opt-in, closed-window approved-template delivery, agent outage. No extra payment/print/admin notice.

**Monitoring:** attach conversion/rejections/replay, consent/subscription changes, window/template/quality failures and notification delivery lag.

**Rollback:** disable new attach; existing subscribed updates continue through compatible deterministic notification worker or clearly reported pause; web/email unaffected. Do not erase consent/audit or change origin.

### Phase 7 — future ordelo-agg-agent and later product features

**Repositories:** new aggregator app/repo or explicitly approved R extension; O exposes only shared order/status/support commands; F discovery/account enhancements; P unchanged unless new payment methods/scheduled orders require work.

**Migrations/API:** optional verified customer profiles/contact mapping, account grants, saved addresses, reordering and scheduling; versioned post-payment entry/selected-order contract. No checkout authority in graph state.

**Flags:** `aggregator_agent_enabled`; gradual support-only then ordering if requested. Separate scheduled/promotions/accounts flags.

**Acceptance:** app identity/runtime/WABA isolation, app-owned graph composition tests, multi-restaurant order authorization, tool permissions, same authoritative rules across channels, old WA apps parity. Changes to shared R runtime release all participating apps from the same revision and roll back together per constitution.

**Monitoring:** graph/tool failure, incorrect order context, support escalation and hallucinated order/payment facts; ordering metrics remain in shared module.

**Rollback:** return WA subscription/status replies to deterministic shared projection and human support; core orders continue. Roll back participating shared-runtime apps together when appropriate, retaining paid-order API support.

### Release controls common to all phases

- Persist origin, policy/rule version and adapter version on new orders, so feature/config changes do not reinterpret inflight orders.
- Use expand/validate/contract migrations, compatibility readers and explicit rollback cut points. Avoid feature-flag branches inside irreversible financial operations.
- Record exact commits/schema revisions and provider configuration for each canary. Verify old and new callers against the same staging deployment.
- Clearly separate mocked/offline verification, provider sandbox tests, authenticated browser tests and approved live WA/payment canaries.
- Rollback disables acquisition/new checkout first; it preserves money reconciliation and customer support until obligations complete.

## 16. Focused test matrix

| Scenario | Required invariant / evidence | Channels/modes |
|---|---|---|
| Direct URL guest | Browse without account/WA, create owned checkout and complete secure order | Web delivery + collection |
| Existing WA deep link | Active legitimate session succeeds; expired/mismatch handled server-side; legacy UI behavior preserved | WA delivery + takeaway/pay-at-rest |
| Same phone simultaneous orders | Independent orders/addresses; no arbitrary profile claim or duplicate-order ban | Web + WA concurrently |
| Cross-restaurant basket | Cannot submit items/options from another catalogue; explicit replacement | All |
| Delivery↔collection change | Offers/fees/minimum/time recomputed, old quote invalidated | All |
| Postcode estimate vs premises | Boundary estimate can change; final address authoritative; manual/flat handling tested | Delivery |
| Quote expired/changed | Payment blocked until fresh accepted quote; same amount/line rounding everywhere | All paid flows |
| Tampered price/discount/minimum/coords | Server derives values; forged client inputs cannot lower payment/evade coverage | All |
| Closed/paused/cutoff/sold-out/capacity | Fail closed at payment; existing paid order support stays open | All |
| Collection time | Estimate versus commitment honest; configured policy has INSERT capture path; adjusted time does not recapture | Collection |
| Double click/reload/two tabs | One order/attempt/session; key mismatch conflict; revision controls | All |
| Legitimate repeat | New checkout can order same basket again; clear duplicate warning only | All |
| Initiation/provider timeout | Same attempt reconciled, no fresh charge until old state known | Online paid |
| Return before event/browser closed | No redirect-authoritative success; independent event processing and recovery | Web + WA online |
| Duplicate/out-of-order webhooks | Single init/capture/print/message; no financial regression; forged events rejected | All online |
| Authorization without summary/notify | Repair worker recovers once or timeout releases; operations alert | Delivery + collection |
| Capture then transfer/print failure | Paid fact preserved; retry only failed effect; no duplicate payout/ticket | Delivery + collection |
| Rejection/timeout before capture | Correct no-dispatch/release path and verified customer copy | Web + WA policy variants |
| Rejection/cancel after capture | Real refund and transfer reconciliation; refund pending/confirmed distinguished | All online |
| Rider unavailable/late/failed delivery | Honest state/support/escalation; release/refund determined by actual money state | Delivery |
| Ready versus collected | No automatic completion from ready/pickup estimate; authorized collection command | Collection |
| Guess order number/public UUID | No private data without grant; generic denied/recovery response | Customer web |
| Recovery/new device | Verified code + rate limits/expiry/revocation; phone alone no historical rights | Customer web |
| Cross-tenant/role forgery/cache/index | No customer/admin permission confusion, service-key leak, shared cache or indexing | Customer/admin |
| WA challenge forwarded/expired/replayed | Same proven sender retries idempotently; other phone/business denied without disclosure | WA attach |
| Existing WA thread / multiple orders | Explicit binding/chooser; no overwrite or wrong-recipient graph invocation | WA attach |
| Updates before attach | Current snapshot + next events once; no missed-race or historical message flood | Web→WA |
| Opt-out/template/window failure | Stop chosen channel only, template fallback correct, web/core processing unaffected | Notifications |
| Agent down/worker restart | Core payment/fulfilment and web tracking continue; durable work resumes | All |
| Mobile/accessibility/slow network | Keyboard/screen reader/long modifiers/safe area/error retry work; no duplicate payment | UI |

Tests target observable command/event interfaces and meaningful concurrency/failure invariants. Reuse current focused tests (`O:tests/watomation/routers/test_order_hooks.py`, `test_payment_hooks.py`, order-management/payment tests and SQL job tests) and introduce controlled transactional tests where needed. F currently lacks a general test framework in its guidelines; add focused API/browser coverage for public checkout rather than relying solely on lint/manual smoke. P provider/receipt tests must assert partial effects, not just HTTP success.

## 17. Monitoring and operational ownership

### Funnel events (no PII)

`town_view → restaurant_view → mode_selected → basket_started → eligibility_result → checkout_started → quote_ready → quote_accepted → payment_attempt_started → payment_authorized → restaurant_accepted → payment_captured → fulfilled`.

Use opaque analytics correlation IDs, restaurant/mode/origin/rule versions and aggregate reasons; no phone/address/email/thread/access/handoff tokens or raw provider payloads. Treat provider-authorized/captured events as server events; do not count redirect as purchase. Measure mobile/webview separately and quantify losses at address, minimum, unavailable service, changed quote and payment.

### Required operational dashboard/alerts

| Measure | Owner / action |
|---|---|
| Provider authorized/captured without matching order/attempt or wrong amount | Payments/ops: quarantine/reconcile/release/refund |
| Authorized order lacks initialized summary or acceptance effect | Order ops: repair then deadline handling |
| Acceptance/rider allocation/capture latency and timeout rates | Merchant + delivery ops: pause service/capacity or escalate |
| Captured but transfer/print incomplete | Finance + restaurant ops: independent repair/manual ticket |
| Overdue preparation/pickup/delivery, missing collected state | Merchant/rider ops: verified action, update estimate/support |
| Release/refund pending age and error | Named refund owner: provider reconciliation and customer update |
| Email/WA template/provider failures, retry age and dead letters | Notification ops: repair channel; no order replay |
| Private access denial/recovery abuse/PII logging violation | Access/security owner: rate-limit/revoke/fix |
| Checkout conversion and quote/service error distributions | Product/merchant owner: improve eligible experience without weakening validation |

Set SLOs and paging destinations before pilot, including outside merchant opening hours for financial issues. Existing overwatch/admin messages are useful operational adapters but must be authorized and must not be the only record of a failure. Assign merchant preparation/food support, Ordelo delivery/payment/refund support, and escalation responsibility explicitly.

## 18. Implementation handoff for another LLM

### Files/services to start from

| Work package | Existing evidence anchors | Proposed changes and dependencies |
|---|---|---|
| Discovery/routes | F:`app/page.tsx`, `app/restaurant/[id]/page.tsx`, `config/restaurants.ts`, `app/api/menu/route.ts` | Add town/canonical restaurant routes and mapping; preserve legacy routes; depends on verified catalogue/restaurant identity |
| Basket/mode/quote UI | F:`MenuContainer.tsx`, `BasketDrawer.tsx`, `contexts/CartContext.tsx`, `AddonCustomizationModal.tsx`, `order-summary/page.tsx` | Restaurant/revision-scoped persistence; stable option IDs; quote review and private checkout; no client price authority |
| Guest address/access | F:`address-update/page.tsx`, postcode/capture routes, `middleware.ts`, `lib/rest-admin-session.ts` pattern; O:`customer_hooks.py`, `order_hooks.py` | New customer access and order-address paths; avoid unverified profile upsert; private grants/OTP recovery and PII redaction |
| Order writer/IDs | O:`order_hooks.py:CreateOrderRequest/create_order`, `order_service.py:create_order_with_items`, `order_db_ops_new.py`, `food_order_pymodel.py`, `food_order.sql` | Deep shared transactional command; additive IDs/origin/snapshots; compatibility adapter |
| Pricing/availability | O:`order_service.py:_call_pricing_service/get_min_order_value`, `food_order_pymodel.py:get_final_order_value`; F:`restaurantHours.ts`; R:`runtime/services/service_hours/` | Server quote, typed eligibility, versioned catalogue/discount policy, service cutoff/pause rules; external pricing/menu owner dependency |
| Payment integration | O:`payment_hooks.py`, `utils_common/payment_ms/payment.py`; P:`internal/transport/http/handler.go`, `internal/stripe/payment.go`, `webhook.go`, payment repository, config | v2 order/attempt contract, return routes, signatures/inbox/idempotency/status/reconcile/refund; verify external wiring before activation |
| Acceptance/fulfilment | O:`resolve_initial_restaurant_acceptance.sql`, `init_delivery.sql`, `init_takeaway.sql`, `summary.sql`, `takeaway_summary.sql`, `inflight.sql`, `delivery_hooks.py`, `takeaway_hooks.py`, callbacks | Snapshot-based init, explicit policy, durable effects/events, reject/refund guards, collection ready/collected; legacy constraints/jobs parity |
| Rider/location | O:`rider_agent.py`, `agent_app_handlers.py`, `delivery_progress.py`, `wa_location.py`, `location_hooks.py`, `dispatch_complete_func.sql`, pickup-alert jobs | Publish canonical events, protect location access, keep rider thread/tool /dontRespond conventions; paid customer thread not required |
| Customer tracking | F:new order page/API; existing `rest-admin/orders/OrdersView.tsx` interaction pattern | Safe customer DTO + polling/recovery/support; never reuse tenant admin data wholesale |
| WA post-payment | R:`runtime/watomation/routers/order_event_hooks.py`, `rider_event_hooks.py`, `runtime/rest_agent/agent_runner.py`, graph adapter/state; O:`config/params.py:WEBHOOK_PATHS` | Explicit attachment/binding and optional notifications; future aggregator composition/ADR; secure sender ingress prerequisite |

### Checklist and guardrails

- [ ] Re-read current instructions, governing constitution and relevant ADRs before implementation; verify commit/working-tree drift.
- [ ] Resolve blocking business questions below; record accepted choices as new ADRs without editing accepted history.
- [ ] Inventory live schema, functions, jobs, RLS and provider/route configuration in approved staging; do not run historical DROP-rich SQL as migrations.
- [ ] Freeze canonical identifiers, origin semantics, money/minimum/rounding and JSON contracts.
- [ ] Produce additive migrations and backwards-compatible adapters; preserve unrelated changes and active/inflight legacy orders.
- [ ] Implement access/authentication and server quote before public real payment.
- [ ] Implement transactional order/attempt writer, durable inbox/outbox and independent reconciliation.
- [ ] Verify capture/release/refund/transfer/print outcomes and provider wiring.
- [ ] Make customer-agent notification optional everywhere, while core admin/rider/summary effects remain mandatory.
- [ ] Implement durable web tracking, independent receipt/update channel, secure recovery and staff support.
- [ ] Run focused matrix, production build, authenticated browser tests, provider sandbox and separately authorized live canaries; label evidence boundaries.
- [ ] Enable one merchant/mode pilot with monitored rollback preserving all paid obligations.
- [ ] Add secure WA attach later; aggregator app is not a dependency for web fulfilment.

**Do not implement during this planning task.** Future implementation LLM must not silently enable payment, deploy, send messages, change WABA/DB configuration, rewrite customer profiles, re-enable WA signature policy, alter capture policy, or merge/deploy changes merely because this document describes them. Follow session authorization and repository rules for each action.

## 19. Consequential questions and explicit assumptions

### Confirmed destination and outstanding policy decision

1. **Confirmed 30 September 2026:** save this investigation as a separate proposal in `OrdeloAgent/plans/ordelo-agg-plan-cc-proposal.md`, preserving the existing plan and decision log. Recommendations in this proposal are not approval to replace their recorded choices or implement application changes.
2. **Web timeout policy:** recommended cancel/release on unanswered manual acceptance, with auto-accept only by explicit configured policy. Alternative preserves current timeout auto-accept. Until answered, this remains the proposed web policy, not an approved change to WA behavior.

### Blocking decisions before real-order implementation/release

| Decision / verification | Recommendation | Why it blocks |
|---|---|---|
| Pricing/menu authoritative deployment and versions | Identify actual deployed writer and adapter contract, supported item/modifier IDs, range/error/minimum semantics | Cannot take money based on client prices or inferred local pricing code |
| Minimum basis/discount allocation and collection offers | Net food after discounts, fees excluded; explicit merchant-specific alternative if approved | Exact charges and payment amount must be agreed |
| Acceptance and directly assigned collection time | Per-mode configured merchant policy with committed prep/capacity rules; otherwise estimate pending manual acceptance | Current global auto-accept affects both modes; web promise must match kitchen ability |
| Timeout/rejection/refund owner | New web cancel/release default; named ops/refund owner; real post-capture refund support | Current delivery/collection behavior differs and cancellation cannot refund captured payments |
| Contact/recovery policy | Guest name/phone + mandatory transactional email at first web launch, no blanket OTP for card checkout | Missing email/SMS recovery cannot support lost browser access and closed-browser updates |
| Provider event wiring and trustworthy webhook ingress | Document and verify deployed chain; durable authenticated provider events | Source does not show payment-service forwarding to Ordelo; unsigned callbacks cannot authorize fulfillment |
| WA sender verification | Verified restricted gateway or owner-approved superseding ADR0022 after credential fix | Secure phone-bound attach cannot trust unsigned payload sender |
| Collection completion and delivery failure commands | Persist authorized ready/collected/failed events and support actions | Tracking must reflect physical progress independently of customer graph |
| Pilot merchant, service capacity, support SLA | One merchant/mode with agreed policy; online collection first if feasible | Operational availability and rollback need a real owner |
| Aggregator business/WABA/runtime ownership | Separate approved app/repo or explicit constitutional extension, post-payment entry first | Existing restaurant app identities are intentionally isolated |
| Privacy/merchant/payment obligations | Verify notices, roles, retention, consent, terms/allergens/refund process with responsible owner | Customer data, legal sales terms and financial support must be defined |

### Nonblocking defaults used in this plan

Town route is discovery context; canonical restaurant page independent of town; one restaurant per checkout; guest accounts optional; ASAP only; authenticated polling initially; no web pay-on-collection at initial pilot without extra abuse/settlement controls; quote TTL 10 minutes; checkout draft 24 hours; order grants 30 days; WA code 15 minutes. All are configurable proposed defaults, not verified current behavior.

### Completion boundary

This plan supplies an evidence-led target architecture, options/tradeoffs, schema, request/response shapes, transition and failure rules, diagrams, tests and reversible releases. Production readiness still requires the explicit live-contract verifications and owner decisions above. The web channel can reach a complete ordering, fulfilment, tracking and support experience before the future aggregator agent is built.
