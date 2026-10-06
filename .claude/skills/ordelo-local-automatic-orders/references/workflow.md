# Running and verifying an Ordelo local order test

## 1. Resolve the requested evidence level

| Path | Entry | What it proves |
| --- | --- | --- |
| Fixture UI | Restaurant frontend town/menu/checkout/order page | Browser behavior and fixture responses; no real database order or Stripe payment |
| R2 real web-origin order | Existing FastAPI Swagger, then Chrome Stripe sandbox | Payment/order/notifier runtime before R3 storefront wiring |
| WhatsApp regression | Existing approved customer flow and rider WhatsApp | Legacy customer/rider behavior with the intended local webhook routing |
| R3 storefront integration | Implemented live town checkout and order page | Browser creates a real web order and consumes real status events |

Inspect current code before selecting a path: R3 can become available after this
skill was written. If the user asks for a whole real storefront journey while
the app is still fixture-only, explain that limitation; do not silently use
Swagger and call it a storefront end-to-end test. An approved R2 run can use
Swagger for order creation and Chrome for payment, as the reference run did.

## 2. Context and startup

Use targeted `rg`/`rg --files` searches from the user-mentioned plan and runbook.
Read the current release gate and local source entrypoints, not just old reports.
Inspect the sibling frontend's relevant routing/configuration files. Batch
independent reads; avoid importing application startup/WA utility examples merely
to inspect data. `aws_setting.py` currently exports `agent_env` and
`get_agent_env`; the older `ordelo_agent_env` example in another skill is stale.

Follow `docs/local-testing-runbook.md` for shell setup. Each Python command needs
an activated repo venv, `PYTHONPATH="$PWD"`, and `.env` loaded through `envLoad`.
Check existing listeners before starting anything:

```zsh
lsof -nP -iTCP:3100 -sTCP:LISTEN
lsof -nP -iTCP:3000 -sTCP:LISTEN
```

Ordelo is 3100; frontend is 3000; 3101 is the separate restaurant-agent backend.
Inspect `~/.cloudflared/config.yml` for the actual tunnel mappings and reuse the
existing tunnel when running. These shared test names normally map to the local
services: `rider-agent-test.ordelo.app` and `restaurant-test.ordelo.app`.

For new processes capture logs from the beginning in unique session files. After
preparing the Python shell, a typical Ordelo terminal command is:

```zsh
set -o pipefail
uv run --active watomation/fapp_ordelo_agent.py 2>&1 | tee /private/tmp/ordelo-local-test-service.log
```

Choose a new filename for each run rather than overwriting another session's
evidence. Start frontend in its own terminal with `npm run dev`, optionally piping
its output to another session log. Record process/session IDs and log paths.
The runbook explains when `--active` is needed for the selected venv.

For an already-running user process, do not restart it just to collect logs.
Check its stdout/stderr using `lsof -a -p <observed-worker-pid> -d 1,2`. If it
writes to a user terminal, use an allowed UI/terminal tool or ask for access to
those logs. Do not read a terminal device stream or treat an old stopped-server
log as the current run. If a terminal app is denied, report the limit and continue
DB/provider evidence; do not bypass the denial through OS automation.

Probe `/docs` on both local and tunneled Ordelo addresses. Menu loading alone
does not prove the frontend uses this Ordelo server; `MENU_API_URL` is independent.
Read the authorized configuration before applying any approved profile from
[configuration.md](configuration.md), and verify provider ingress separately.

## 3. Frontend browser checks and 404s

Inspect `lib/web/mode.ts`, `lib/web/api.ts`, the town catalog and actual route
files. On 2026-10-02 the known fixture UI required
`NEXT_PUBLIC_WEB_ORDERING_MODE=fixtures`; absent/`off` failed closed with 404.
`live` existed as a mode but had no implemented live proxy. ELAS's configured town
was `/town/salisbury`; `/town/orpington` was not a configured town. Restart Next.js
after changing `.env.local`, or rebuild if testing a production bundle.

Exercise discovery, restaurant/menu, item choices, basket, delivery/collection,
address/eligibility, fees and checkout, then the order status/receipt. Check the
surrounding flow requested by the user, including back navigation, mobile layout,
reload and reopening a saved order link. Record actual URL, observed content,
API/runtime mode and whether a DB order exists. Keep fixture bugs distinct from
live payment behavior. One reference fixture run exposed an HTTPS localhost
tracking-link problem; recheck rather than assuming it is still present.

## 4. Computer use mechanics

Use the current `mcp__cua_repl` entrypoint instructions. When Chrome is exposed as
a native app, bind it through `cua.getApp('Google Chrome')`; do not assume a DOM
browser connection exists. Read its returned documentation. After compaction,
call `cua.rewriteDocumentation()` before continuing.

