# Web ordering playground — implementation and proposal explained

Source review: 7 October 2026, current OrdeloAgent working tree. This is a code-based explanation, not a live database or deployment audit. The separate proposal is a design snapshot from 30 September; the accepted plan contains later owner decisions and release reports. Its production claims are historical reports, not independently verified here.

Companion: [interactive playground](web-ordering-playground.html), [architecture map](web-ordering-architecture.html), [separate proposal](../plans/ordelo-agg-plan-cc-proposal.md), [accepted plan](../plans/ordelo-agg-plan-cc.md).

## Start here

Web ordering is a new customer entry and tracking channel into the existing Ordelo order, payment, restaurant and rider workflows. There is no separate `web_orders` order ledger. The customer uses a browser; restaurant admins and riders can still use WhatsApp. A web-only restaurant needs no restaurant-agents customer app.

Three independent dimensions prevent confusion:

| Dimension | Example | Meaning |
|---|---|---|
| Origin | `food_order.origin_channel='web'` | Where the order began; the R1 trigger prevents later mutation |
| Storefront | `food_order.storefront='ordelo'` | Which storefront sold the order; legacy orders default to `direct` |
| Fulfilment | `action='delivery'` or `action='takeaway'` | How food reaches the customer; collection maps to takeaway internally |
| Updates | `order_notification_subscription.channel='web_page'` | Where progress is read; distinct from origin and fulfilment |

The browser is not payment authority. A payment return URL does not authorize an order; the callback and guarded database transition do. Authorization holds funds; capture charges them later. An order can be preparing while its money is only authorized. `requires_capture` is not evidence that capture succeeded.

The separate proposal has phases 0–7. The accepted plan has releases R0–R5 and an interim R3.1. These are different roadmaps, not interchangeable labels. Current source contains R3.1 simplifications; do not copy old rollout flags from historical SQL comments into a new setup.

### Identity: four values that look related but have different jobs

| Value | Owner and lifetime | Do not confuse it with |
|---|---|---|
| Checkout `thread_id` | A `thread` row with `agent='WEB'`, linked to `web_session_meta`, normally two hours | A running customer LangGraph conversation; web checkout never runs an agent |
| Checkout `cust_id` | Synthetic W key in session metadata; used to match the checkout | A customer's phone or the per-order recipient |
| Order `recipient` | A **fresh** W key and `customer_master` row per order, preserving its address | The checkout W key; creating another order generates another recipient |
| `order_id` / `order_number` | Internal payment correlation / public operational reference | Proof of permission to view an order |
| Access token | Random reusable secret; only SHA-256 hash stored; expires 30 days after order creation | A login, customer phone, single-use WhatsApp challenge, or the order number |

A W key is `W` plus 11 base32 characters and fits the old 12-character customer key. The WEB thread is a compatibility record in the real thread table. This differs from the proposal's preferred independent checkout UUID with no conversation row. The fresh order W row isolates a paid order from later address edits in the same browser checkout.

## Walkthrough

The HTML companion lets you choose delivery/collection and step through success, payment-URL failure/retry, late authorization, collection decline and no-rider-found. The walkthrough is an educational simulation; it calls no application, database or provider endpoints.

### 1. Browse and check availability

The frontend chooses restaurant/mode. Next.js proxies `/api/web/*` requests to Ordelo `/web/*` using `X-Ordelo-Web-Key`. Backend restaurant refs are restricted to `common.RESTAURANTS`: ELAS/SFCS in Salisbury; BNAT/CRMS in Orpington. Registry presence is separate from external payment/menu readiness.

`availability.eligibility` geocodes a delivery postcode and quotes the pricing service's car option per restaurant. Collection bypasses geocoding and delivery pricing. A postcode check is an estimate, not the final address. Fresh `restaurant_master.service_hours_json` is evaluated in Europe/London, including yesterday's overnight interval. New orders stop at least 15 minutes before closing, or earlier if the mode's configured cutoff is larger. Missing hours provide no accepting intervals.

For new orders, `{REST}_WEB_ORDERING_PAUSED` blocks checkout. The generic flag reader caches for 60 seconds and treats lookup errors as off: the pause is not strictly fail-closed during a config read failure. Tracking does not consult that pause.

Reads: `restaurant_master`, `ordelo_config`; external geocoding/pricing. Source: [availability.py](../utils_common/web_ordering/availability.py), [feature_flags.py](../config/feature_flags.py).

### 2. Create or resume the checkout

