# WhatsApp Embedded Signup — Onboarding Guide

**Version:** 1.0
**Last Updated:** 2026-03-21

This document explains how Ordelo onboards new restaurant businesses onto WhatsApp Business API using Meta's Embedded Signup flow. It maps Meta's official documentation steps to our implementation.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration & Credentials](#configuration--credentials)
4. [Step-by-Step Flow](#step-by-step-flow)
5. [Token Types](#token-types)
6. [Database Persistence](#database-persistence)
7. [Post-Onboarding](#post-onboarding)
8. [Troubleshooting](#troubleshooting)

---

## Overview

Embedded Signup lets a new business complete WhatsApp Business Account (WABA) registration inside an iframe/popup on our page, without leaving ordelo.app. Once signup completes, we automatically:

1. Exchange the auth code for a business token
2. Subscribe our app to the new WABA (to receive webhooks)
3. Register the phone number for messaging
4. Send a test message to verify the setup

**Meta Documentation Reference:** [Embedded Signup](https://developers.facebook.com/docs/whatsapp/embedded-signup)

---

## Architecture

```
Browser (restaurant owner)          Backend (FastAPI)              Meta Graph API
──────────────────────────          ────────────────               ──────────────
1. Load signup page
   GET /twilio-webhook/
       waba-embedded-signup
       ← HTML with FB SDK

2. FB.login() popup
   User completes signup
   ↓
3. WA_EMBEDDED_SIGNUP event ──→ POST /twilio-webhook/
   (phone_number_id,              waba-embedded-signup
    waba_id, business_id)         → stores in TEMP_STORE

4. FB_AUTH_RESPONSE callback ──→ POST /twilio-webhook/
   (auth code)                    waba-embedded-signup
                                  → onboard_business_customer()
                                    ├─→ exchange code ──────────→ GET /oauth/access_token
                                    ├─→ persist to DB             → business_token
                                    ├─→ subscribe app ──────────→ POST /{waba_id}/subscribed_apps
                                    ├─→ register number ────────→ POST /{phone_id}/register
                                    └─→ send test msg ──────────→ POST /{phone_id}/messages
```

---

## Configuration & Credentials

Two settings classes in `config/waba_setting.py` provide credentials:

| Setting | Class | Purpose |
|---|---|---|
| `waba_business_settings` | `WabaBusinessSettings` | **System user token** — Ordelo's own WABA credentials. Used for phone registration and sending messages. Has `whatsapp_business_messaging` permission. |
| `waba_provider_settings` | `WabaProviderSettings` | **Tech provider credentials** — Meta app ID, app secret, configuration ID, Graph API version, PIN, business portfolio ID. Used to initiate the embedded signup and exchange codes. |

Key provider fields consumed during signup:

| Field | Source | Used In |
|---|---|---|
| `app_id` | `waba_provider_settings.app_id` | FB SDK init (`FB.init({ appId })`) |
| `app_secret` | `waba_provider_settings.app_secret` | Code-to-token exchange |
| `configuration_id` | `waba_provider_settings.configuration_id` | `FB.login({ config_id })` |
| `graph_api_version` | `waba_provider_settings.graph_api_version` | All Graph API calls |
| `pin` | `waba_provider_settings.pin` | Phone number registration (two-step verification) |

All secrets are loaded from AWS Secrets Manager via `config/aws_setting.py`.

---

## Step-by-Step Flow

### Step 1: Render Embedded Signup Dialog

**File:** `watomation/routers/templates/waba_embedded_signup.html`

The GET endpoint at `/twilio-webhook/waba-embedded-signup` renders an HTML page that:
- Loads the Facebook JS SDK from `connect.facebook.net`
- Initializes it with `app_id` and `graph_api_version` (passed as Jinja template variables)
- Provides a "Login with Facebook" button that calls `launchWhatsAppSignup()`

```javascript
FB.login(fbLoginCallback, {
    config_id: '{{ configuration_id }}',
    response_type: 'code',
    override_default_response_type: true,
    extras: {
        setup: {},
        featureType: 'whatsapp_embedded_signup',
        sessionInfoVersion: '3',
    }
});
```

### Step 2: Receive `WA_EMBEDDED_SIGNUP` Message Event

**File:** `waba_embedded_signup.html:16-29`

A `window.message` event listener catches postMessage from facebook.com. When `data.type === 'WA_EMBEDDED_SIGNUP'`, the payload contains:
- `phone_number_id` — the new phone number's Graph API ID
- `waba_id` — the new WhatsApp Business Account ID
- `business_id` — the Meta business ID

This data is POSTed to the backend and stored in `TEMP_STORE`.

**Backend handler:** `watomation/routers/twilio_webhook.py:88-97`

### Step 3: Receive `FB_AUTH_RESPONSE` Callback

**File:** `waba_embedded_signup.html:55-66`

The `FB.login()` callback fires with `response.authResponse.code` (the authorization code). This is POSTed to the backend as `{ type: 'FB_AUTH_RESPONSE', authResponse: {...} }`.

**Backend handler:** `watomation/routers/twilio_webhook.py:100-110` — extracts the code, stores it in `TEMP_STORE`, then calls `onboard_business_customer(TEMP_STORE)`.

### Step 4: Exchange Code for Business Token

**File:** `utils_common/waba_es/onboarding_utils.py:45-80` — `exchange_code_for_business_token()`

```
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?client_id={app_id}
    &client_secret={app_secret}
    &code={auth_code}
```

Returns a short-lived user access token (the "business token"). This token represents the business owner who completed signup.

### Step 4a: Persist Onboarding Data

**File:** `onboarding_utils.py:266-270`

The full `TEMP_STORE` dict (including `business_token`) is:
1. Pickled to `temp_store.pkl` (local backup)
2. Inserted into the `waba_es` Supabase table

### Step 5: Subscribe App to WABA

**File:** `onboarding_utils.py:86-111` — `subscribe_app_to_waba()`

```
POST https://graph.facebook.com/{version}/{waba_id}/subscribed_apps
Authorization: Bearer {business_token}
```

This subscribes our Meta app to the new WABA so we receive webhook events (message received, status updates, etc.) for this business.

### Step 5a: Update PIN (Optional, Currently Skipped)

**File:** `onboarding_utils.py:117-149` — `update_pin()`

Sets the two-step verification PIN on the phone number. Currently commented out in the orchestration function (lines 280-283). The default PIN `141414` is used during registration instead.

### Step 6: Register Phone Number

**File:** `onboarding_utils.py:152-183` — `register_phone_number()`

```
POST https://graph.facebook.com/{version}/{phone_number_id}/register
Authorization: Bearer {waba_business_settings.token}    ← system user token
Body: { "messaging_product": "whatsapp", "pin": "141414" }
```

**Important:** This step uses `waba_business_settings.token` (system user token), not the exchanged business token.

### Step 7: Send Test Message

**File:** `onboarding_utils.py:189-226` — `send_test_message()`

```
POST https://graph.facebook.com/{version}/{phone_number_id}/messages
Authorization: Bearer {waba_business_settings.token}    ← system user token
Body: { "messaging_product": "whatsapp", "to": "{recipient}", "type": "text", ... }
```

Sends a simple text message to verify the number can send messages.

---

## Token Types

Understanding the two token types is critical for debugging permission errors:

| Token | Source | Variable | Has `whatsapp_business_messaging`? | Used For |
|---|---|---|---|---|
| **System User Token** | Pre-configured in AWS Secrets | `waba_business_settings.token` | Yes | Phone registration, sending messages, webhook management |
| **Business Token** | Exchanged from auth code (Step 4) | `business_token` (local var) | Not guaranteed | WABA subscription, persisted for future API calls on behalf of the business |

If `send_test_message()` fails with `(#3) Application does not have the API granular permission`, it likely means the wrong token type is being used. The system user token should be used for messaging operations.

---

## Database Persistence

### `waba_es` Table

Stores onboarding records. Each row corresponds to one completed embedded signup:

| Column | Source |
|---|---|
| `phone_number_id` | From `WA_EMBEDDED_SIGNUP` event |
| `waba_id` | From `WA_EMBEDDED_SIGNUP` event |
| `business_id` | From `WA_EMBEDDED_SIGNUP` event |
| `code` | From `FB_AUTH_RESPONSE` callback |
| `business_token` | From code exchange (Step 4) |
| `phone_num` | Pre-set in `TEMP_STORE` before signup |
| `business_ref` | Pre-set in `TEMP_STORE` before signup |

### Pre-Signup Setup

Before initiating a signup, `TEMP_STORE` must be updated with the business's display phone number and reference:

```python
# onboarding_utils.py line 38
TEMP_STORE = {"phone_num": "00441722433714", "business_ref": "elas"}
```

This is currently hardcoded and must be changed for each onboarding.

---

## Post-Onboarding

After the automated flow completes, the following manual/semi-automated steps use `utils_common/waba_es/api_funcs.py`:

| Function | Purpose |
|---|---|
| `get_assigned_wabas()` | List all WABAs assigned to our tech provider portfolio |
| `list_phone_numbers_for_waba(waba_id)` | List phone numbers under a specific WABA |
| `get_wabas_with_phone_numbers()` | Combined view of all WABAs and their phone numbers |
| `register_phone_number(phone_number_id)` | Manually register a phone number (if automated step failed) |

The callback URL for the new WABA can be overridden using `pywa`:
```python
wa.override_waba_callback_url(
    callback_url="https://agent.ordelo.app/",
    verify_token="123456",
    waba_id="<waba_id>",
)
```

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `(#3) Application does not have the API granular permission` on test message | Wrong token used for messaging | Ensure `send_test_message()` uses `waba_business_settings.token` (system user token) |
| `Unhandled event type: None` in logs | Raw (non-JSON) message events from FB SDK | Harmless — these are now handled and logged at debug level |
| Phone registration takes >10 seconds | Normal for Meta — registration can be slow | No action needed, wait for completion |
| `No code found in TEMP_STORE` | `WA_EMBEDDED_SIGNUP` event arrived but `FB_AUTH_RESPONSE` did not | User may have closed the popup before completing auth — retry signup |
| WABA subscription fails | Business token expired or lacks permissions | Re-run signup flow to get a fresh auth code |

### Verifying a Successful Onboarding

1. Check `waba_es` table for the new record
2. Run `get_wabas_with_phone_numbers()` to confirm the WABA appears under the tech provider
3. Send a test message via the Graph API or via the `send_test_message()` function
4. Verify webhooks are received by checking app logs after sending a message to the new number