Observe the UI, derive fresh element indices, batch deterministic actions and
get a fresh AX state before deciding again. Native `setValue` worked reliably
for Swagger JSON textareas and Chrome's URL field in the reference run; verify
the complete value before submitting. `typeText` dropped characters on some
attempts and `paste` once pasted unrelated clipboard text. Treat these as
observed failures to verify, not as proof that every future tool version fails.
Do not reuse old accessibility indices or browser coordinates across observations.

Do not use injected browser scripts/network calls to replace requested UI
interaction. API/database checks belong in their purpose-built tools or prepared
Python, separately from browser interaction. Respect current tool review and
handoff requirements. A Stripe sandbox Pay attempt was rejected in the reference
run; the user clicked Pay and then the agent verified the result.

## 5. Prepare one real web-origin order

Confirm the selected restaurant's notifier flag/scope and test-payment eligibility
before creating the order. Confirm the existing schema/RPCs from R1 are available;
R2 requires no migration. Both `origin_channel=web` and `storefront=ordelo` must
be explicit; omitting them defaults to the WhatsApp/direct path.

Create a **fresh** web identity and thread for each order. Mint the W-id using
`new_web_customer_key()` from `utils_common.order_management.customer_keys`.
The format is W plus 11 base32 characters, not a phone number. Through the
database-operations workflow, execute:

```sql
SELECT * FROM public.create_thread('WEB', NULL);
```

Record the returned WEB thread ID and W-id. Do not reuse a WhatsApp customer's
thread or send messages to the W-id. For an approved baseline basket/address,
read the exact `food_order`, singular `order_item`, and referenced
`customer_master` rows. Inspect column definitions/models first. Do not invent
SKU, price, modifications, coordinates, or a customer's private details. A past
order's prices can be reused for an explicitly approved reproduction; use the
current menu for a new-price test.

## 6. Create through Swagger UI

Open `http://localhost:3100/docs` or
`https://rider-agent-test.ordelo.app/docs` in the selected Chrome session.

1. Expand **POST /order-hooks/capture-address**, click **Try it out** and fill
   the complete JSON below with the fresh W-id and approved address. The latitude/
   longitude property names differ from the DB's `lat`/`lon`. Execute once and
   inspect the response/status. This W-id must skip the restaurant address hook.
2. Expand **POST /order-hooks/create-order/{rest_ref}**, **Try it out**, set
   the restaurant path parameter, and fill the complete create JSON. Verify all
   fields before **Execute**. Execute once and record the full/short order IDs,
   thread, returned URL, payment mode and fees. If an execute times out or the
   response is ambiguous, inspect DB by the fresh W-id/thread before retrying;
   create-order is not permission to create several accidental orders.

Address payload template (replace each example/placeholder from approved data):

```json
{
  "recipient": "FRESH_W_ID",
  "rest_ref": "ELAS",
  "house_number": "APPROVED_HOUSE_NUMBER",
  "building_name": null,
  "street_name": "APPROVED_STREET",
  "city": "APPROVED_CITY",
  "postcode": "APPROVED_POSTCODE",
  "latitude": 0,
  "longitude": 0
}
```

Order payload template (replace example items and prices, do not submit literally):

```json
{
  "recipient": "FRESH_W_ID",
  "thread_id": "RETURNED_WEB_THREAD_ID",
  "order_items": [{
    "order_id": "",
    "product_name": "APPROVED_PRODUCT",
    "sku": "APPROVED_SKU",
    "quantity": 1,
    "price": 0,
    "modifications": []
  }],
  "order_type": "delivery",
  "notes": "Local web payment-path test",
  "origin_channel": "web",
  "storefront": "ordelo",
  "test_payment": true
}
```

Expect the response's `payment_mode` to be `test` and the Checkout session ID to
start `cs_test_`. The request flag can be refused, leaving an order in live mode;
stop before payment in that case. For the frontend WhatsApp ordering entry the
test query flag is `?isTest3100=true` (or `&isTest3100=true` when a query exists);
it still passes through Ordelo's eligibility check.

## 7. Pay in Chrome's Stripe sandbox and record the redirect

Navigate to the **entire** `payment_intent_url`, including its `#` fragment.
Dropping the fragment produced "This link is incomplete" in the reference run.
If only a hash was changed on an already initialized page, navigate/reload the
complete returned URL rather than repeatedly creating new orders.

Verify the sandbox/test badge, restaurant/account context, basket and total.
Use generic test details rather than the browser's personal wallet/autofill:
`ordelo-r2@example.com`, card `4242424242424242`, future expiry `12/34`, CVC `123`,
name `Ordelo Test`, and the approved postal code. Choose **Pay without Onelink**
if the page offers a saved wallet, and leave save-information unchecked.
Use current payment approval/handoff rules; if final Pay is denied, ask the user
to click it. Wait for their completion and verify it through Stripe/DB.

