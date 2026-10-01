# ORDELO ⇄ restaurant-frontend interaction explorer

## Context

You want to add a **website-only ordering channel** alongside the existing WhatsApp channel. Before designing it, you need a precise picture of how ORDELO (the FastAPI WhatsApp/logistics service) and `restaurant-frontend` (Next.js 14) actually talk to each other today.

Nothing in either repo documents the HTTP surface as such. `docs/payment_and_order_flow.md` covers the order/payment slice well but stops there; `docs/delivery_process.md` is the canonical lifecycle doc but is WhatsApp-centric and says nothing about the frontend. There is no endpoint reference anywhere.

Deliverable: **`docs/ordelo-restaurant-frontend-cc.html`** — one self-contained file, no build step, no network deps. Per your answers: flow map **and** API reference; all four portals at equal depth; a layer marking WhatsApp couplings (descriptive — what breaks, not what to build).

## The correction that shapes the whole diagram

**This is not a two-service interaction. It is a triangle, and the third service is load-bearing.**

- `GET /order-hooks/get-active-thread/{rest_ref}/{recipient}` — the "session validation before checkout" you described — is a **pure reverse-proxy**. ORDELO forwards to the *restaurant runtime's* own `thread-hooks/get-active-thread` (`watomation/routers/order_hooks.py:393-420`; path template `config/params.py:78`). ORDELO does not own the session store.
- `POST /payment-hooks/payment-complete` is **not called by Stripe directly** — it is relayed by `restaurant-agents/.../on_message_graph_handler.py:203`.
- ORDELO calls **11 distinct webhook types** back on the restaurant app (`WEBHOOK_PATHS`, `config/params.py:66-78`).

So the flow diagram needs **four lanes** — Browser → Next `/api` → ORDELO → restaurant-agents — with Stripe, the pricing microservice, Google Geocoding and Supabase as side actors. A two-box diagram would be wrong on the single most important endpoint for the web-channel question.

## Build shape

Follow the house style already set by `docs/delivery_process_explorer.html`: dark theme (`#0f172a` / `#1e293b` / `#334155`), top tab bar, left sidebar with layer toggles + "gotchas", click-a-node → right detail panel, bottom copy bar. Match its CSS conventions so the two files sit together.

**Diverge from it in one way:** that file is 82 KB of hand-placed SVG geometry. This one covers four portals plus an endpoint catalogue, so **drive the SVG from JS data arrays** and lay out lanes/rows arithmetically. Hand-placing coordinates at this scale produces errors that aren't visible on inspection.

One array feeds both the Endpoints tab and the node detail panel:

```js
{ method, path, direction,          // 'fe→ordelo' | 'ordelo→rest' | 'db→ordelo' | 'fe→supabase' | ...
  caller_file, caller_line,
  impl_file,  impl_line,
  req, res,                          // shape summaries, not full schemas
  status }                           // 'live' | 'dead' | 'stale-doc'
```

### Tabs

| Tab | Content |
|---|---|
| **Flows** | Four-lane sequence map. Sub-views: Order & Payment · Session & Address · Delivery lifecycle (abridged — links out to `delivery_process_explorer.html`) · Takeaway fork |
| **Endpoints** | Filterable catalogue, grouped by direction. Every row carries caller `file:line` and impl `file:line` |
| **Portals** | Customer · rest-admin · rider · sys-admin — one section each, equal depth |
| **Data** | The identity chain: `recipient` → `cust_id` → `order_number` → `rest_ref`, and which table each lives in |
| **Web-only gaps** | Coupling layer (below) |

## Facts to get right

Each of these is a specific, verified check — they're the parts most likely to be got wrong from memory:

- **Exactly 6 live** frontend→ORDELO calls: `create-order`, `get-active-thread`, `capture-address`, `pay-at-restaurant`, `sys-admin/rider-payout`, `sys-admin/update-paid`. Everything else the frontend fetches goes to Supabase, byteloop (menu), postcodes.io or Google.
- Mark dead/stale explicitly rather than omitting:
  - `postcode-validator` — documented in `ENV_SETUP.md:84,90`, still implemented at `order_hooks.py:307`, but the frontend rewrote `app/api/postcode-lookup/[postcode]/route.ts` to call postcodes.io + Google directly. **Stale doc.**
  - `/takeaway-hooks/init-takeaway-order` — no caller in any repo (`takeaway_hooks.py:600` says so in a comment).
  - `check-rider-allocation-status` — annotated "To Be Deleted" (`delivery_hooks.py:813`) but **live**, called from `restaurant-agents/.../rest_agent/agents/delivery.py:691`.
- **`PAYMENT_COMPLETE` is dead config.** `config/whatsapp.ts:7,12,17` defines a post-payment wa.me link per restaurant, but `getWhatsAppUrl()` is called in exactly one file (`app/address-update/page.tsx:129-130`) and only for `ADDRESS_UPDATE_COMPLETE` / `START_NEW_CONVERSATION`. **Do not draw a payment→WhatsApp arrow.** Draw the dead end: `app/order-summary/page.tsx:132` still carries `// TODO: Redirect to order confirmation page`. For a web-only channel this gap is the interesting part.
- Base-URL cache is **1 hour** (`config/params.py:29`). Both `params.py`'s own docstring and `docs/get_restaurant_webhook_url_async_guide.md` say 5 minutes. Cite the code.
- **`subtotal` / `total` contract drift**: `app/api/checkout/route.ts:94-95` reads two fields ORDELO never returns (`order_hooks.py:290-300`), so `BasketDrawer.tsx:162,183` silently falls back to **client-recomputed** pricing. The total the customer sees is computed in the browser.
- `PayAtRest.order_id` is matched against the **`order_number` column** (`payment_hooks.py:230`) — works only because the frontend happens to send a number (`app/api/pay-at-restaurant/route.ts:46`).
- Customer session = plaintext `(recipient, thread_id)` equality, no HMAC, no cookie. `/api/checkout`, `/api/verify-session`, `/api/capture-address`, `/api/pay-at-restaurant` sit **outside** the middleware matcher (`middleware.ts:186-194`). ORDELO itself has **zero** `add_middleware()` calls and no auth on any hook. Present this as a **trust-boundary layer** on the diagram — it's part of the interaction contract, not a security audit.

## Handling "equal depth" honestly

The real finding for the portals tab is an **asymmetry**, and it should be the headline rather than something to paper over:

- **rest-admin** and **rider** portals never call ORDELO at all. They read Supabase views (`v_admin_orders`, `v_admin_order_items`, `v_admin_orders_daily`) and `delivery_dispatch` directly, through tenant-scoped JS `Proxy` clients that auto-inject `.eq('rest_ref', …)` / `.eq('rider_id', …)` (`lib/rest-admin-session.ts:28-38,348`; `lib/rider-session.ts:23-28`).
- **sys-admin** is the only admin portal touching ORDELO, via the 2 payout endpoints.
- All three receive **magic links minted by ORDELO** from WhatsApp (`rider_auth_session.py:76`, `rest_admin_auth_session.py:47`, `sys_admin_auth_session.py:128`) landing on `/{role}/activate/[token]`. That is the real ORDELO↔portal coupling.

Equal depth = each portal gets its own complete endpoint list including the Supabase-direct calls and the activate paths. Don't invent ORDELO interactions that don't exist.

## Web-only gaps layer

Descriptive only — mark what breaks, don't prescribe replacements.

**Hard blockers (schema/code raises):**
- `create_order_reference()` requires `recipient[-4:]` to be 4 digits or raises `ValueError` — `utils_common/order_management/order_db_ops_new.py:63-81`. Order creation fails before any row is written.
- `customer_master.cust_id VARCHAR(12)` — `ordelo_datamodels/masterdata.sql:49`. Won't hold a UUID or email.
- `food_order.thread_id NOT NULL` — `utils_common/order_management/food_order.sql:40`.
- `init_delivery` raises if `cust_id` isn't already in `customer_master` (`init_delivery.sql:123-125`) and needs non-null `lat`/`lon` (`summary.sql:12-13`).

