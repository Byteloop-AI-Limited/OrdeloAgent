# Plan: order tracking page for WhatsApp orders (OrdeloAgent + restaurant-agents + restaurant-frontend)

Written 2026-10-08. Decisions agreed with the owner in a grilling session (Q1–Q8 below).
Origin: investigation of ELAS-JRFR-20 / ELAS-AAUS-21 and the follow-up question "does the order page work for WhatsApp orders?".
Chat: https://claude.ai/share/f65dc986-136b-4f9b-865a-8d5dce1cf00a

| Repo | Path on owner's Mac | Branch to create | Base |
|---|---|---|---|
| OrdeloAgent | `/Users/basavaraj/bloop/OrdeloAgent` | `feature/wa-order-tracking` | `feature/dynamic-payment-return-urls` (not merged yet) |
| restaurant-frontend | `/Users/basavaraj/bloop/restaurant-frontend` | `feature/wa-order-tracking` | `feature/dynamic-payment-return-urls` |
| restaurant-agents | `/Users/basavaraj/bloop/restaurant-agents` | `feature/wa-order-tracking` | `main` |

Commit locally, **do not push**, until the owner has tested. Commit format `type: summary`. If the return-URL branch changes before it merges, rebase onto it.

---

## 1. Goal

A WhatsApp customer gets a private link to the same order page web customers use (`/o/<token>` → `/town/<town>/orders/<ORDER_NUMBER>`), in the payment receipt they already receive. The page shows live status, and its help card sends them back to the restaurant's WhatsApp chat.

## 2. Today (verified 2026-10-08)

**Blocked on purpose (web-only, D34):**
- `utils_common/web_ordering/customer_order_view.py` L113–115: `get_view()` reads `food_order … AND origin_channel='web'`, so a WhatsApp order number is 404. L169 hard-codes `"origin_channel": "web"`.
- `utils_common/web_ordering/order_access.py` L21–36: `issue()` only inserts a grant `WHERE origin_channel='web'`.
- restaurant-frontend `lib/web/types.ts` L177: `origin_channel: 'web'`.

**Already works for WhatsApp orders:**
- The customer notifier records `order_customer_event` for every order (e.g. ELAS-JRHV-29: `payment_authorised → rider_assigned → food_collected → delivered`). Orders before the notifier covered a restaurant (SFCS up to ~5 Oct, ELAS before ~2 Oct) have no events: status still derives from the summary tables, only the timeline is empty. Old orders never get a link, so this only matters if a link is minted by hand.
- `derive()` reads `delivery_summary` / `takeaway_summary` / `delivery_dispatch`, which WhatsApp orders have. Paid WhatsApp orders checked (ELAS, SFCS, delivery and takeaway) all have `order_item` rows and a summary row.
- Delivery address falls back to `delivery_summary.customer_address`; `web_order_request` simply returns nothing for WhatsApp orders.
- `order_access.verify()` and `POST /web/access/exchange` have no channel filter. `/o/[token]` in the frontend needs no change.
- WhatsApp restaurants with orders since 1 Sept: ELAS, SFCS, BNAT. All are in `common.RESTAURANTS` (with CRMS, which is web-only).

**Who messages a WhatsApp customer:** OrdeloAgent never does. `payment_hooks.py` L65 publishes `payment_authorised` with webhook `order-payment-complete` and the `FoodOrder` payload; the notifier POSTs it (at most once, ADR-0006) to restaurant-agents `POST /{rest_ref}/payment-complete/{recipient}/{thread_id}` (`watomation/routers/order_event_hooks.py` L168), which sends a plain-text receipt with `runtime.async_wa_client.send_message` (delivery L244, collection L275). This covers chat orders and menu-page orders (`order_hooks.create_order`) alike.

**Why the token can't ride in the event payload:** the notifier stores the payload (`payload` and `body_json`) in `order_customer_event.data` and the outbox for replay. A raw token there would break the hash-only rule (ADR-0005, `order_access_grant.secret_hash`).

