"""
Stripe Checkout return URLs sent to the payment service.
  . web_return_urls - web orders return to their secret order link (/o/<token>) so the customer
    sees the order page straight away, without waiting for payment authorisation; without a
    token they fall back to the storefront's /checkout/return page
  . wa_return_urls  - WhatsApp menu-page orders return to the restaurant's WhatsApp chat
  . None from either means "send nothing": the payment service uses its per-restaurant defaults.
  . storefront_base / order_link - build the secret /o/<token> order-page URL (also used to send
    the link in the WhatsApp payment receipt)
  . wa_chat_url - the restaurant's WhatsApp chat link (return URLs and the order page help button)
Functions:
  . storefront_base
  . order_link
  . wa_chat_url
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


async def storefront_base() -> str | None:
    base = await config_str(RESTAURANT_MENU_APP_URL)
    return base.rstrip("/") if base else None


def order_link(base: str, token: str) -> str:
    return f"{base}/o/{quote(token, safe='')}"


def wa_chat_url(rest_ref: str) -> str | None:
    return WA_PAYMENT_RETURN_URLS.get((rest_ref or "").upper())


async def web_return_urls(order_number: str, token: str | None = None) -> dict[str, str] | None:
    base = await storefront_base()
    if not base:
        return None
    success = (
        order_link(base, token)
        if token
        else f"{base}/checkout/return?order={quote(order_number, safe='')}"
    )
    return {
        "success_url": success,
        "cancel_url": f"{base}/checkout?resume=1",
    }


def wa_return_urls(rest_ref: str) -> dict[str, str] | None:
    url = wa_chat_url(rest_ref)
    return {"success_url": url, "cancel_url": url} if url else None