`POST /web/checkout-sessions` requires a proxy-supplied 64-character visitor hash. The router counts attempts in `web_rate_limit` and allows 20 per identity/hour. `web_checkout.start` checks restaurant/town/availability, calls `create_thread('WEB', NULL)`, generates a checkout W key and writes `web_session_meta` with a two-hour expiry.

These thread and metadata writes are separate transactions. `session` validates thread + checkout customer key + expiry; it does not require `thread.is_active=true`. Resume also rechecks availability. There is no one-order-per-thread constraint; up to ten distinct order requests may be created from a checkout.

Writes: `thread`, `web_session_meta`, `web_rate_limit`. Source: [web_hooks.py](../watomation/routers/web_hooks.py), [web_checkout.py](../utils_common/web_ordering/web_checkout.py).

### 3. Capture the complete delivery address

Delivery requires premises, street, town and postcode, with bounded optional instructions. The backend geocodes the full entered address and checks its postcode **sector** against the typed postcode; a different unit postcode within the sector is accepted. It stores normalized text, display address and coordinates in `web_session_meta.address`. Collection requires no address. No customer name or phone is requested.

This is an editable draft until copied during order creation. Frontend coordinates never decide delivery fees. Source: `web_checkout.address`, `availability.geocode`.

### 4. Persist one order for one idempotency key

`POST /web/orders` validates bounds (1–20 lines, integer quantities 1–99, bounded nonnegative unit prices), session restaurant, hours/pause, payment mode, address and total. Delivery minimum spend comes from the pricing service; item names/modifiers/prices are still supplied by the client under accepted decision D8. This is not SKU-based server repricing.

A fingerprint binds the full serialized input and address to `Idempotency-Key`. Transaction A takes a request advisory lock; a new request also locks its checkout and enforces the ten-order budget. It inserts a fresh per-order W customer, allocates a daily sequence, calls `create_food_order_with_items` and inserts `web_order_request` with its address copy. All these changes commit together. `food_order` starts at `requires_payment`, web origin, Ordelo storefront and selected payment mode.

Same key + same input resumes the existing order. Same key + changed thread/input/address gives `409 idempotency_conflict`, subject to session/availability checks that run first. A new key means a new order; one checkout may legitimately have several orders. The client estimate is part of the fingerprint even though it does not set authoritative fees.

Writes: `customer_master`, `daily_seq_last_value` + `daily_seq` sequence, `food_order`, `order_item`, `web_order_request`. Sources: `web_checkout.create`; [R3 migration](../ordelo_datamodels/migrations/ordelo_agg_r3.sql); [order SQL](../utils_common/order_management/food_order.sql).

### 5. Obtain the payment URL after the order commit

Transaction B takes the same request lock. If `web_order_request.quote` exists, reuse it. Otherwise load the persisted FoodOrder and its calculated final amount; call `generate_payment_intent_url` for delivery or `generate_takeaway_manual_payment_url` for collection and save the returned URL/charges/mode/acceptance deadline in the quote JSON.

The existing provider path still uses `/threads/{thread_id}/orders/{order_id}/payment-url` with manual capture. The 35-minute `payment_accept_by` is an Ordelo acceptance window, not Stripe Checkout expiry. Each successful response issues a new page token in `order_access_grant` (including a cached-quote retry).

If URL generation fails, Transaction A remains committed. Retry with the same key/input can resume without duplicating the FoodOrder. Local locking does not prove that an ambiguous external timeout could not create multiple provider sessions. A new secret grant is not a new order.

### 6. Authorize, then initialize fulfilment

Ordelo's `/payment-hooks/payment-complete` parses the event and runs `lifecycle.reject_late` first. An unpaid web order older than 35 minutes, or paid after actual restaurant closure, gets a durable cancellation request and no fulfilment initialization. This uses zero new-order cutoff and ignores the emergency pause for an already-created order. Transient availability errors propagate instead of treating an outage as closure.

For a valid authorization, `record_payment_authorised` inserts `payment_event` under a unique provider event ID and conditionally changes `food_order.payment_status` from `requires_payment` to `requires_capture`. Replays and other invalid states do not schedule fulfilment again. Missing provider IDs use `authorised:<order_id>` as a compatibility key.

Background tasks publish `payment_authorised`, deactivate the WEB thread and call `init_delivery` or `init_takeaway`. These tasks run **after** the database payment commit and are not a universal transactional effect queue. The SQL payment-init reconciler detects paid orders with missing summaries and alerts; it does not blindly rerun initialization.