## 3. Decisions (agreed)

| # | Decision |
|---|---|
| Q1 | Scope: **delivery and collection, every WhatsApp restaurant agent**. No per-restaurant switch (keeps D35's "one switch"). Rollback = redeploy. |
| Q2 | The link goes in the **payment receipt** (`payment-complete`), sent once, as fixed text (not LLM text). The customer has just messaged, so the 24 h window is open and no template is needed. |
| Q3 | **restaurant-agents asks OrdeloAgent for the link** just before sending the receipt. The raw token is never stored anywhere except the customer's chat; only its hash is in `order_access_grant`. |
| Q4 | Grant: kind `page_token`, `detail_level` `full`, `expires_at = order_dtts + 30 days` (same as web; no migration). A fresh grant on every call, **no cap**. Issue only if: order exists, `origin_channel='whatsapp'`, paid (`payment_status <> 'requires_payment'`), caller's `recipient` = `food_order.recipient`, rest_ref in `RESTAURANTS`. Web orders → 409. |
| Q5 | The endpoint lives under **`/web/*`** and uses the existing **`ORDELO_WEB_KEY`** (`X-Ordelo-Web-Key`). restaurant-agents gets the same key. |
| Q6 | Page differences when `origin_channel === 'whatsapp'`: the help card's main button opens the **restaurant's WhatsApp chat** (`wa.me`), call stays as a second option; the **"Save your order link" box is hidden**. |
| Q7 | One line appended to the existing receipt, delivery and collection: `Track your order: <url>`. Request the link with a **2 s timeout**; on any failure send the receipt **without** the line and log a warning with the order number only. Never log the URL or token. Delivery replays are already stopped by the existing duplicate guard; a collection replay gets a fresh link (accepted). |
| Q8 | Branches as in the table above. Release: **OrdeloAgent → restaurant-frontend → restaurant-agents**, so a link is never sent before the page can show it. |

---

## 4. OrdeloAgent changes

Repo rules (CLAUDE.md): Supabase REST is blocking → `asyncio.to_thread()` in async code; Ruff F-rules; pytest + pytest-asyncio. The web_ordering modules use psycopg helpers (`one`, `query`) from `common.py`, which are async already.

### 4.1 `utils_common/payment_ms/return_urls.py`: share the storefront base

`web_return_urls()` already reads `RESTAURANT_MENU_APP_URL` via `config_str`. Extract it so the new endpoint builds the same `/o/<token>` URL:

```python
async def storefront_base() -> str | None:
    base = await config_str(RESTAURANT_MENU_APP_URL)
    return base.rstrip("/") if base else None


def order_link(base: str, token: str) -> str:
    return f"{base}/o/{quote(token, safe='')}"
```

`web_return_urls()` uses both (behaviour unchanged). Add `def wa_chat_url(rest_ref) -> str | None` returning `WA_PAYMENT_RETURN_URLS.get(rest_ref.upper())` so the order view and the return URLs share one map. Update the module docstring.

### 4.2 `utils_common/web_ordering/order_access.py`: `issue_for_whatsapp`

Keep `issue()` unchanged (web checkout only). Add:

```python
async def issue_for_whatsapp(order_number, recipient):
    """Mint a full page grant for a paid WhatsApp order and return its raw secret.

    404 unknown order or restaurant not in RESTAURANTS; 409 web order
    (its link comes from checkout) or unpaid order; 403 recipient mismatch.
    Every call creates a new grant (no cap, decision Q4).
    """
```

- Read `order_number, origin_channel, recipient, payment_status` from `food_order` first to choose the error: missing → `WebError("not_found", 404)`; `rest_ref` (`order_number.split("-")[0]`) not in `RESTAURANTS` → 404; `origin_channel == "web"` → `WebError("web_order", 409)`; `payment_status == "requires_payment"` → `WebError("not_paid", 409)`; `recipient` differs (`secrets.compare_digest` on strings) → `WebError("forbidden", 403)`.
- Then the same INSERT as `issue()`, with the WHERE repeating the conditions so a race can't slip through:
  `... WHERE order_number=%s AND origin_channel='whatsapp' AND recipient=%s AND payment_status<>'requires_payment' RETURNING id, expires_at`.
- Return `(token, expires_at)`.

### 4.3 `watomation/routers/web_hooks.py`: new route

```python
class WhatsAppLink(BaseModel):
    order_number: str = Field(pattern=r"^[A-Z0-9]+-[A-Z]{4}-\d+$")
    recipient: str = Field(min_length=5, max_length=32)


@router.post("/access/whatsapp-link")
async def whatsapp_link(body: WhatsAppLink):
    base = await storefront_base()
    if not base:
        raise WebError("link_unavailable", 503)      # check before minting: no orphan grants
    token, expires_at = await order_access.issue_for_whatsapp(body.order_number, body.recipient)
    return JSONResponse({"url": order_link(base, token), "expires_at": iso(expires_at)},
                        status_code=201, headers=PRIVATE)
```

The router-level `require_key` dependency gives it the `ORDELO_WEB_KEY` check. Upper-case `order_number` before validating (WhatsApp payloads use upper case already). No logging of the body or response.

### 4.4 `utils_common/web_ordering/customer_order_view.py`: WhatsApp-aware view

- L113–115: `SELECT * FROM food_order WHERE order_number=%s AND origin_channel IN ('web','whatsapp')` (the CHECK constraint already limits the column to these two; the explicit list keeps intent visible).
- L169: `"origin_channel": food["origin_channel"]`.
- `support`: for `whatsapp`, `"whatsapp_available": True, "whatsapp_url": wa_chat_url(rest_ref)` (`whatsapp_available` is `False` when the map has no entry). Web unchanged (`False`, no URL).
- The `web_order_request` lookup (full detail) runs only for web orders; WhatsApp uses `summary.customer_address` and no instructions.
- Update the docstrings ("registered web order" → "web or WhatsApp order").

`derive()` needs no change. Note for reviewers: `derive()`'s "authorised" test is `payment_status != "requires_payment"`, which is right for WhatsApp too.

### 4.5 Tests

`tests/utils_common/web_ordering/test_web_contract.py` (extend; reuse its `one`/`query` monkeypatch pattern):
- `issue_for_whatsapp`: success inserts with the WhatsApp WHERE and returns a 43-char token; 404 unknown order; 404 rest_ref not in registry; 409 web order; 409 unpaid; 403 wrong recipient.
- Route: `/web/access/whatsapp-link` without the key → 401 (add to `test_new_web_routes_require_server_secret`); with the key and `RESTAURANT_MENU_APP_URL` unset → 503 and **no** insert; success → 201 with `url` ending `/o/<token>` and `PRIVATE` headers.
- `get_view`: a WhatsApp delivery order returns `origin_channel: "whatsapp"`, address from `delivery_summary`, `support.whatsapp_url` = ELAS wa.me; a WhatsApp takeaway reads `takeaway_summary`; a web order still returns `whatsapp_available: False` and no URL.
- `tests/utils_common/payment_ms/test_return_urls.py`: `storefront_base`, `order_link`, `wa_chat_url` (ELAS/SFCS/BNAT, unknown → None); existing cases unchanged.

Run: `pytest tests/utils_common/web_ordering tests/utils_common/payment_ms -q && pytest -q && ruff check .`

---

## 5. restaurant-frontend changes

- `lib/web/types.ts`: `origin_channel: 'web' | 'whatsapp'`; `support: { call_restaurant?: string; whatsapp_available: boolean; whatsapp_url?: string; support_email?: string }`.
- `components/order-status/RestaurantHelpCard.tsx`: when `support.whatsapp_available && support.whatsapp_url`, the main button is "Message {restaurant.name} on WhatsApp" (`href={support.whatsapp_url}`, `target="_blank" rel="noopener noreferrer"`, `MessageCircle` icon from `lucide-react`), the call button becomes secondary styling, and the copy reads "To change or cancel your order, or for anything about your food, message or call the restaurant." Web orders render exactly as today.
- `components/order-status/OrderPage.tsx` L214: `{full && view.origin_channel !== 'whatsapp' && <SaveOrderLink … />}`.
- `lib/web/fixtures/index.ts`: add one WhatsApp delivery fixture (status `rider_assigned`, ELAS wa.me URL) so fixtures mode shows the new card.
- No change to `/o/[token]`, `/api/web/orders/[orderNumber]` or `PaymentReturn`.

Run: `npm run lint && npm run build`. Screenshot the help card (web and WhatsApp) for the PR.

---

## 6. restaurant-agents changes

Package root: `packages/restaurant-agent-runtime/src/restaurant_agent_runtime/`.

### 6.1 Secret and setting

- Add `ordelo_web_key` to AWS Secrets Manager **`restaurant-agents-env`** with the same value as OrdeloAgent's `ORDELO_WEB_KEY` (OrdeloAgent reads the env var first, then `ordelo-agent-env` key `ordelo_web_key`; that secret has no such key today, so the value lives in the OrdeloAgent deployment env).
- `config/project_setting.py` `ProjectSetting`: add `ordelo_web_key: str = Field("", alias="ordelo_web_key")`. It loads through `load_settings_bundle()` like the other fields. Empty means "feature off": no call is made.

### 6.2 New `services/order_link.py`

```python
"""Fetch a customer's private order-page link from Ordelo for the payment receipt.

Best effort: any failure returns None and the receipt is sent without the line.
Never log the URL or token.
"""

TIMEOUT_SECS = 2.0


async def fetch_order_page_link(runtime, order_number: str, recipient: str) -> str | None:
    key = runtime.settings.project.ordelo_web_key
    if len(key) < 32:
        return None
    base = runtime.operational_lookups.get_app_url("ORDELO")   # ORDELO_APP_URL, as payment-complete simulation uses
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECS, follow_redirects=False) as client:
            r = await client.post(f"{base}/web/access/whatsapp-link",
                                  json={"order_number": order_number, "recipient": recipient},
                                  headers={"X-Ordelo-Web-Key": key})
        if r.status_code != 201:
            logger.warning("order link unavailable order={} status={}", order_number, r.status_code)
            return None
        url = r.json().get("url")
        return url if isinstance(url, str) and url.startswith("https://") else None
    except Exception as exc:  # noqa: BLE001 - never block the receipt
        logger.warning("order link failed order={} error_type={}", order_number, type(exc).__name__)
        return None
```

Check how `runtime.settings` exposes `project` (it is built in `config/bundle.py` L32) and adjust the attribute path.

### 6.3 `watomation/routers/order_event_hooks.py` `payment_complete`

- After the delivery duplicate guard (≈L215) and before building `formatted_wa_text`, call `link = await fetch_order_page_link(runtime, food_order.order_number, recipient)`.
- Append `f"\n    Track your order: {link}\n"` to `formatted_wa_text` in **both** branches (delivery ≈L238, collection ≈L270) when `link` is set.
- The receipt is still sent before the background graph task, as today. Nothing else changes.
- The link is not passed into the graph state or the LLM system message.

### 6.4 Tests (new `tests/watomation/routers/test_order_event_hooks.py`)

Use the repo's runtime stubs (`tests/_stubs`) and patch `fetch_order_page_link` / `httpx`:
- Delivery and collection: when the fetch returns a URL, the sent text ends with `Track your order: https://…/o/…`.
- Fetch returns None (timeout, 401, 409, 503, empty key): receipt sent unchanged, no exception.
- Delivery replay (duplicate guard hit): no fetch, no send.
- `fetch_order_page_link`: empty/short key → no HTTP call; non-201 → None; non-https URL → None; timeout is 2 s; log lines never contain `/o/`.

Run the repo's usual `pytest -q` (and its linter).

---

## 7. Local verification

Follow `docs/local-testing-runbook.md` (OrdeloAgent :3100, restaurant-frontend :3000, restaurant-agents :3101, Cloudflare tunnel; switch `ORDELO_APP_URL` / `RESTAURANT_MENU_APP_URL` to the test hosts in the maintenance window and restore after). Use Stripe test mode (overwatch number with `?isTest3100=true`, or a restaurant in `TEST_PAYMENT_REST_REFS`). Locally restaurant-agents needs `ordelo_web_key` in its env, matching OrdeloAgent's `ORDELO_WEB_KEY` from `.env.r3-local`.

| # | Test | Expect |
|---|---|---|
| W1 | WhatsApp delivery, ELAS, chat order, pay | Receipt ends with `Track your order: https://restaurant-test.ordelo.app/o/…`. Opening it lands on `/town/salisbury/orders/ELAS-…`; status moves through rider assigned / on its way / delivered; help card shows "Message Elai… on WhatsApp" → opens the ELAS wa.me; no "Save your order link" box |
| W2 | WhatsApp collection (SFCS or BNAT) | Same line in the collection receipt; page shows the collection steps from `takeaway_summary` |
| W3 | WhatsApp menu-page order (`/restaurant/elas`) | Same as W1 (same `payment-complete` path) |
| W4 | `ordelo_web_key` removed from restaurant-agents env | Receipt sent without the line; no call made |
| W5 | OrdeloAgent stopped while paying | Receipt arrives within ~2 s extra, without the line; warning logged with the order number only |
| W6 | `curl` the endpoint: wrong key / web order / unpaid order / wrong recipient / unknown order | 401 / 409 / 409 / 403 / 404; no grant row for any of them |
| W7 | `RESTAURANT_MENU_APP_URL` missing | 503 `link_unavailable`, no grant row |
| W8 | Web order regression (delivery) | Checkout, return to `/o/<token>`, page unchanged: call button only, save-link box shown |
| W9 | Privacy | No `/o/` URL or token in OrdeloAgent, restaurant-agents or Next.js logs for W1–W3 |

Inspect grants with `SELECT order_number, kind, detail_level, expires_at FROM order_access_grant WHERE order_number='<n>' ORDER BY id;` (hashes only).

---

## 8. Release

1. **OrdeloAgent** (endpoint + view). Safe alone: nothing calls the endpoint and no WhatsApp order has a link yet.
2. **restaurant-frontend** (type, help card, hidden save-link box).
3. **restaurant-agents**: add `ordelo_web_key` to `restaurant-agents-env`, deploy. Links start appearing in new receipts.
4. **Production smoke test:** one WhatsApp delivery at the test restaurant; open the link; check the help button and one status change.
5. **Docs:**
   - New ADR `docs/adr/0009-order-page-covers-whatsapp-orders.md`: WhatsApp orders get the same order page; the link is minted by OrdeloAgent on request from the restaurant app at receipt time and sent once in the receipt; the raw token is never stored (amends the web-only scope of D34; ADR-0003 and ADR-0005 still hold).
   - `plans/ordelo-agg-plan-cc.md`: tick the "order tracking page for WhatsApp orders" item in "Resume here" and point the R5 entry here.
   - `CONTEXT.md` "Web ordering": add "order page link (WhatsApp)" to the glossary.

## 9. Out of scope

- A link in the rider-assigned or later messages (could be added later as fixed text, never through the LLM).
- Links for orders paid before release (can be minted by hand: `claude/ordelo-order-access-tokens.md` in the project).
- WhatsApp templates: the receipt is always inside the 24 h window.
- Timeline backfill for orders without `order_customer_event` rows.

## 10. Done when

- [ ] OrdeloAgent: `pytest -q && ruff check .` pass; new tests in §4.5 pass.
- [ ] restaurant-frontend: `npm run lint && npm run build` pass.
- [ ] restaurant-agents: tests in §6.4 pass.
- [ ] W1–W9 pass locally.
- [ ] Commits on the three `feature/wa-order-tracking` branches, not pushed.
