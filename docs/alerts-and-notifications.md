# Alerts and notifications — who hears what, how and when

Source review: 7 October 2026. Scope: active Ordelo order/customer/rider/admin/operations communication and the restaurant-frontend customer order status page. The neighboring restaurant-agents receivers were inspected to explain WhatsApp customer delivery; they are not changed. Code/DDL inspection is not a live WhatsApp, cron, provider, database or deployment audit.

Companion: [interactive guide](alerts-and-notifications.html). Canonical vocabulary: [Ordelo glossary](../GLOSSARY.md), [frontend glossary](../../restaurant-frontend/GLOSSARY.md). Context: [web ordering guide](../docs/web-ordering-playground.md), [existing domain context](../CONTEXT.md).

## Start here

There are **two main communication paths**, with several direct-send exceptions and supporting flows:

1. Customer progress: an order fact becomes a customer event; the notifier records it, resolves subscriptions and dispatches the customer-facing transport. Web customers read a private status page. WhatsApp customers receive a restaurant-app callback, which can run their conversation graph or send WhatsApp directly.
2. Operations: staff and riders get dispatch offers, kitchen confirmation/receipts, timing reminders, nearby messages and escalation notices. These generally use WhatsApp directly or rider graph tools and do not pass through the customer-notification outbox.

A web order still alerts restaurant admins and riders on WhatsApp. “Web orders never reach restaurant apps” means they never enter the **customer-facing restaurant-agents conversation app**; it does not mean the kitchen or rider stops receiving WhatsApp.

| Recipient | Destination | Owner of routing | What reaches them |
|---|---|---|---|
| Web customer | Private order status page | Ordelo customer projection + frontend polling | Order progress, timeline, payment evidence, receipt and limited delivery details |
| WhatsApp customer | Restaurant's customer-facing WhatsApp app | Customer notifier → restaurant-app callback → receiver/graph | Receipt/progress/customer code, pickup/readiness/completion and other customer updates |
| Assigned/offered rider | Rider WhatsApp number | Dispatch handler or rider graph/tools | Offers, instructions, timing alerts, readiness, pickup-time changes, location request, contact/tracking links |
| Restaurant admins | Restaurant's admin WhatsApp numbers | Ordelo hooks/senders, timing scheduler | Confirmation, pickup choice, receipt, readiness controls, nearby/no-rider messages and timing alerts |
| Overwatch | Configured operations WhatsApp recipients | WALogger / ops alert senders | Inflight/pickup notices, overdue fulfilment, payment reconciliation and price-audit alerts |
| A person requesting access/help | Their browser or WhatsApp response | Access routes / command handlers | Access/error/expiry replies and private dashboard/order links; not a customer lifecycle event |

### Three meanings of “restaurant call”

The owner clarified that “restaurant calls for WA” means the HTTP callbacks to restaurant-agents. The other two meanings below are separated to prevent mixing recipients or transports.

- **Restaurant-app callback**: HTTP request to the customer-facing restaurant app, usually for a WhatsApp order. This is not a telephone call.
- **Restaurant-admin message**: WhatsApp to a kitchen/admin number, for either order origin.
- **Customer support call**: a customer clicks the order page's `tel:` link and calls the restaurant. The browser does not place an automated outbound call or confirm that a call occurred.

The mounted Twilio `/voice` and recording endpoints are a separate voice/recording flow. No automated order-alert call initiation was found in the inspected runtime. Do not infer that Twilio recording endpoints constitute a scheduled restaurant phone-alert system.

## Customer routing

### One event, different recipients

`CustomerOrderEvent` holds `event_type`, deterministic `event_key`, legacy `webhook_type`, payload, optional URL suffix, redirect policy and estimate flag. The customer event is the fact; the subscription and outbox are communication bookkeeping. Neither a HTTP callback nor a WhatsApp reply is the authoritative order state.

`publish` normally runs `_record` in one database transaction under an order advisory lock:

1. Load the FoodOrder and insert `order_customer_event`, unique on `(order_number,event_key)`.
2. Read active subscriptions; repair a missing origin subscription when none is active.
3. Insert one `notification_outbox` row per active subscription, unique on `(event_id,subscription_id)`.
4. After committing, claim each pending, zero-attempt row and select its channel adapter.

`CustomerOrderEvent.data()` preserves the original transport body as `body_json` as well as JSON payload. This avoids JSONB key reordering changing legacy callback bytes. Some internal payloads contain customer/order details; the browser gets a redacted view model rather than the stored envelope. Do not paste those envelopes or access tokens into public logs/examples.