Ingress remains unsigned by accepted D23. Inbox deduplication protects replays, not authenticity. The wider signed-ingress/provider-verification recommendation in the separate proposal is not implemented by this path.

Sources: [payment_hooks.py](../watomation/routers/payment_hooks.py), [record_payment_authorised.sql](../ordelo_datamodels/jobs_n_functions/record_payment_authorised.sql), [job_payment_init_reconciler.sql](../ordelo_datamodels/jobs_n_functions/job_payment_init_reconciler.sql).

### 7A. Delivery: restaurant, rider, capture, completion

`init_delivery` reads the order-specific W customer and creates delivery state. `delivery_summary` carries restaurant acceptance/pickup/customer details. `delivery_detail` holds per-vehicle options; scheduled dispatching uses `delivery_dispatch` offers. An accepted assignment becomes `delivery_inflight` and triggers the inflight webhook.

The inflight hook starts the rider graph and requests manual capture through the existing payment service. Admin/rider WhatsApp messages are operational workflows; web customer events must not be routed into a restaurant-agents customer app. Rider restaurant code verification marks pickup; customer code verification completes delivery via `dispatch_complete_func`. Customer progress is persisted through the notifier.

No rider found triggers cancellation handling; failed web cancellation queues `web_payment_release`. A web W ID is never a callable customer phone. The rider contact tool explains that no number is stored and uses the operational fallback.

Restaurant decline and timeout are mode-specific shared handlers. Do not infer that every delivery decline uses collection's cancellation path. Existing restaurant timeout behavior can auto-accept; the proposal's default cancel/release-on-timeout policy was not adopted wholesale.

Sources: [delivery_hooks.py](../watomation/routers/delivery_hooks.py), [init_delivery.sql](../ordelo_datamodels/jobs_n_functions/init_delivery.sql), [delivery process](delivery_process.md), [rider_agent.py](../ordelo/agents/rider_agent.py).

### 7B. Collection: pickup time, capture, ready, collected

`init_takeaway` creates `takeaway_summary`. The initial acceptance policy can set a pickup time automatically or wait for admin confirmation. The first finalized pickup time triggers the takeaway pickup-time hook, capture and printing; the insert trigger covers configured auto-accept. Ready for collection and collected are separate customer events/states. There is no delivery dispatch or rider required.

A collection decline records the cancellation result. A failed provider call queues recovery instead of asserting that payment was released. Confirmed capture publishes `payment_captured`. The accepted plan's 6 October handover still reports a payment-service deployment/storage problem for manual collection capture; this review does not verify that it has since been resolved.

Sources: [takeaway_hooks.py](../watomation/routers/takeaway_hooks.py), [takeaway_summary.sql](../ordelo_datamodels/takeaway_summary.sql), [init_takeaway.sql](../ordelo_datamodels/jobs_n_functions/init_takeaway.sql), [takeaway flow](takeaway_flow.md).

### 8. Track through a private customer projection

`order_access.verify` validates the page token, its expiry and order binding. `customer_order_view.get_view` reads FoodOrder, the relevant summary, latest assigned/pickedup/completed dispatch, customer events and release job. It derives display and payment states; there is no stored `display_status` column. Its separate reads are not a single transaction snapshot.

`full` adds item/charge/address/instruction details and the delivery customer code only at rider-assigned/on-the-way stages. Other detail levels omit that block. The router checks grants **before** calling the view and returns private/no-store, noindex and no-referrer headers with ETag support. Direct `get_view` calls are not an authorization check. Backend `/access/exchange` validates the reusable secret and returns the canonical page path; it does not consume a one-use challenge.

The page reads `order_customer_event`. A `web_page` outbox delivery performs no outbound HTTP or WhatsApp send. Persisting an event is sufficient for polling. A completed cancellation job or customer cancellation evidence can show released; captured requires `payment_captured`. A rejected captured order can show `refund_pending`; that label does not mean this module can perform refunds.

### 9. Maintain and audit

The app-owned notifier sweeper runs approximately every 60 seconds: recover unattempted outbox rows, run `lifecycle.sweep`, then `monitoring.sweep`. A failure in an earlier step skips later steps in that iteration.