**Supply-side WhatsApp-only writers:**
- `delivery_dispatch.status = 'accepted'` has **exactly one writer** (`ordelo/agent_app_handlers.py:268-271`), reachable only from the WA callback `/dispatchResponse` (`watomation/on_callback_wa_handler.py:58-137`). No HTTP endpoint accepts a dispatch.
- Restaurant confirm + pickup-time only via WA buttons (`on_callback_wa_handler.py:239-372`).

**Two nuances that must be included or the layer over-claims:**
1. `restaurant_master.auto_accept` + `job_restaurant_confirmation_timeout()` already advance the flow with **no WA tap at all** (`init_delivery.sql:195-202`; `docs/adr/0001-configured-restaurant-auto-accept.md`).
2. The WA address-capture Flow handler is a **stub** returning hardcoded placeholders (`watomation/on_flow_request_wa_handler.py:44-47,69-73`). Real address writes already go through plain HTTP.

Also state plainly: **the customer never receives a WhatsApp message in the delivery flow.** `delivery_summary.customer_msg_id` is nullable and nothing writes it. The customer path is far less WA-coupled than the supply path — colour the layer accordingly (🟢 customer/payment/pricing, 🔴 identity schema, 🟠 supply-side).

## Files

**Created:** `docs/ordelo-restaurant-frontend-cc.html` (the only file this task writes).

**Read while building** — grouped by which part of the HTML they feed:

| Feeding | Files |
|---|---|
| Endpoint impls | `watomation/routers/{order,payment,customer,delivery,takeaway,thread}_hooks.py`, `watomation/routers/{rider,rest_admin,sys_admin}_auth_session.py`, `watomation/fapp_ordelo_agent.py:133-144` |
| Frontend callers | `restaurant-frontend/app/api/*/route.ts`, `components/BasketDrawer.tsx`, `app/restaurant/[id]/page.tsx`, `app/order-summary/page.tsx`, `app/address-update/page.tsx`, `middleware.ts`, `lib/config.ts`, `lib/{rider,rest-admin,sys-admin}-session.ts`, `config/whatsapp.ts` |
| Identity / data tab | `ordelo_datamodels/masterdata.sql`, `summary.sql`, `utils_common/order_management/{food_order.sql,order_db_ops_new.py,order_service.py}` |
| Couplings | `watomation/on_callback_wa_handler.py`, `ordelo/agent_app_handlers.py`, `watomation/on_flow_request_wa_handler.py` |
| Style precedent | `docs/delivery_process_explorer.html` |

## Verification

1. **Citation check (the important one).** The HTML will carry ~100 `file:line` references across three repos; a wrong line number is the likeliest defect and the cheapest to catch. Script it: extract every `path:line` from the generated file, assert the path exists and has ≥ that many lines. Run against `/Users/basavaraj/bloop/OrdeloAgent`, `/Users/basavaraj/bloop/restaurant-frontend`, `/Users/basavaraj/bloop/restaurant-agents`.
2. **Self-contained check.** `grep -E '<(script|link)[^>]+(src|href)=' docs/ordelo-restaurant-frontend-cc.html` → no external URLs. File opens from `file://` with no network.
3. **Endpoint cross-check.** Every entry marked `live` in `ENDPOINTS[]` has both a caller and an impl citation; every `dead`/`stale-doc` entry has a note saying why.
4. **Render check.** Open in a browser: each tab renders, layer toggles hide/show, clicking a node fills the detail panel, the endpoint filter narrows rows. Confirm no horizontal scroll at 1280px.
5. **Count assertion.** The Endpoints tab shows exactly 6 rows under "frontend → ORDELO (live)".
