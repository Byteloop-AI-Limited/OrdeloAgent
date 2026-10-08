"""
Stripe Checkout return URLs sent to the payment service.
  . web_return_urls - web orders return to the storefront's /checkout/return page
  . wa_return_urls  - WhatsApp menu-page orders return to the restaurant's WhatsApp chat
  . None from either means "send nothing": the payment service uses its per-restaurant defaults.
Functions:
  . web_return_urls
  . wa_return_urls
"""

from urllib.parse import quote

from config.feature_flags import config_str

WEB_STOREFRONT_URL = "WEB_STOREFRONT_URL"

# Mirrors payment-service internal/config/config.yaml successurl/cancelurl and
# restaurant-frontend config/whatsapp.ts PAYMENT_COMPLETE.
WA_PAYMENT_RETURN_URLS: dict[str, str] = {
    "ELAS": "https://wa.me/message/AIDICBLAE4KZH1",
    "SFCS": "https://wa.me/message/KLHBN7UOKO7UE1",
    "BNAT": "https://wa.me/message/F7QYDTUOIVCNI1",
}


async def web_return_urls(order_number: str) -> dict[str, str] | None:
    base = await config_str(WEB_STOREFRONT_URL)
    if not base:
        return None
    base = base.rstrip("/")
    return {
        "success_url": f"{base}/checkout/return?order={quote(order_number, safe='')}",
        "cancel_url": f"{base}/checkout?resume=1",
    }


def wa_return_urls(rest_ref: str) -> dict[str, str] | None:
    url = WA_PAYMENT_RETURN_URLS.get((rest_ref or "").upper())
    return {"success_url": url, "cancel_url": url} if url else None