Lifecycle expiry deactivates WEB threads and deletes rate counters older than two days. It claims up to ten due cancellation jobs with `FOR UPDATE SKIP LOCKED`, schedules a one-minute claim lease and performs cancellation outside the claim transaction. Each release invocation tries delays 0/2/5/15 seconds. Continued failure schedules five minutes later and alerts on job attempts one and three. This is cancellation of a hold, not an implemented post-capture refund workflow.

The price audit claims one `web_monitor_run` per London day, compares the previous 24 hours of order lines against `{ref}_menu` by normalized name and flags prices more than one penny below the allowed discount floor. Unmatched lines also need review. Missing `{REST}_WEB_MAX_DISCOUNT_PERCENT` means 0%. It never corrects a checkout price. Handled exceptions delete an unfinished claim; a process crash can leave a claim that blocks rerunning that day. The one-minute cancellation lease can expire while a slow worker is still running; it is not an end-to-end exactly-once financial guarantee.

## Tables

This inventory covers direct web storage, shared order/payment/notification state and the fulfilment/config/location dependencies. Names and constraints below come from checked-in DDL and code, not live introspection. The proposal-only records appear in the next section; they must not be treated as deployed tables. `delivery_summary` is a table, despite its summary name.

### Direct web tables

| Table | Key / relationship | Purpose and producer/consumer |
|---|---|---|
| `web_session_meta` | PK `thread_id` → `thread`; UNIQUE `cust_id` | Editable restaurant/mode/town/address checkout draft; two-hour expiry; start/address/session |
| `web_order_request` | PK `idempotency_key`; UNIQUE `order_number` → `food_order`; `thread_id` → `thread` | Request fingerprint, fixed address copy and cached quote/payment URL; create/retry and full customer view |
| `order_access_grant` | PK `id`; UNIQUE `secret_hash`; `order_number` → `food_order` | Hash-only page secrets, detail level and expiry; issue/verify. Schema permits `wa_handoff`, but current web code issues only `page_token` |
| `web_rate_limit` | Composite PK `(identity_hash, window_start)` | Hourly session-create counter from trusted proxy hash; router increments, lifecycle prunes |
| `web_payment_release` | PK/FK `order_number` → `food_order` | Durable cancel intent, reason, attempts, next attempt, completion/update times; late guard/failed cancellations enqueue, lifecycle executes, view reads |
| `web_monitor_run` | PK `run_day` | One daily audit claim, completion and flagged order numbers; monitoring |

R3 enables RLS and revokes anon/authenticated access to these six tables. Server-side database access performs the operations. This does not authenticate payment ingress. Source: [R3 migration](../ordelo_datamodels/migrations/ordelo_agg_r3.sql).

### Shared order, payment and notification tables

| Table | Key / relationship | Purpose and producer/consumer |
|---|---|---|
| `food_order` | PK `order_number`; UNIQUE `order_id`; references/correlation include `recipient`, `thread_id` | Authoritative order header, action, amounts, origin/storefront/payment mode/status; web RPC writes, callbacks and fulfilment read |
| `order_item` | `order_id` → `food_order.order_id` (checked-in DDL declares no item PK) | Persisted names/SKU/quantity/unit prices/modifier strings; inserted atomically with order; receipts/view/audit read |
| `customer_master` | PK `cust_id` | Legacy phone-keyed customer storage reused with per-order W rows for immutable delivery address; init_delivery reads it |
| `thread` | PK `thread_id` | WEB compatibility identity and expiry/activity; also real customer/rider threads outside web. No web LangGraph checkpoint is created by checkout |
| `daily_seq_last_value` + `daily_seq` sequence | Per-day sequence allocation via `get_next_daily_seq` | Shared order-number suffix allocation; not a guest identity or permission |
| `payment_event` | PK `id`; UNIQUE `provider_event_id`; FK `order_id` | Authorisation inbox plus late cancel intents/reconciliation alerts. Schema permits further financial kinds, but current capture/release success is published through customer events/jobs; not a full payment_attempt model |
| `order_notification_subscription` | PK `id`; FK `order_number`; unique active order/channel/destination | Web origins get `web_page` with NULL destination; legacy customers use `whatsapp_restaurant`; schema also reserves `whatsapp_agg` |
| `order_customer_event` | PK `id`; UNIQUE `(order_number,event_key)` | Durable semantic progress/timeline, safe payload envelope, timestamps; notifier writes, customer view reads |
| `notification_outbox` | PK `id`; FKs event/subscription; UNIQUE `(event_id,subscription_id)` | Per-subscription dispatch bookkeeping; claim before I/O. Restaurant-app delivery is attempted once; web-page delivery is a no-op |

