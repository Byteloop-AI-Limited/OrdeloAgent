# The order page also tracks WhatsApp orders

Status: accepted, implemented locally on `feature/wa-order-tracking`, 8 October 2026 (not yet deployed). Amends the web-only scope of D34 in `plans/ordelo-agg-plan-cc.md`; [ADR 0003](0003-web-orders-never-reach-restaurant-apps.md) and [ADR 0005](0005-web-orders-use-synthetic-keys-and-no-contact.md) still hold.

The customer order page (`/town/<town>/orders/<N>`) was web-only. A WhatsApp customer had no way to see rider status except by asking in the chat. The status derivation (`customer_order_view.derive()`) already works for any order that has `food_order`, summary, dispatch and `order_customer_event` rows, so the page now serves WhatsApp orders too.

- **Who gets a link.** Every paid WhatsApp order, delivery or collection, for every restaurant agent. No per-restaurant switch.
- **How it is sent.** Once, as an "Order Tracking" URL button on the payment receipt message (a WhatsApp CTA button, so the raw link isn't in the text). The restaurant app (restaurant-agents) asks OrdeloAgent for the link at receipt time with `POST /web/access/whatsapp-link`, protected by `X-Ordelo-Web-Key` (`ORDELO_WEB_KEY`). It is never written by the LLM.
- **Minting.** `order_access.issue_for_whatsapp()` creates a new full-detail `page_token` grant on every call (no cap), expiring 30 days after the order. It refuses unknown orders and restaurants (404), web orders and unpaid orders (409) and a recipient that does not own the order (403). The storefront URL is checked before minting, so a misconfiguration leaves no orphan grant.
- **No raw token at rest.** The token is returned once and is not stored in any table, event payload or outbox row (the notifier stores payloads for replay), and no service logs it. Grants stay hash-only.
- **Best effort.** The call has a 2 second timeout. On any failure the receipt goes out without the line; a receipt is never delayed or blocked by this.
- **Page differences for WhatsApp orders.** The help card's main button opens the restaurant's WhatsApp chat (`support.whatsapp_url`, from `wa_chat_url()`), with the phone call secondary, and the "Save your order link" box is hidden (the link is already in the chat). The address comes from the summary table; there is no `web_order_request` for these orders.

Orders paid before release have no link; one can be minted by hand (see `claude/ordelo-order-access-tokens.md` in the project). Orders with no `order_customer_event` rows (for example SFCS before the notifier pilot) show a thin timeline.

Rejected: putting the link in the LLM context (the model could alter or leak it), a capped number of grants per order, storing the raw token to re-send later, and a separate WhatsApp-only tracking page.

Sources: [order_access.py](../../utils_common/web_ordering/order_access.py), [web_hooks.py](../../watomation/routers/web_hooks.py), [customer_order_view.py](../../utils_common/web_ordering/customer_order_view.py), [return_urls.py](../../utils_common/payment_ms/return_urls.py), [plan](../../plans/order-tracking-page-for-whatsapp.md).
