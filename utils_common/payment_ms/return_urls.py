"""
Stripe Checkout return URLs sent to the payment service.
  . web_return_urls - web orders return to their secret order link (/o/<token>) so the customer
    sees the order page straight away, without waiting for payment authorisation; without a
    token they fall back to the storefront's /checkout/return page
  . wa_return_urls  - WhatsApp menu-page orders return to the restaurant's WhatsApp chat
  . None from either means "send nothing": the payment service uses its per-restaurant defaults.
Functions:
  . web_return_urls
  . wa_return_urls
"""

from urllib.parse import quote

from config.feature_flags import config_str

# ordelo_config key holding the restaurant-frontend base URL (no trailing slash needed). It also
# builds the dashboard links in config/params.py, so test/prod switches move both together.
RESTAURANT_MENU_APP_URL = "RESTAURANT_MENU_APP_URL"

# Mirrors payment-service internal/config/config.yaml successurl/cancelurl and
# restaurant-frontend config/whatsapp.ts PAYMENT_COMPLETE.
WA_PAYMENT_RETURN_URLS: dict[str, str] = {
    "ELAS": "https://wa.me/message/AIDICBLAE4KZH1",
    "SFCS": "https://wa.me/message/KLHBN7UOKO7UE1",
    "BNAT": "https://wa.me/message/F7QYDTUOIVCNI1",
}


async def web_return_urls(order_number: str, token: str | None = None) -> dict[str, str] | None:
    base = await config_str(RESTAURANT_MENU_APP_URL)
    if not base:
        return None
    base = base.rstrip("/")
    success = (
        f"{base}/o/{quote(token, safe='')}"
        if token
        else f"{base}/checkout/return?order={quote(order_number, safe='')}"
    )
    return {
        "success_url": success,
        "cancel_url": f"{base}/checkout?resume=1",
    }


def wa_return_urls(rest_ref: str) -> dict[str, str] | None:
    url = WA_PAYMENT_RETURN_URLS.get((rest_ref or "").upper())
    return {"success_url": url, "cancel_url": url} if url else None