Sources: [FoodOrder SQL](../utils_common/order_management/food_order.sql), [R1 migration](../ordelo_datamodels/migrations/ordelo_agg_r1.sql), [payment_event.sql](../ordelo_datamodels/payment_event.sql), [notification DDL](../ordelo_datamodels/order_notification_customer_event_outbox.sql), [thread DDL](../utils_common/thread_management/thread_mgmnt_ddl.sql), [master data](../ordelo_datamodels/masterdata.sql).

### Fulfilment and supporting records

| Table or view | Relationship / consumer | Role for a web order |
|---|---|---|
| `restaurant_master` | `rest_ref`; availability and init RPCs | Coordinates, hours, cutoffs, admins and acceptance defaults; registry alone is insufficient |
| `ordelo_config` | `config_key`; flags/URL/policy helpers | Backend URL, emergency pause, test list, discount floor, operational timeouts/defaults |
| `delivery_summary` | Per `order_number`; customer/rider/dispatch links | Mutable delivery and restaurant-confirmation state, pickup time, codes/address; created by delivery init and read by customer projection |
| `delivery_detail` | PK `(order_number,vehicle_type)` | Distance/payout and vehicle-specific assignment candidates; feeds dispatch workflow |
| `delivery_dispatch` | `dispatch_id`, order/rider | Each rider offer/acceptance/assignment/pickup/completion/cancel reason; projection reads latest relevant offer |
| `delivery_inflight` | Active assigned order/rider job | Inflight trigger starts rider graph/capture; ends when job finishes |
| `takeaway_summary` | Per `order_number` | Collection acceptance, pickup time and completion; alternative to delivery summary |
| `rider_master` | `rider_id`; dispatch/agent/view | Rider operations; customer DTO exposes first name only |
| `rider_location`, `rider_location_event` | Rider tracking and zone events | Shared location pipeline supplies nearby events; web view does not directly return raw coordinates |
| `wa_location_request`, `wa_location_observation` | Pending rider request and observation | Supporting rider location verification; not web customer identity or order access |
| `{ref}_menu` | Product `title`/price matches in audit | External menu source and daily monitoring; current checkout does not enforce SKU price authority |
| `v_admin_orders` | View joining order information | Admin visibility; R3 appends origin_channel. Separate admin auth/session tables are not guest access grants |
| `cust_rest_map` | Customer/restaurant relationship | Existing WhatsApp marketing/profile association; this web checkout path does not populate it or grant marketing consent |

Sources: [detail](../ordelo_datamodels/detail.sql), [summary](../ordelo_datamodels/summary.sql), [dispatch](../ordelo_datamodels/dispatch.sql), [inflight](../ordelo_datamodels/inflight.sql), [takeaway](../ordelo_datamodels/takeaway_summary.sql), [location](../ordelo_datamodels/location.sql), [WA location](../ordelo_datamodels/wa_location.sql), [admin view](../ordelo_datamodels/migrations/admin_orders_views.sql).

`payment_details` is reported in the accepted plan as **payment-service storage**, not a new table owned by this web package. Likewise LangGraph checkpoints belong to conversation/rider infrastructure, not browser checkout state. No new browser checkout calls create a customer agent checkpoint.

### Relationship sketch

```text
thread ──1:1── web_session_meta (editable draft, checkout W key)
   └──1:N── web_order_request (key + hash + address + cached quote)
                    └──1:1── food_order (order_number / order_id / per-order W recipient)
                                 ├──1:N── order_item (order_id FK)
                                 ├──1:N── payment_event (order_id FK)
                                 ├──1:N── order_access_grant (order_number FK)
                                 ├──1:N── order_customer_event ──1:N── notification_outbox
                                 ├──1:N── order_notification_subscription ──1:N── notification_outbox
                                 ├──0:1── web_payment_release
                                 └──delivery_summary OR takeaway_summary (workflow linkage)
customer_master(per-order W) ──recipient/customer_id linkage── order/delivery
```

The sketch mixes declared FKs with explicitly labeled workflow linkages; it is not a promise that every legacy relationship has a live FK. The two W keys intentionally differ. A WEB thread can correlate several orders.

## Proposal versus code

The proposal asks how to build a stronger public-ordering foundation. The later accepted plan narrows launch scope and accepts several risks. Read its decision register and ADRs before implementing the proposal literally.