| Subscription channel | Destination | Adapter behavior | Normal outbox result |
|---|---|---|---|
| `web_page` | NULL; customer reads through their grant | `WebPageAdapter` is a no-op; event remains readable | `skipped` — no outbound send is needed |
| `whatsapp_restaurant` | Original WhatsApp customer recipient | One restaurant-app HTTP POST using configured URL/body | `sent` on successful HTTP response; `failed` on transport exception |
| `whatsapp_agg` | Future aggregator destination | No implemented adapter in current notifier | `skipped` with unavailable-adapter explanation; R4 remains future work |
| Inactive/incompatible subscription | No valid current target | No send | `skipped`; incompatible legacy destination/detail gets an explanatory error |

Origin is immutable on FoodOrder. Default routing chooses `web_page` when origin is web **or** the recipient is a synthetic W key; otherwise it chooses `whatsapp_restaurant`. The dispatch guard blocks restaurant-app calls for web origins/W recipients even if a bad subscription asks for one. Legacy restaurant-app delivery also requires destination == original recipient and full detail. The sweep's repair SQL uses origin, while the final dispatch guard still blocks synthetic recipients.

Subscriptions are not marketing consent. The current web checkout has no customer phone. A page event does not become a WhatsApp message, email, SMS or browser push. No customer SSE/WebSocket/service-worker notification transport is implemented in this order-status path.

Source: [customer_notifier.py](../utils_common/notify/customer_notifier.py), [notification DDL](../ordelo_datamodels/order_notification_customer_event_outbox.sql), [web-isolation ADR](../docs/adr/0003-web-orders-never-reach-restaurant-apps.md).

### Event catalog: producers, transports and gaps

The interactive catalog distinguishes active producers from names accepted by the projection. Supporting a label is not evidence that the runtime emits it. “Callback type” below is mapped through `config.params.WEBHOOK_PATHS`; `web-*` types intentionally have no restaurant-app URL and are published on web branches.

| Customer event | Producer / event key | Web customer / WhatsApp customer |
|---|---|---|
| `payment_authorised` | `payment_hooks.handle_payment_complete`; key `payment_authorised` | Page reflects authorization; WA callback `order-payment-complete` with recipient/thread suffix. Receiver sends receipt and runs payment-pending customer graph update |
| `rider_assigned` | `delivery_hooks.post_rider_event_inflight`; key includes dispatch ID or redispatch timestamp | Page gets assigned state/code; WA callback `rider-inflight`, receiver invokes graph update |
| `food_collected` | `agent_app_handlers.post_rider_event_restaurant_cc`; key `food_collected` | Page shows on its way; WA callback `rider-rest-cc` with order/customer suffix |
| `rider_near_customer` | Customer-zone enter in `location_hooks`; key `rider_near_customer` | Page timeline nearby; WA callback `rider-cust-enter`, receiver invokes customer graph |
| `delivered` | `agent_app_handlers.post_rider_event_customer_cc`; key `delivered` | Page completion; WA callback `rider-cust-cc`, receiver schedules completion/release-of-specialist-work sequence |
| `no_rider_found` | `delivery_hooks.post_delivery_timedout`; key `no_rider_found` | Page cancellation evidence; WA callback `delivery-timedout` carries actual payment_cancelled result; receiver checks current order before customer update |
| `pickup_time_set` | `takeaway_hooks._post_pickup_time_event`; key includes pickup time | Page sees time and event; WA callback `order-pickup-time-updated`, redirects allowed. Event estimate flag is true in this producer, while final pickup wording also depends on summary confirmation |
| `ready_for_collection` | `on_callback_wa_handler.admin_takeaway_ready`; key `ready_for_collection` | Page readiness; WA callback `order-takeaway-ready` with order ID, receiver sends a ready-for-collection message directly |
| `restaurant_declined` | **Web** collection **or delivery** decline; key `restaurant_declined` | Page gets verified cancellation result; WA collection and WA delivery declines bypass the notifier and send directly. Delivery decline mirrors the collection path since R1-a (15 Oct 2026) |
| `payment_captured` | Successful **web** delivery/collection capture; key `payment_captured` | Page money evidence; these publisher branches do not implement a WA restaurant-app callback of the same type |
| `payment_released` | Successful **web** cancellation/release; key `payment_released` | Page release evidence; `lifecycle.release` can recover an earlier failed cancellation |
| `restaurant_accepted` | Recognized in backend/frontend catalog; **no current publisher found in scanned runtime** | Preparing can still be derived from summary acceptance/pickup time; do not promise an acceptance timeline row |
| `pickup_time_updated` | Recognized catalog name; **no current publisher found** | Current collection publisher uses a new keyed `pickup_time_set`; changed delivery pickup times notify the rider and can alter the summary projection |
| `collected` | Recognized catalog name; **no current publisher found** | Collection completion can derive from `takeaway_summary.status='completed'`; a catalog label alone does not create a completion command/event |

