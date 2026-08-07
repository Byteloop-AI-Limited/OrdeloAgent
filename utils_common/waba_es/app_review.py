# %% [markdown]
# # Demonstration of `whatsapp_business_management`
#
# This recording demonstrates how our service uses Meta's **Graph API** to read
# management information from a WhatsApp Business Account
# (WABA) after the user has granted access to it.
#
# The demonstration performs three read-only operations using the Graph API:
#
# 1. Read the WABA's business phone numbers using the Graph API.
# 2. Check the WABA's application subscriptions using the Graph API.
# 3. Get the WABA's WhatsApp message templates using the Graph API.
#
# These operations are part of our backend WhatsApp integration. The matching
# WhatsApp Manager screens are shown during the recording so the returned Graph
# API data can be compared with the selected WABA's visible configuration.
#
# No access token, app secret, verification token, or PIN is displayed. WABA
# IDs, phone-number IDs, business phone numbers, verified names, application
# details, and template details remain visible so the reviewer can verify that
# the Graph API responses correspond to the account shown in WhatsApp Manager.

# %% [markdown]
# ## Setup the access token and WABA ID
#
# First, show WhatsApp Manager:
# The WABA shown in WhatsApp Manager is the same WABA used in each Graph API
# request below.

# %% 
# 1. Define supporting functions, mainly `graph_request`
# `graph_request`: is an internal utility function to make Graph API requests

from __future__ import annotations

import json
import os
from getpass import getpass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v23.0").removeprefix("v")
ACCESS_TOKEN = os.getenv("META_APP_REVIEW_ACCESS_TOKEN") or getpass(
    "Meta access token (input hidden): "
)
WABA_ID = os.getenv("META_APP_REVIEW_WABA_ID", "490733454126658")

if not ACCESS_TOKEN.strip():
    raise RuntimeError("A Meta access token is required.")
if not WABA_ID.strip():
    raise RuntimeError("A WABA ID is required.")

GRAPH_BASE_URL = f"https://graph.facebook.com/v{GRAPH_API_VERSION}"
HTTP_TIMEOUT_SECONDS = 30

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {ACCESS_TOKEN}"})


def _redact_token_from_url(value: str) -> str:
    """Redact token query parameters without hiding account identifiers."""
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.replace(ACCESS_TOKEN, "[REDACTED]")

    query = [
        (key, "[REDACTED]" if "token" in key.lower() else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


def redact_credentials(value: Any, *, parent_key: str = "") -> Any:
    """Remove credentials while leaving IDs, names, and phone numbers visible."""
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if "token" in key.lower() or "secret" in key.lower()
                else redact_credentials(item, parent_key=key)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_credentials(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        return _redact_token_from_url(value)
    return value



def graph_request(
    edge: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make a read-only Graph API request and display its successful response."""
    endpoint = f"/{edge.lstrip('/')}"
    response = session.get(
        url=f"{GRAPH_BASE_URL}{endpoint}",
        params=params,
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    print(f"Graph API request: GET {endpoint}")
    print(f"HTTP status: {response.status_code}")

    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise RuntimeError("Meta Graph API returned a non-JSON response.") from error

    if not response.ok:
        error_details = redact_credentials(payload.get("error", payload))
        raise RuntimeError(
            "Meta Graph API request failed:\n"
            f"{json.dumps(error_details, indent=2, sort_keys=True)}"
        )

    print("Graph API response (credentials redacted only):")
    print(json.dumps(redact_credentials(payload), indent=2, sort_keys=True))
    return payload


print(f"Graph API version: v{GRAPH_API_VERSION}")
print(f"WABA ID: {WABA_ID}")
print("Access token loaded securely and will not be displayed.")

# %% [markdown]
# ## 1. Read the WABA's business phone numbers using the Graph API
#
# **Graph API operation:** `GET /{WABA_ID}/phone_numbers`
#
# This operation reads the phone-number assets owned by the WABA. The response
# displays each phone-number ID, full business phone number, and verified
# business name as returned by Meta's Graph API.
#
# **Corresponding WhatsApp Manager screen shown in the recording:**
#
# **WhatsApp Manager -> Account tools -> Phone numbers**
#
# The phone-number ID, business phone number, and verified name on that screen
# can be compared directly with the Graph API response below.

# %% Read the WABA's business phone numbers using the Graph API
phone_numbers_response = graph_request(
    f"{WABA_ID}/phone_numbers",
    params={"fields": "id,display_phone_number,verified_name"},
)

# %% [markdown]
# ## 2. Check the WABA's application subscriptions using the Graph API
#
# **Graph API operation:** `GET /{WABA_ID}/subscribed_apps`
#
# This operation checks which Meta applications are subscribed to receive
# webhook events for the selected WABA. The returned application identifiers
# and names remain visible in the Graph API response.
#
# **Corresponding Meta screen shown in the recording:**
#
# **Meta for Developers -> My Apps -> select this application -> WhatsApp ->
# Configuration -> Webhook**
#
# The configuration screen shows the webhook endpoint for this application.
# The Graph API response below confirms the application's subscription at the
# selected WABA level.

# %% Check the WABA's application subscriptions using the Graph API
application_subscriptions_response = graph_request(f"{WABA_ID}/subscribed_apps")

# %% [markdown]
# ## 3. Get WhatsApp message templates using the Graph API
#
# **Graph API operation:** `GET /{WABA_ID}/message_templates`
#
# This operation reads the WhatsApp message templates belonging to the selected
# WABA. The Graph API response displays the template IDs, names, languages,
# categories, statuses, and components returned by Meta.
#
# **Corresponding WhatsApp Manager screen shown in the recording:**
#
# **WhatsApp Manager -> Account tools -> Message templates**
#
# The template names and statuses on that screen can be compared directly with
# the Graph API response below.

# %% Get the WABA's WhatsApp message templates using the Graph API
message_templates_response = graph_request(f"{WABA_ID}/message_templates")

# %% [markdown]
# ## Demonstration complete
#
# This recording has demonstrated three implemented uses of
# `whatsapp_business_management`, all performed through Meta's Graph API:
#
# - Reading the WABA's business phone-number configuration.
# - Checking the applications subscribed to the WABA's webhooks.
# - Reading the WABA's WhatsApp message templates.
#
# All three requests are read-only and use the same restaurant-owned WABA shown
# in WhatsApp Manager. The successful HTTP responses and corresponding
# WhatsApp Manager screens demonstrate the business-management functionality
# that our service uses after the restaurant grants access.

# %%