| Separate proposal reference | Recommended design | Current implementation / disposition |
|---|---|---|
| §1, §3: shared authority | One FoodOrder and shared fulfilment, independent web/WA adapters | Implemented direction: same FoodOrder, SQL init, admin/rider hooks; web API adapter and notifier isolation |
| §4–5: identity/thread | UUID guest/customer/checkout; checkout compatibility metadata, no conversation row | Changed by D9/D10/D24 and ADR-0005: W IDs and real WEB thread rows. Nullable/surrogate identity remains later work |
| §5: checkout_session | Dedicated revisioned basket/address/mode lifecycle | Partial analogue: `web_session_meta`; no stored revisioned basket or consumed-checkout uniqueness |
| §5, §8: checkout_quote | Separate immutable versioned quote with integer-pence lines, expiry, rule versions | Partial analogue: `web_order_request.quote` JSON + FoodOrder amounts; no standalone quote table or full input/version model |
| §8, phase 2: authoritative catalogue | Validate SKU/modifier IDs and server prices before payment | Not adopted for launch (D8): bounded client prices + retrospective floor audit. Audit is not checkout validation |
| §5, §10: payment_attempt | Explicit attempts with amount/currency/provider binding and lifecycle | Not present as a table: existing FoodOrder/payment wire + `payment_event` + request quote + release jobs |
| §5, §10: payment_event_inbox | Verified provider/account inbox, signature validation and durable receipt | Partial analogue: `payment_event` unique event IDs + conditional transition; ingress unsigned (D23), no provider/account binding enforcement here |
| §5, §10: order_event/order_effect | Versioned transitions and universal durable effects/reconciliation | Partial: customer event/outbox + financial cancellation jobs; init/capture hooks still use background tasks/shared handlers, not a universal effect engine |
| §6: access and recovery | Browser access session and verified email/SMS recovery | Page grants implemented; no verified-contact recovery. No contact collected; preserve the secret link |
| §6, §12: independent notifications | Email plus optional WhatsApp subscription | Browser page/polling implemented; subscription schema supports channels but no email/SMS send in this path |
| §9: acceptance policy | Snapshot merchant capacity/policy; default timeout cancellation unless agreed auto-accept | Shared configured acceptance and existing timeout handlers retained; not the proposed full policy/capacity reservation model |
| §10: payment redirect/refunds | Per-checkout return routes, verified refunds and reconciliation | Existing payment-service contract retained (ADR-0004); web return redirect deferred (D26); release retries do not implement refunds |
| §11, phase 6: WA handoff | Single-use challenge, sender verification, consent scope and safe agent attach | Deferred R4. `wa_handoff` grant kind and `whatsapp_agg` channel are schema capacity, not completed handoff |
| §12, phase 4: tracking | Authenticated polling from one customer projection | Implemented through grants + customer events + derived DTO + ETag; no SSE/realtime transport in this package |
| Phase 5: pilot release | Verify payment, recovery and service gates before widening | Accepted plan reports R3 deployments and owner delivery/WA tests; collection capture and several operational gates still open as of its 6 Oct handover |
| Phase 7: ordelo-agg-agent | Dedicated post-payment order-bound support agent | Deferred. No web customer agent graph is initialized by this package |

### How to read the release names

| Accepted release | What it means | Related proposal phases, approximately |
|---|---|---|
| R0 | Fixture storefront; no real payment proof | Phase 0 UI prototype |
| R1a | Shared order creation/payment inbox/idempotence foundation | Parts of phases 1 and 3 |
| R1b | Customer events/subscriptions/outbox and routing isolation | Parts of phases 1 and 4 |
| R2 | Existing manual-payment path verified through test orders | A subset of phase 3 evidence; not full web rollout |
| R3 | Guest checkout/address/idempotency, access and polling | Selected pieces of phases 1–5, with explicit decisions/deferments |
| R3.1 / D35 | Remove rollout flags; registry presence + one test-payment list + emergency pause | Operational simplification in later accepted plan, absent from original proposal |
| R4 | Secure WhatsApp handoff and aggregator attachment | Phase 6; deferred |
| R5 | Later identity/catalogue/experience improvements | Remaining recommendations and phase 7; deferred |

This mapping explains intent, not completion of every proposal phase. Source: [accepted plan releases](../plans/ordelo-agg-plan-cc.md), [ADR-0003](adr/0003-web-orders-never-reach-restaurant-apps.md), [ADR-0004](adr/0004-web-payments-use-existing-payment-service-contract.md), [ADR-0005](adr/0005-web-orders-use-synthetic-keys-and-no-contact.md).