Additional customer communication that is not an order-event outbox path:

- Pre-order address updates use `notify_address`: skip W keys, otherwise invoke the address callback directly without event/outbox FKs. The receiver acknowledges and runs address confirmation work.
- WhatsApp collection and delivery declines directly send the existing apology/payment-cancellation text (delivery since R1-a). The wording can claim payment was cancelled even after a cancellation exception; web publication records the actual result. This is an existing gap, not a behavior change in this documentation task.
- Customer menu/address/payment/reservation/receipt helper functions exist in `wa_senders.py`; some have no active call sites in this repo. Their existence is not proof of deployed lifecycle coverage.

Sources: [payment hooks](../watomation/routers/payment_hooks.py), [delivery hooks](../watomation/routers/delivery_hooks.py), [takeaway hooks](../watomation/routers/takeaway_hooks.py), [location hooks](../watomation/routers/location_hooks.py), [callbacks](../watomation/on_callback_wa_handler.py), [agent handlers](../ordelo/agent_app_handlers.py), [callback URL map](../config/params.py).

### WhatsApp callback acceptance is not WhatsApp delivery

The inspected restaurant-agents receivers validate restaurant identity, then send directly or schedule customer conversation work. Payment acknowledgment can send a receipt immediately and queue a graph turn. Inflight/pickup/nearby callbacks queue graph work. Collection-ready sends directly. Delivery completion calls the receiver's specialist-release/completion sequence; “release” there means conversation ownership, not necessarily payment release.

Ordelo's outbox knows only the callback outcome. A 2xx can arrive before a background graph turn or customer message completes. There is no customer read-receipt ledger exposed by this notifier. The receiver repository was read to explain this boundary; its deployed version and device behavior were not verified.

Receiver source: [order_event_hooks.py](../../restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/order_event_hooks.py), [rider_event_hooks.py](../../restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/rider_event_hooks.py).

## Rider and kitchen alerts

### Active operational communication inventory

These flows are relevant for both web and WhatsApp order origins unless a specific branch says otherwise. They do not automatically appear in the customer timeline.

| Trigger / notice | Intended recipient | Route / implementation | Delivery and bookkeeping |
|---|---|---|---|
| Dispatch offer | Candidate rider from dispatch payload | `/delivery-hooks/delivery-dispatch` → `wa_send_delivery_dispatch_request_to_rider` | Direct interactive WA accept/decline buttons carrying order/dispatch/rider IDs; scheduled as background work |
| Job assigned / delivery instructions | Assigned rider | Inflight hook → `init_ordelo_graph` → rider tools/handlers | Graph-owned instructions, confirmation flow, location buttons and tracking helpers |
| Missed dispatch | Rider whose dispatch missed | `/delivery-hooks/notify-missed-dispatches` handler | WA notice scheduled, then dispatches marked missed; scheduling/DB marker is not provider delivery |
| Food ready for pickup | Inflight rider still awaiting pickup | Admin receipt “Ready - Notify Rider” → food-ready hook → graph tool | Delivery-progress gate blocks stale taps after pickup/completion/unknown read |
| Pickup time changed | Inflight rider awaiting pickup | Admin +10/+20 callback → summary trigger → `notify_pickup_time_adjusted` | Refreshes graph pickup_time; uses current DB progress and never changes a completed job from a stale button |
| Timing reminders / late delivery | Rider, admins, overwatch on separate schedules | SQL timing ledger → `/delivery-hooks/rider-pickup-alerts` | Detailed below; rider uses graph, admins/ops direct send |
| Request current location | Rider on a valid assignment | `WaLocation` demand/request ledger → rider graph tool | Correlated request and response routing. Without an active rider thread it has a direct native-location prompt fallback |
| Legacy OwnTracks missing/stale location | Rider in payload | `/location-hooks/null-or-outdated-location` | Direct WA reminder only when `legacy_owntracks_prompts_enabled`; otherwise endpoint returns disabled |
| New order awaiting restaurant confirmation | Restaurant admins | Delivery/takeaway restaurant-confirmation hook → `send_restaurant_order_confirmation` | Direct interactive message; current sender exposes Accept while the Decline button stays commented out (D17: Decline is Telegram-only). Accept/Decline and the pickup time are recorded by the shared decision functions (`restaurant_order_decide`, `restaurant_order_set_pickup`); a decline sets `delivery_summary.status = 'declined'` atomically (never dispatchable), cancels the payment and tells the customer. Telegram order cards for linked admins follow in phases 4-5 |
| Admin chooses pickup time | Restaurant admins | Restaurant accept hook → `send_restaurant_pickup_time` | Direct choice buttons; manual and configured-auto policies differ |
| Delivery operational receipt | Restaurant admins | Inflight hook → `admin_order_reciept` | Food receipt, rider, address/code, tracking link; Ready/+10/+20 buttons |
| Collection receipt/readiness control | Restaurant admins | Pickup-time hook → `takeaway_admin_order_receipt` | Receipt/time and Notify Customer ready button; capture/print remain payment workflow |
| Rider enters restaurant zone | Restaurant admins | `location_hooks.notify_rider_location_event`, restaurant enter branch | Direct WA “nearby” notice with restaurant code; customer-zone enter instead publishes customer event |
| No rider found | Restaurant admins | `delivery_hooks.delivery_timedout` | Direct notice suppressed for configured-auto orders; customer no-rider event has separate conditions |
| Restaurant-confirmation timeout | Restaurant admins | Shared delivery/takeaway timeout handlers | Existing timeout auto-accept and admin wording; not the proposal's universal cancel-on-timeout policy |
| Shift availability enquiry | Selected rider list | SQL `enquire_shift_availability` → webhook → background fan-out | `shift_availability` WA template, Yes/No callbacks; no customer order event |
| Admin availability enquiry | Unique admins across restaurants | SQL `enquire_admin_availability` → webhook → deduped fan-out | `alert_order_notification_resolve` template; per-recipient failure isolation |
| Feedback/complaint | Deduped restaurant admins | `/customer-hooks/restaurant-feedback` → `_notify_feedback_admins` | Generates feedback ID and schedules WA fan-out; one recipient failure does not abort the others; no order-event/outbox persistence here |
| Conversation expiry / command response | Actual WhatsApp conversation recipient | Close-thread hook / message & callback handlers | Goodbye, errors, availability/dashboard/live-map/reset replies. Null recipients and WEB threads skipped on closure |