Record the destination actually shown in Chrome as well as Stripe's configured
success/cancel URLs. ELAS's fixed success URL was a `wa.me` link resolving to
`api.whatsapp.com/message/...`; this is the plan's deferred redirect gap, not
an order-page return. Do not click through to send the prefilled customer message
merely because a web test redirected there.

## 8. Track runtime evidence at each transition

Use the helper from a prepared OrdeloAgent shell:

```zsh
python .claude/skills/ordelo-local-automatic-orders/scripts/inspect_order.py ELAS-DQFH-22
```

For the authorized ELAS Stripe test account, optional direct provider evidence:

```zsh
python .claude/skills/ordelo-local-automatic-orders/scripts/inspect_order.py ELAS-DQFH-22 \
  --stripe-secret prod/elai/secrets --stripe-key-field stripetestkey \
  --output /private/tmp/ordelo-order-new-snapshot.json
```

The secret name is an ELAS example; resolve the selected restaurant's actual
authorized secret. The script refuses live keys, fetches only intent IDs recorded
against this order, masks phone destinations and saves snapshots with mode 0600.
It has no mutations or automatic retries. Use a new snapshot filename each time.

| Evidence | Authorization | Rider accepted | No rider |
| --- | --- | --- | --- |
| Stripe test PI | `requires_capture`; amount capturable equals order total, zero received | `succeeded`; total received, zero capturable | `canceled`; zero received/capturable |
| `payment_details` | PI stored under SHORT `food_order.order_id` | Same recorded PI | Same recorded PI |
| `payment_event` | One `authorised` event for the provider event ID | Inspect current events; do not assume a capture record exists | Inspect current events; do not assume a cancel record exists |
| `delivery_summary` | One initialized order | Assigned/inflight per current DB contract | `timedout` |
| Customer events | One `payment_authorised` | `rider_assigned:<dispatch_id>` | `no_rider_found`, payload `payment_cancelled=true` |
| Subscription | Active `web_page`, destination null | Same | Same |
| Outbox in R1b | `skipped`, attempts 1, no error | Same for assigned event | Same for no-rider event |

R1b's WebPageAdapter is currently a no-op: it records events, sends no HTTP/WA,
and does not push them onto the fixture order page. Future polling/R3 changes
these expectations. WhatsApp subscriptions use `whatsapp_restaurant`; verify
actual messages against the approved flow instead of expecting web skips.

`food_order.payment_status` remained `requires_capture` even after the reference
capture/cancel succeeded in Stripe. Do not call provider capture/release broken
from that order column alone. Likewise Checkout `payment_status=unpaid` can be
normal for a manually authorized, not-yet-captured session.

Inspect current service logs for the order/event/dispatch IDs when accessible.
Do not claim a restaurant-app access-log audit from skipped outbox rows alone;
state the distinction between the executed routing evidence and external logs.

## 9. Replay, acceptance and natural timeout

For an authorized R2 replay, obtain the actual `checkout.session.completed`
event through Stripe test API and save its exact JSON privately. Match its event
ID and `metadata.orderID` to the recorded order's short ID before posting to the
intended local `/payment-hooks/payment-complete`. Inspect current signature and
inbox requirements; the reference release accepted unsigned replay by plan D23.
Use the same event ID for every replay, never invent a new provider event.

Expect HTTP 200 with `outcome=duplicate`. Compare business state before/after:
one summary, one authorized event and one payment-authorized customer event,
no new delivery initialization/notification. Diagnostic `authorised_duplicate`
records can increase deliberately; that is not a duplicate charge/order.
The reference run performed three sequential replays. Do not treat a concurrently
arriving legitimate rider-assigned event as a replay side effect.

Have the designated rider accept the first order through the normal WhatsApp
callback. If the user accepts it, observe rather than issuing a second acceptance.
Verify Stripe capture directly. Do not fake physical pickup/dropoff solely to
make R2 pass; those stages require the user's requested scope and coordination.

Create/pay a second fresh web order and leave it unaccepted. Read the actual
timeout and scheduler configuration. Timeout requires both the configured age
and exhausted available vehicle attempts. In the reference run global/ELAS
timeouts were five minutes and all four `delivery_detail` vehicle rows reached
`vehicle_type_timedout`; no rider dispatch was created because no rider was free.
Monitor boundedly, keep the user informed, and inspect jobs/HTTP failures if the
deadline passes without transition. Do not manually invoke cancellation, alter
timestamps/statuses, shorten timeouts or disable riders to claim this test passed.

## 10. Restore and report

Follow [configuration.md](configuration.md) for the database, frontend env,
Meta ingress, every Stripe test endpoint, cache refresh and process ownership.
Read back each restoration, and identify active test jobs that still need the
user's normal completion/cancellation. Do not clean up order evidence automatically.

Reference evidence from the original run is in
`docs/releases/ordelo-agg-r2-2026-10-02.md` and
`docs/releases/ordelo-web-fixture-browser-check-2026-10-02.md`.
These are historical examples, not a substitute for observing the next run.