## Modules and contracts

### Package responsibilities and callable index

Every function and method in `utils_common/web_ordering` has a docstring, including validators and private helpers. The package has eight modules; `__init__.py` has a module description and no functions.

| Module | Callables | Boundary |
|---|---|---|
| `common.py` | `WebError.__init__`, `utcnow`, `iso`, `query`, `one` | Public error contract; dictionary SQL results, per-call transaction and public search path |
| `availability.py` | `minute`, `opening`, `restaurant`, `available`, `geocode`, `pricing`, `eligibility` | Registry/hours/pause/address/pricing; estimates versus full-address eligibility |
| `web_checkout.py` | `Item.modifications_bounded`, `OrderInput.finite_estimate`, `start`, `session`, `address`, `fingerprint`, `create`, `_accept_by` | Editable checkout → atomic order → recoverable payment URL; caller prices retained |
| `order_access.py` | `digest`, `issue`, `verify` | Hash-only page grants; order-number knowledge never grants access |
| `customer_order_view.py` | `derive`, `get_view` | Pure state interpretation plus authorized-caller read projection; no sends/mutations |
| `lifecycle.py` | `queue_release`, `reject_late`, `sweep`, `release` | Late rejection, expiry and durable cancellation retry; no refund implementation |
| `monitoring.py` | `below_floor`, `sweep` | Retrospective daily price audit; not quote authority |
| `__init__.py` | None | Package purpose |

### Backend HTTP surface

All routes below require `X-Ordelo-Web-Key`; these are server-to-server contracts. Next.js supplies checkout identity from its cookie context; the raw browser need not supply these internal IDs. An order read/exchange additionally needs `X-Order-Access`. Keys and tokens must not be pasted into logs or sample URLs.

| Endpoint | Purpose | Extra checks / result |
|---|---|---|
| `POST /web/eligibility` | Delivery postcode estimates or collection eligibility | UK postcode shape, bounded refs, registered refs filtered |
| `POST /web/availability` | Collection availability without postcode | Registered refs filtered; no delivery geocode |
| `POST /web/checkout-sessions` | New checkout | Visitor hash, 20/hour, restaurant/town/hours/pause; IDs and expiry |
| `POST /web/checkout-sessions/resume` | Validate reusable checkout | Thread/key/expiry and availability |
| `POST /web/address` | Store complete geocoded draft address | Internal thread/customer keys and bounded fields |
| `POST /web/orders` | Persist or retry order, create/cache payment URL | `Idempotency-Key` 16–100 URL-safe characters; quote and access grant |
| `GET /web/orders/{order_number}` | Private status and receipt projection | Order-bound access token, ETag/304 |
| `POST /web/access/exchange` | Validate secret and locate canonical page | Reusable access token in header, canonical page_path |
| `POST /payment-hooks/payment-complete` | Shared authorization callback, outside web router | Unsigned event parsing, late guard, payment inbox; not protected by the web router's server key |

Source: [web_hooks.py](../watomation/routers/web_hooks.py). Frontend behavior is documented in the [integration guide](ordelo-restaurant-frontend-agents.md) and accepted plan; this turn's executable-function scope is the Ordelo web package.

### Customer display and payment state

| Evidence | Customer display | Money state |
|---|---|---|
| New unpaid order, age ≤ 35 minutes | `confirming_payment` | `pending` |
| Still unpaid after 35 minutes | `payment_not_completed` | `not_completed` |
| Authorization, no acceptance yet | `waiting_for_restaurant` | `authorised` |
| Pickup time or accepted/auto-accepted restaurant | `preparing` | `authorised` or `captured` when event confirms it |
| Assigned rider | `rider_assigned` | Independent payment evidence |
| Picked-up dispatch / food_collected event | `on_its_way` | Independent payment evidence |
| Collection readiness | `ready_for_collection` | Independent payment evidence |
| Completion / delivered or collected event | `delivered` / `collected` | Independent payment evidence |
| Rejected, cancellation incomplete, not captured | `cancelled` | `release_pending` |
| Rejected, capture event exists, no release evidence | `cancelled` | `refund_pending` |
| Completed release job or cancellation evidence | `cancelled` | `released` |

Rejection takes precedence over completion in `derive`. The UI state is an interpretation of recorded evidence, not provider reconciliation. These combinations are intentionally more expressive than `food_order.payment_status` alone.