The restaurant owns customer support decisions; the frontend contact button does not create a staff alert. No direct WA order-update message is sent to a web W key. The rider contact tool detects no-number web orders and tells the rider to follow instructions/contact operations; it does not fabricate a customer contact.

Sources: [wa_senders.py](../utils_common/waba_utils/wa_senders.py), [rider tools](../ordelo/agents/rider_agent.py), [delivery hooks](../watomation/routers/delivery_hooks.py), [customer hooks](../watomation/routers/customer_hooks.py), [WA location](../ordelo/wa_location.py), [message handlers](../watomation/on_message_wa_handler.py).

### Rider timing alerts: six independent buckets

All six measure minutes relative to **scheduled `delivery_summary.pickup_time`**, including the picked-up phase. They are not measured from actual food collection. Defaults below are checked-in defaults, not currently verified configuration values.

| Audience | Required phase | Config key | Default offsets (minutes) |
|---|---|---|---|
| Rider | Awaiting pickup | `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` | `-15,-5,2,5,7` |
| Rider | Picked up, undelivered | `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` | `30,45` |
| Overwatch | Awaiting pickup | `rider_alert_to_overwatch_pickup_intervals` | `10` |
| Overwatch | Picked up, undelivered | `rider_alert_to_overwatch_delivery_intervals` | `30` |
| Restaurant admins | Awaiting pickup | `rider_alert_to_rest_admins_pickup_intervals` | `-10,2,7` |
| Restaurant admins | Picked up, undelivered | `rider_alert_to_rest_admins_delivery_intervals` | blank: wired but off by default |

An absent/blank key disables its bucket. The checked-in runbook recommends a two-minute sweep so nearby offsets such as +5/+7 need not collapse; cron installation/running state is not verified here. The SQL file contains historical/destructive scratch statements: do not execute it wholesale as a runbook.

A checkpoint row is keyed by `(dispatch_id,phase,audience,offset_minutes)`. Seeding creates missing rows. Resolution considers live dispatch state, picks the largest due offset per `(dispatch,audience)`, and leaves separate audiences independent. On webhook 2xx, the selected row becomes `sent` and older overtaken rows become `superseded`. Failed/non-2xx POSTs leave them pending for another sweep.

The endpoint returns success immediately and schedules `_process_rider_pickup_alerts`. Python rechecks `DeliveryProgress` before sending, skips stale phase/finished/unknown cases, and prefers the current inflight rider over the payload's old rider. Rider reminders run the rider graph with alert offset/phase/current pickup time. Admin reminders use supplied admin numbers with deduplication and isolated sends. Ops alerts use overwatch. Text calculates actual minutes to/past pickup, not blindly the checkpoint offset.

Moving pickup_time updates the due time and reopens **all** order checkpoints, including previously sent/superseded rows. Phase gates prevent already-picked-up reminders firing as awaiting pickup. Reopening is intentional rescheduling, not failure-retry of a previously sent message.

Example, scheduled pickup noon: at 11:50 restaurant admins can hear “due in ~10 minutes”; at 12:07 rider and admins can each receive their +7 alert; at 12:10 overwatch gets an awaiting-pickup escalation. If still undelivered after collection at 12:30, rider and overwatch have their independent picked-up checkpoints. If pickup occurred late, collapse-to-largest prevents replaying every overdue message.

**Important delivery limit:** ledger `sent` records a successful webhook acknowledgment, not proof that the background WhatsApp operation succeeded. A crash/send failure after 2xx can permanently lose that checkpoint's communication. An ambiguous POST failure can also cause another webhook attempt; the scheduler is not an end-to-end exactly-once messaging system.

Sources: [timing SQL](../ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql), [progress gate](../ordelo/delivery_progress.py), [alert processing](../watomation/routers/delivery_hooks.py), [senders](../utils_common/waba_utils/wa_senders.py).

## Operations and failures

### Overwatch: notices versus escalations

`get_wa_logger` resolves `ordelo_config.overwatch_list`, cached for one hour. `WALogger` prefixes a level marker and fans out to all configured recipients. A normal order-event notice is not automatically a customer event or an incident.

| Operations communication | Source | Meaning / caveat |
|---|---|---|
| Order is inflight | Inflight hook → `notify_overwatch` | Assignment notice via info-level logger; separate from customer rider_assigned event |
| Food picked up from restaurant | Rider restaurant-code tool → logger info | Notice is invoked before the pickup database update in that block; do not treat receipt of the notice as proof the update committed |
| Rider still awaiting pickup / still undelivered | Timing scheduler → `notify_ops_rider_alert` → logger critical | Operations escalation on its own phase/schedule; not sent to the rider by this sender |
| Authorized order with no summary after two minutes | SQL payment-init reconciler → `/payment-hooks/init-reconciler` | Alert-only recovery; logger notice/warning, no automatic fulfilment replay |
| Web hold release still failing | `lifecycle.release` | Alerts on claimed job attempts 1 and 3; cancellation retries have their own durable queue |
| Collection capture requires reconciliation | `takeaway_hooks._notify_capture_reconciliation` | Calls `notify_overwatch` after applicable lookup/capture failures; not proof capture/refund happened |
| Daily web price-floor audit | `monitoring.sweep` | Alerts on unmatched menu products or below-floor prices; optional per-restaurant discount allowance, no repricing |

`WALogger._send` uses `asyncio.gather(..., return_exceptions=True)` without checking individual results. A caller that labels its result “sent” after this await cannot establish each recipient received it. There is no WALogger outbox or durable per-recipient receipt ledger here. Missing/failed overwatch lookup and aggregate call exceptions can be logged, but swallowed recipient failures are not promoted to that level automatically.

Sources: [WALogger](../config/waba_setting.py), [recipient lookup](../config/params.py), [init reconciler SQL](../ordelo_datamodels/jobs_n_functions/job_payment_init_reconciler.sql), [web lifecycle](../utils_common/web_ordering/lifecycle.py), [audit](../utils_common/web_ordering/monitoring.py).

### Persistence and outcome meanings

| Record | Identity / role | What it does not prove |
|---|---|---|
| `food_order` + delivery/takeaway state | Authoritative order/fulfilment/payment correlation | A particular message reached anyone |
| `order_customer_event` | Unique order + event key; progress fact and envelope | That a callback was attempted or customer viewed it |
| `order_notification_subscription` | Active destination/channel/detail rule | Marketing consent or proof of message delivery |
| `notification_outbox` | Unique event + subscription, attempts/status/error | Customer WhatsApp receipt or read state |
| `rider_pickup_alert` | Dispatch + phase + audience + offset checkpoint | Actual rider/admin/overwatch message delivery after webhook 2xx |
| `web_payment_release` | Durable cancel intent, retry schedule/completion | A general messaging outbox or implemented post-capture refund |
| `web_monitor_run` | Daily price-audit claim/completion | End-to-end alert delivery to overwatch |
| `wa_location_request` + observation | Correlated rider location demand/result/prompt | Delivery of unrelated customer events |
| `ordelo_config`, `restaurant_master`, `rider_master` | Recipient/policy/schedule and operational identities | Deployed cron/job/API reachability |