## Gaps and operations

### What this inspection can and cannot establish

Implemented in current source: guest checkout with W/WEB compatibility, per-order address isolation, local order idempotency, access grants, derived tracking, web customer notification isolation, cancellation jobs and daily audit. This documentation change does not alter application behavior, execute migrations, change configuration, send messages or deploy.

The accepted plan's 6 October handover reports successful web delivery capture, order tracking and WhatsApp regression. It still lists manual collection capture as awaiting a payment-service fix/deploy; R3.1 built and owner-tested but its deployment pending/in progress; log privacy, accessibility, business/legal details and monitoring verification remain open. Older 2 October release docs describe previous allowlists/test-on-request rules; use current code for R3.1 behavior. Do not present these historical reports as a fresh production check.

### Current configuration rules

| Control | Current source meaning |
|---|---|
| Backend `RESTAURANTS` + frontend registry/build mode | Web presence is code configuration; no current backend enablement allowlist row |
| `{REST}_WEB_ORDERING_PAUSED` | Emergency block on new checkout/order creation; absent = open; tracked orders remain readable |
| `TEST_PAYMENT_REST_REFS` | Every order at a listed restaurant is test mode, requested or not; lookup failure refuses mode resolution |
| Explicit test request on a live restaurant | Requires permitted overwatch identity; anonymous web key cannot impersonate that phone and gets `test_payment_not_allowed` |
| `{REST}_WEB_MAX_DISCOUNT_PERCENT` | Optional daily audit allowance; absent = 0%; does not price checkout |
| `ORDELO_WEB_KEY` | Matching server secret at frontend/backend, minimum backend length 32; missing/short backend key gives `web_unavailable` |
| `WEB_COOKIE_SECRET`, `NEXT_PUBLIC_WEB_ORDERING_MODE`, `ORDELO_APP_URL` | Frontend session/build/backend routing context; documented in accepted plan and deployment handover |

The old inbox/notifier/late-guard/price-monitor/restaurant-allowlist rollout flags are removed from current R3.1 source. Migration comments and old release notes can still mention them. The generic pause flag's 60-second cache means changes need not be instantaneous.

### Remaining design limitations to remember

- Client-supplied item prices/modifier text are bounded but not authoritatively repriced; auditing detects some problems later.
- Payment callback authenticity is not established by inbox deduplication; unsigned ingress is an explicit accepted decision, not a missing claim in this guide.
- No universal order-effect queue or fully modeled payment attempts/provider sessions; background-task crash gaps and ambiguous external outcomes remain operational concerns.
- Cancellation retry is not a refund workflow; a `refund_pending` display needs operational/provider reconciliation.
- No verified-contact recovery or implemented WhatsApp handoff; possessing the page secret is the current guest access basis.
- Addresses are isolated by per-order rows/snapshots; broader policy/menu/price version snapshots and checkout revision freezing from the proposal are not present.
- Current source includes temporary `DEBUG-addr` logs with entered/geocoded address details. This documentation work leaves them unchanged; they matter to the outstanding production log-privacy check.
- A missing menu table can fail the daily audit; a crashed audit claim and an expired cancellation lease need operational attention. These jobs are bounded recovery mechanisms, not guarantees of exactly-once external effects.

### Agent starting points

Read the matching Markdown guide before making web changes. Inspect current code and the later accepted decision log before copying a recommendation from the separate proposal. Preserve the proposal as a historical alternative. Do not infer live DDL from checked-in migrations or run historical SQL wholesale.

For changes: enter at `watomation/routers/web_hooks.py`, then this package; inspect shared `payment_hooks.py`, `delivery_hooks.py`, `takeaway_hooks.py` and `utils_common/notify/customer_notifier.py` for cross-channel effects. Use [local runbook](local-testing-runbook.md) for shell setup and [web-only onboarding](onboarding-web-only-restaurant.md) for registry/config/provider prerequisites. Focused existing tests: `tests/utils_common/web_ordering/test_web_contract.py`, payment hook/event tests and customer notifier tests. Passing local tests does not establish deployed payment capture, provider ingress or new restaurant readiness.

### Playground artifacts

The HTML is offline and contains the same guide content as this Markdown file plus illustrative scenario controls. Its synthetic examples use no real customer data and perform no network calls. The separate architecture HTML is generated from `web-ordering-architecture.json` with Archify. Source of truth for business behavior remains application code and accepted decisions; the simulation is not executable business logic.