| Outcome label / action | Precise current evidence |
|---|---|
| Event recorded | Customer fact committed or fallback REST insert succeeded |
| Callback accepted | Target HTTP endpoint returned a success response |
| Outbox `sent` | Restaurant-app POST succeeded; downstream graph/message can still fail |
| Outbox `skipped` | No outbound action: web-page no-op, inactive/incompatible subscription or unimplemented adapter; inspect channel/error |
| Outbox `failed` | HTTP exception or a claimed attempt interrupted long enough for the sweep to mark failure |
| Timing checkpoint `sent` | Alert webhook returned 2xx and scheduler marked the row; background send is later |
| Direct WA send returned | Sender accepted the request; inspect actual returned provider data if needed, not generic wrapper wording |
| Message delivered/read | Requires provider-specific delivery/read evidence; the documented ledgers do not store this proof |
| Order delivered | Food fulfilment completed; this is not a message delivery receipt |

### Retry policies are intentionally different

| Path | Recovery behavior | Tradeoff / limitation |
|---|---|---|
| Customer event recording | Pool transaction; on error, REST upsert of the event with ignore_duplicates | If both fail, logs manual reconciliation; publish normally suppresses errors rather than failing fulfilment |
| Missing subscription/outbox | App-owned sweep about every 60 s repairs from committed events | Repairs communication intent without re-emitting order state |
| Unattempted restaurant-app callback | Sweep handles pending attempts=0, up to 100 selected rows | Progresses committed-but-unattempted work |
| Attempted/ambiguous restaurant-app callback | **No retry**; stale claimed pending rows become failed after five minutes | At-most-once attempt favors avoiding duplicated conversation/message side effects over guaranteed update delivery |
| Web-page update | No send; browser polls event/state projection | Event may exist while page closed; no push or reader acknowledgement |
| Rider timing scheduler → webhook | Non-2xx leaves checkpoints pending; 2xx marks accepted checkpoints | Background send can fail after acknowledgment; no durable per-recipient send repair there |
| Direct admin/rider/feedback messages | Call-specific background/recipient isolation; no common durable outbox | Immediate success often means scheduled work, not completed delivery |
| WALogger fan-out | Concurrent best effort, swallowed recipient exceptions | “Sent” wrappers may overstate recipient outcomes |
| Web cancellation | Durable release jobs; up to four calls at delays 0/2/5/15 s per invocation, later five-minute reschedule | Financial recovery, not restaurant-callback retry or post-capture refund |
| Browser polling | Visible/hidden cadence, network-error backoff and last-known display | Retry read requests; never retry creating/capturing/cancelling an order |

The notifier is always enabled in current R3.1 code. Older release notes mention rollout flags/pilot lists; those are history, not current configuration requirements. No legacy direct restaurant-app fallback is used if persistence/dispatch fails, because it could duplicate or leak updates.

Historical policy rationale is recorded in [ADR-0006](../docs/adr/0006-customer-notifications-at-most-once-callbacks.md). The existing implementation records event keys, subscriptions and attempts; it is not a universal event-sourced order/effect engine.

## Frontend order status

### Live path and ownership

Browser `/town/{town}/orders/{orderNumber}` → server page → `getOrderView` → Ordelo `/web/orders/{order_number}` → token verification → customer projection. Later browser reads use `/api/web/orders/{orderNumber}`, not direct database or browser-to-Ordelo calls.

The page reads an HttpOnly order-access cookie. Live API calls require the actual order token; lookup/status-only flows are fixture-only at launch. In live mode, knowing an order number, recipient or phone is insufficient. An inaccessible order shows saved-link/device guidance. `/o/{token}` exchanges the private saved-link token for access and redirects to a clean canonical page. `SaveOrderLink` fetches from a cookie-guarded API and warns that link possession exposes full details.

The Next.js server adds `X-Ordelo-Web-Key` and `X-Order-Access`; browser code does not receive backend credentials. Ordelo verifies token expiry/order binding before constructing the view. The backend returns private/no-store, noindex and no-referrer headers; the Next.js route's own private headers contain no-store/noindex. Backend and Next.js compute their own ETags from their view representations; the browser's If-None-Match is compared at Next.js after it obtains the view, so browser 304 does not imply the backend read was avoided.

Sources: [server order page](../../restaurant-frontend/app/%28web%29/town/[town]/orders/[orderNumber]/page.tsx), [browser status API](../../restaurant-frontend/app/api/web/orders/[orderNumber]/route.ts), [server API client](../../restaurant-frontend/lib/web/api.ts), [backend view](../utils_common/web_ordering/customer_order_view.py), [backend access](../utils_common/web_ordering/order_access.py).

### Polling cadence and terminal exceptions

| Condition | Current OrderPage behavior |
|---|---|
| Active order, visible tab | Schedule read every 15 s; no automatic push |
| Hidden tab | Next scheduling interval is 60 s; hiding does not immediately replace an already queued timer |
| Tab becomes visible | Schedule an immediate read |
| Network/server error | Keep last view, display offline/retrying banner, waits 15 → 30 → 60 s (capped at 60) |
| HTTP 304 | Clear failure/offline state, keep current view, update last-checked time |
| HTTP 200 | Replace view, store ETag, announce **display-status changes** through polite aria-live; timeline-only changes need not announce |
| HTTP 401/403 | Reload to show access guidance; do not invent an update or clear actual order state |
| Cancelled/delivered/collected | Stop only when money is not `release_pending`/`refund_pending` |
| `payment_not_completed` | Read at 60 s until 24 h after placement, unless pending financial state keeps polling alive |
| Time-based lateness | Local clock reevaluated every 30 s without a network call |

`PaymentReturn` is a separate component: read immediately and then every two seconds; after 60 seconds show slow-confirmation wording but continue polling. Access 401/403/404 stops with guidance. It navigates when the view leaves confirming_payment and clears the basket on the relevant successful transition; it never authorizes a payment. Its existence does not prove the provider's fixed restaurant redirect lands there.

Source: [OrderPage.tsx](../../restaurant-frontend/components/order-status/OrderPage.tsx), [PaymentReturn.tsx](../../restaurant-frontend/components/ordelo/PaymentReturn.tsx).

### What the customer actually sees

- Status header and delivery/collection progress steps derived from `display_status`.
- Payment wording based on recorded payment evidence, independent of food progress; authorization is a hold, capture a charge and release is not a refund.
- Newest-first timeline from the redacted customer-event list, plus placed_at. Catalog recognition does not create a missing event row.
- Full-detail receipt/address/instructions. Delivery code appears only at the permitted stage; rider first name appears during assigned/on-the-way, not a raw rider number or live coordinates.
- Last updated is the projection's data timestamp; last checked is the browser's most recent successful check. They answer different questions.
- Save-link UI; support/call restaurant and optional configured email. Current Ordelo projection sets WhatsApp support unavailable; no automated customer WA opt-in/handoff is wired here.

The backend projection reads several rows separately, not one database snapshot. It prioritizes cancellation/release evidence and distinguishes `release_pending`, `refund_pending` and `released`. A recognized state does not prove an unimplemented refund operation ran.

### Lateness display does not send an alert

`lateness` ignores missing/estimated pickup times. Preparing/rider-assigned becomes late beyond pickup +20 minutes. Delivery preparing/rider-assigned/on-the-way becomes very late beyond +60 minutes. Collection has no analogous very-late branch. Very late makes restaurant help prominent.

The “Running a little late — the restaurant has been notified” banner is **display copy**, computed from local time and order state. This component does not send a restaurant message or verify a notification outcome. Backend timing alerts are an independent schedule and can be disabled, skipped by phase or fail. That wording is stronger than the frontend can prove; this task documents it without changing product behavior.

Source: [status.ts](../../restaurant-frontend/lib/web/status.ts), [help card](../../restaurant-frontend/components/order-status/RestaurantHelpCard.tsx), [timeline](../../restaurant-frontend/components/order-status/OrderTimeline.tsx).

## Language and review

### Shared vocabulary and old names

| Use in conversation/docs | Meaning | Existing code or ambiguous name |
|---|---|---|
| Customer event | Persisted customer-relevant order fact | `CustomerOrderEvent`, `order_customer_event`; not every order event is published here |
| Customer notification | Customer-facing communication/presentation of that fact | Page update or restaurant-app→WA path, not necessarily a push |
| Operational notice | Informational staff/operations communication | Inflight/pickup logger notices; not every notice is an alert |
| Operational alert | Condition asking operational attention | Rider timing escalation, payment reconciliation, missing summary |
| Rider timing alert | Phase/audience/offset-based operational alert | Legacy `rider_pickup_alert` also includes post-pickup and non-rider audiences |
| Restaurant-app callback | HTTP to customer-facing WhatsApp service | Do not say “called restaurant” when meaning staff phone/message |
| Restaurant-admin message | WA to staff | Not the restaurant app, and not a web customer notification |
| Customer support call | Customer-initiated phone help | `tel:` link, not outbound alert automation |
| Callback accepted | Success response from the next HTTP system | Current outbox/checkpoint may name this `sent` |
| Message delivery evidence | Provider confirmation for a recipient | Not present in these ledgers; do not infer from accepted/scheduled work |
| Order delivered | Food reached the customer | Distinct from a notification/message being delivered |

The owner agreed on 7 October 2026 to separate accepted, sent and delivered. Callback accepted means the HTTP recipient acknowledged the request; message sent means the messaging sender accepted it; delivered needs recipient delivery confirmation. Neither means read.

The domain glossary is deliberately free of table/API details. `CONTEXT.md` keeps implementation context, and this guide maps vocabulary to current names. No database columns, enums, route contracts or application symbols were renamed.

### Evidence-driven questions and known gaps

- Resolved with the owner: “restaurant calls for WA” means restaurant-app HTTP callbacks, not telephone calls.
- Resolved with the owner: distinguish accepted callback, sent message request and confirmed message delivery. Existing ledger labels remain unchanged; reports must state which evidence they actually record. Changing stored labels or adding provider receipts is separate work.
- Should the WhatsApp collection-decline direct send eventually use a compatible durable customer-event adapter? Current centralization is incomplete and its payment wording can overclaim cancellation success.
- Should the lateness banner say the restaurant “has been notified,” or limit itself to the lateness it can prove? Backend alert outcomes are not supplied to this page today.
- Should the timing ledger mark completion after sender execution, with durable per-recipient recovery? Current 2xx-before-send means at-least-once webhook submission does not guarantee message delivery.
- What should happen when WALogger partially fails? Recipient exceptions are swallowed; operations reporting is best effort.
- Are restaurant_accepted/pickup_time_updated/collected meant to be emitted timeline events or just allowed view vocabulary? Three supported names have no publisher in the scanned runtime.

These are exposed as gaps/questions, not silently “fixed” or claimed approved architecture changes. The two guides document the same cross-project system; owning source links resolve from each repository's copy.

### Source inventory and change boundary

Active order notification source: `utils_common/notify/customer_notifier.py`; shared payment/delivery/takeaway/location/customer routers; callbacks; rider tools/agent handlers; `wa_senders.py`; `WALogger`; timing/reconciler/availability SQL; `WaLocation`. Frontend: OrderPage/StatusHeader/OrderTimeline/RestaurantHelpCard/SaveOrderLink, payment return, status/types, server API and access routes.

Existing helpers `admin_delivery_driver_nearby` and `admin_delivery_complete_notification` use placeholder REST_MASTER and have no active call site found; nearby staff communication uses the location router instead. Menu/reservation/example/import-side-effect tools, exploratory `ai_rnd`, scratch SQL/notebooks and generic chat responses are not asserted to be production alerts. Kitchen printing/payout is an external payment effect, not a customer message receipt. Frontend rest-admin operational order reads are separate from the guest status-page notification channel.

Documentation work: paired offline HTML/Markdown guides in both repositories, canonical glossaries, corrected context and a retrospective ADR for the already-chosen callback retry policy. No live recipients, customer data, credentials, migrations, messages, phone calls or deployments are changed.

### Documentation verification

- Existing focused notifier, notification contracts, WA sender, delivery-progress and web-ordering tests: **122 passed**. These are local contract checks, not evidence of delivered customer messages.
- Offline guide JavaScript parses; **44 source links** resolve in each repository copy. Customer routing, all event choices, callback failures, phase/offset behavior, financial polling exceptions, filters, chapter navigation and themes passed **91 browser checks**.
- Responsive inspection: all six chapters fit the page width at 1440 and 390 pixels; long tables have their own horizontal scroll. The embedded map renders. Light/dark desktop and phone screenshots were inspected. Vertical scrolling is intentional; no accessibility score is claimed.
- Architecture generated from [alerts-and-notifications-architecture.json](../docs/alerts-and-notifications-architecture.json), embedded verbatim in each HTML. Archify validation: **9/9 showcase checks, zero errors/warnings**. Automated browser containment/readability checks passed at 1440×900, 1600×1000, 1920×1080 and 2048×1320; final light/dark screenshots were inspected.
- Runtime contracts, SQL, recipients and deployed state are unchanged by this task. Unrelated edits in both worktrees are preserved.

Architecture receipt (applies to the embedded standalone map, not the entire guide):

```text
diagram_type: architecture
specification_sha256: a84b67221a092b3e22eca91d70dfaf283fc3649503e635b5d3141707fb112549
artifact_sha256: 8f7509139a40ada82a20b57f687a3e4a8082b9461239fe23f27fcbefc219355c
specification_bytes: 2617
artifact_bytes: 705640
validation: 9/9 showcase, 0 errors, 0 warnings
browser_evidence: passed
visual_review: passed
correction_rounds: 1
```

Browser receipts/screenshots are local temporary evidence under /tmp. The root glossaries capture the terms resolved in the owner-approved direct interview, and ADR-0006 records the existing at-most-once restaurant-callback choice rather than inventing a new policy.
