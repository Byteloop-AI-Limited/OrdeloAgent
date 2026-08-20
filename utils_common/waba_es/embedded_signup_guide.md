# WhatsApp Embedded Signup — Onboarding Guide

**Version:** 1.2
**Last Updated:** 2026-08-20

This document explains how Ordelo onboards new restaurant businesses onto WhatsApp Business API using Meta's Embedded Signup flow. It maps Meta's official documentation steps to our implementation.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration & Credentials](#configuration--credentials)
4. [Step-by-Step Flow](#step-by-step-flow)
5. [Reference Log: Successful Onboarding](#reference-log-successful-onboarding)
6. [Token Types](#token-types)
7. [Runtime Credential Policy](#runtime-credential-policy)
8. [Case Study: BNAT (2026-08-19)](#case-study-bnat-2026-08-19)
9. [Database Persistence](#database-persistence)
10. [Post-Onboarding](#post-onboarding)
11. [Troubleshooting](#troubleshooting)

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
| `waba_business_settings` | `WabaBusinessSettings` | **Legacy system user token** — Ordelo's own (`bloop_*`) WABA credentials. Still used by `register_phone_number()`. Has `whatsapp_business_messaging`. Not the runtime credential for new clients. |
| `waba_provider_settings` | `WabaProviderSettings` | **Tech provider credentials** — Meta app ID, app secret, configuration ID, Graph API version, PIN, business portfolio ID. Used to initiate the embedded signup, exchange codes, and — via `token` — as `RUNTIME_WABA_TOKEN`. |

`onboarding_utils.RUNTIME_WABA_TOKEN` is `waba_provider_settings.token`. It is what
`send_test_message()` sends with and what every onboarded client is configured with,
so the test message validates the exact credential that ships. See
[Runtime Credential Policy](#runtime-credential-policy).

Key provider fields consumed during signup:

| Field | Source | Used In |
|---|---|---|
| `app_id` | `waba_provider_settings.app_id` | FB SDK init (`FB.init({ appId })`) |
| `app_secret` | `waba_provider_settings.app_secret` | Code-to-token exchange |
| `configuration_id` | `waba_provider_settings.configuration_id` | `FB.login({ config_id })` |
| `graph_api_version` | `waba_provider_settings.graph_api_version` | All Graph API calls |
| `pin` | `waba_provider_settings.pin` | Phone number registration (two-step verification) |
| `token` | `waba_provider_settings.token` | `RUNTIME_WABA_TOKEN` — test message, and every client's runtime credential |

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
        featureType: '<FEATURE_TYPE>',   // left as the literal placeholder — see note
        sessionInfoVersion: '3',
    }
});
```

> **Note:** `featureType` in the template is still the literal string `'<FEATURE_TYPE>'` from Meta's sample code. The reference onboarding run succeeded with it unchanged, so Meta appears to ignore an unrecognised value and fall back to the default flow for the given `config_id`. Leave it alone unless you need a specific variation (e.g. `whatsapp_business_app_onboarding`).

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

**File:** `utils_common/waba_es/onboarding_utils.py:67-110` — `exchange_code_for_business_token()`

```
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?client_id={app_id}
    &client_secret={app_secret}
    &code={auth_code}
```

Returns the "business token". **This is not short-lived.** With the current Embedded
Signup configuration ("Access token: System-user access token / Token will never
expire" — see `waba_es_configuration.md`) it is a client-business *system-user* token
with `expires_at: 0`. What it does *not* guarantee is scope: its granular permissions
follow the Advanced Tasks granted at signup, so it may carry
`whatsapp_business_management` only. Never use it as a runtime credential — see
`RUNTIME_WABA_TOKEN` in `onboarding_utils.py`.

### Step 4a: Persist Onboarding Data

**File:** `onboarding_utils.py:333-339`

The full `TEMP_STORE` dict (including `business_token`) is:
1. Pickled to `temp_store.pkl` (local backup)
2. Inserted into the `waba_es` Supabase table

### Step 5: Subscribe App to WABA

**File:** `onboarding_utils.py:115-147` — `subscribe_app_to_waba()`

```
POST https://graph.facebook.com/{version}/{waba_id}/subscribed_apps
Authorization: Bearer {business_token}
```

This subscribes our Meta app to the new WABA so we receive webhook events (message received, status updates, etc.) for this business.

### Step 5a: Update PIN (Optional, Currently Skipped)

**File:** `onboarding_utils.py:152-188` — `update_pin()`

Sets the two-step verification PIN on the phone number. Currently commented out in the orchestration function (lines 349-352). The default PIN `141414` is used during registration instead.

### Step 6: Register Phone Number

**File:** `onboarding_utils.py:191-230` — `register_phone_number()`

```
POST https://graph.facebook.com/{version}/{phone_number_id}/register
Authorization: Bearer {waba_business_settings.token}    ← system user token
Body: { "messaging_product": "whatsapp", "pin": "141414" }
```

**Important:** This step uses `waba_business_settings.token` (system user token), not the exchanged business token.

### Step 7: Send Test Message

**File:** `onboarding_utils.py:235-280` — `send_test_message()`

```
POST https://graph.facebook.com/{version}/{phone_number_id}/messages
Authorization: Bearer {RUNTIME_WABA_TOKEN}    ← the token the deployed agent will use
Body: { "messaging_product": "whatsapp", "to": "{recipient}", "type": "text", ... }
```

Sends a simple text message to verify the number can send messages.

Since 2026-08-20 this uses `RUNTIME_WABA_TOKEN` (= `waba_provider_settings.token`)
rather than `waba_business_settings.token`, so the step validates the exact credential
that will be deployed. If it fails, the client's WABA is most likely not assigned to the
system user with the `messaging` task — see `waba_es_configuration.md`.

### Guide Steps vs. Log "Step N" Labels

The `logger.info("Step N: ...")` labels emitted at runtime do **not** match this guide's step numbering. Use this mapping when reading logs:

| Log label | Guide step | Function |
|---|---|---|
| `Step 1: Exchanging code for business token` | Step 4 | `exchange_code_for_business_token` |
| `Step 2: Subscribing app to WABA` | Step 5 | `subscribe_app_to_waba` |
| `Step 2.5: Updating PIN for phone number` | Step 5a | `update_pin` — **should never appear**, intentionally disabled |
| `Step 3: Registering customer's phone number` | Step 6 | `register_phone_number` |
| `Step 4: Sending test message` | Step 7 | `send_test_message` |

---

## Reference Log: Successful Onboarding

This is a **live, known-good onboarding run** (2026-08-19, `business_ref='bnat'`) to compare future runs against. All secrets and account identifiers are replaced with `<PLACEHOLDER>` tokens — the *shape*, *order*, *log level*, and *elapsed time* are what matter, not the values.

### Redaction legend

| Placeholder | Real value shape | Sensitive? |
|---|---|---|
| `<client-ip>` | IPv6/IPv4 of the browser completing signup | Low |
| `<DISPLAY_PHONE_NUM>` | `00441700000000` — business display number, pre-set in `TEMP_STORE` | Low |
| `<PHONE_NUMBER_ID>` | 16-digit Meta phone number ID | Low |
| `<WABA_ID>` | 16-digit WhatsApp Business Account ID | Low |
| `<BUSINESS_ID>` | 16-digit Meta business ID | Low |
| `<AUTH_CODE>` | `AQ…` ~500 char one-time OAuth code | **Yes — single-use secret** |
| `<BUSINESS_TOKEN>` | `EAA…` ~250 char user access token | **Yes — bearer token** |
| `<supabase-project-ref>` | Supabase project subdomain | **Yes** |
| `<cb>` / `<frame>` | Facebook SDK postMessage correlation hashes | Low |

### Annotated transcript

```log
# ── Page load ────────────────────────────────────────────────────────────────
INFO:     <client-ip>:0 - "GET /twilio-webhook/waba-embedded-signup HTTP/1.1" 200 OK

# ── Event 1: WA_EMBEDDED_SIGNUP (event='FINISH') — assets created by Meta ────
2026-08-19 17:49:12.211 | INFO  | watomation.routers.twilio_webhook:waba_embedded_signup_callback:85 - Received event: {'data': {'phone_number_id': '<PHONE_NUMBER_ID>', 'waba_id': '<WABA_ID>', 'page_ids': [], 'catalog_ids': [], 'dataset_ids': [], 'business_id': '<BUSINESS_ID>', 'instagram_account_ids': []}, 'type': 'WA_EMBEDDED_SIGNUP', 'event': 'FINISH'}
2026-08-19 17:49:12.212 | INFO  | watomation.routers.twilio_webhook:waba_embedded_signup_callback:96 - Updated TEMP_STORE with WA data: {'phone_num': '<DISPLAY_PHONE_NUM>', 'business_ref': 'bnat', 'phone_number_id': '<PHONE_NUMBER_ID>', 'waba_id': '<WABA_ID>', 'business_id': '<BUSINESS_ID>', 'event_type': 'FINISH'}
INFO:     <client-ip>:0 - "POST /twilio-webhook/waba-embedded-signup HTTP/1.1" 200 OK

# ── Event 2: raw_data (non-JSON FB SDK postMessage) — HARMLESS, ignored ──────
2026-08-19 17:49:12.588 | INFO  | watomation.routers.twilio_webhook:waba_embedded_signup_callback:85 - Received event: {'raw_data': 'cb=<cb>&domain=rider-agent-test.ordelo.app&is_canvas=false&origin=https%3A%2F%2Frider-agent-test.ordelo.app%2F<frame>&relation=opener&frame=<frame>&code=<AUTH_CODE>&base_domain=byteloop.ai'}
2026-08-19 17:49:12.588 | DEBUG | watomation.routers.twilio_webhook:waba_embedded_signup_callback:114 - Received raw_data event (non-JSON message from FB SDK): cb=<cb>&domain=rider-agent-test.ordelo.app&...&code=AQ…   ← truncated to 200 chars
INFO:     <client-ip>:0 - "POST /twilio-webhook/waba-embedded-signup HTTP/1.1" 200 OK

# ── Event 3: FB_AUTH_RESPONSE — triggers onboard_business_customer() ─────────
2026-08-19 17:49:12.591 | INFO  | watomation.routers.twilio_webhook:waba_embedded_signup_callback:85 - Received event: {'type': 'FB_AUTH_RESPONSE', 'authResponse': {'userID': None, 'expiresIn': None, 'code': '<AUTH_CODE>'}}
2026-08-19 17:49:12.591 | INFO  | watomation.routers.twilio_webhook:waba_embedded_signup_callback:106 - Updated TEMP_STORE with auth code: <AUTH_CODE>

# ── Guide Step 4: code → business token (~1.1 s) ─────────────────────────────
2026-08-19 17:49:12.591 | INFO  | utils_common.waba_es.onboarding_utils:exchange_code_for_business_token:55 - Step 1: Exchanging code for business token
2026-08-19 17:49:13.646 | INFO  | utils_common.waba_es.onboarding_utils:exchange_code_for_business_token:75 - Successfully obtained business token

# ── Guide Step 4a: persist to temp_store.pkl + waba_es table (~0.2 s) ────────
INFO:httpx:HTTP Request: POST https://<supabase-project-ref>.supabase.co/rest/v1/waba_es "HTTP/2 201 Created"

# ── Guide Step 5: subscribe our app to the new WABA (~1.2 s) ─────────────────
2026-08-19 17:49:13.807 | INFO  | utils_common.waba_es.onboarding_utils:subscribe_app_to_waba:97 - Step 2: Subscribing app to WABA
2026-08-19 17:49:15.019 | INFO  | utils_common.waba_es.onboarding_utils:subscribe_app_to_waba:106 - Successfully subscribed app to WABA

# ── Guide Step 6: register the phone number (~15.2 s — SLOWEST STEP) ─────────
2026-08-19 17:49:15.019 | INFO  | utils_common.waba_es.onboarding_utils:register_phone_number:162 - Step 3: Registering customer's phone number
2026-08-19 17:49:30.181 | INFO  | utils_common.waba_es.onboarding_utils:register_phone_number:178 - Successfully registered phone number

# ── Guide Step 7: send test message (~1.2 s) ─────────────────────────────────
2026-08-19 17:49:30.182 | INFO  | utils_common.waba_es.onboarding_utils:send_test_message:206 - Step 4: Sending test message
2026-08-19 17:49:31.410 | INFO  | utils_common.waba_es.onboarding_utils:send_test_message:224 - Successfully sent test message

# ── Done (~18.8 s from auth code) ────────────────────────────────────────────
2026-08-19 17:49:31.410 | INFO  | utils_common.waba_es.onboarding_utils:onboard_business_customer:298 - Business customer onboarding completed successfully, save this !!!: {'phone_num': '<DISPLAY_PHONE_NUM>', 'business_ref': 'bnat', 'phone_number_id': '<PHONE_NUMBER_ID>', 'waba_id': '<WABA_ID>', 'business_id': '<BUSINESS_ID>', 'event_type': 'FINISH', 'code': '<AUTH_CODE>', 'business_token': '<BUSINESS_TOKEN>'}
```

### Expected timings

| Phase | Log window | Duration |
|---|---|---|
| Code exchange | `Step 1` → `Successfully obtained business token` | ~1.1 s |
| `waba_es` insert | `Successfully obtained…` → `Step 2` | ~0.2 s |
| WABA subscription | `Step 2` → `Successfully subscribed app to WABA` | ~1.2 s |
| Phone registration | `Step 3` → `Successfully registered phone number` | **~15.2 s** |
| Test message | `Step 4` → `Successfully sent test message` | ~1.2 s |
| **Total** | `FB_AUTH_RESPONSE` → completion line | **~18.8 s** |

Phone registration dominates the runtime and is normal Meta behaviour. Do not add a client timeout below ~45 s to this call.

### Verification checklist for a future run

Compare a new run against the reference above:

- [ ] Exactly **three** `POST /twilio-webhook/waba-embedded-signup` requests, all `200 OK`
- [ ] `WA_EMBEDDED_SIGNUP` arrives **before** `FB_AUTH_RESPONSE` (order matters — see Troubleshooting)
- [ ] `WA_EMBEDDED_SIGNUP` carries `'event': 'FINISH'` and non-null `phone_number_id`, `waba_id`, `business_id`
- [ ] `Updated TEMP_STORE with WA data` contains the correct `business_ref` and `phone_num` for *this* onboarding
- [ ] The `raw_data` line is logged at **DEBUG**, not WARNING (a `Unhandled event type: None` warning means the handler regressed)
- [ ] `waba_es` insert returns **`201 Created`** (not `409`, not `401`)
- [ ] All four `Successfully …` lines present, in order, with no `Failed to …` / `Error …` lines in between
- [ ] **No** `Step 2.5: Updating PIN for phone number` line — `update_pin()` is intentionally disabled
- [ ] Final lines: `Business customer onboarding completed successfully:` (contains `code` and `business_token` — scrub before sharing) followed by `Runtime credential for this client is the shared system-user token ...`
- [ ] `business_token` was **not** copied into any `<namespace>_waa_token` secret
- [ ] The test message actually lands on the recipient WhatsApp (default `447448440754` in `send_test_message`)

> **Log line numbers drift.** The `:NN` suffixes in the transcript above are whatever the source revision that produced the run happened to have; adding a docstring line shifts them all. Match on the **message text**, never the line number. Current `onboarding_utils.py` positions: `Step 1` → `:84`, `Successfully obtained business token` → `:104`, `Step 2` → `:132`, `Successfully subscribed` → `:141`, `Step 3` → `:208`, `Successfully registered` → `:224`, `Step 4` → `:257`, `Successfully sent test message` → `:275`, completion line → `:364`.

### Security note on this log

The reference transcript shows that the raw `code` and `business_token` are currently emitted at **INFO** level in three places:

- `twilio_webhook.py:106` — `Updated TEMP_STORE with auth code: <AUTH_CODE>`
- `twilio_webhook.py:85` — the full `FB_AUTH_RESPONSE` event dump
- `onboarding_utils.py:364` — the completion dump containing `business_token`

The `raw_data` handler at `twilio_webhook.py:114` truncates to 200 chars, which happens to cut the auth code short — that is incidental, not a deliberate redaction. **Scrub these lines before sharing logs outside the team.** The auth code is single-use and short-lived; the business token is not.

---

## Token Types

Three kinds of token appear in this flow. Confusing them is the single most likely
way to ship a broken client — see [Case Study: BNAT](#case-study-bnat-2026-08-19).

| Token | Source | Expires? | `whatsapp_business_messaging`? | Use it for |
|---|---|---|---|---|
| **Provider system-user token** — `waba_provider_token` | AWS `ordelo-agent-env` | No (`expires_at: 0`) | **Yes**, granular targets `None` = unrestricted | Everything at runtime: sending, typing indicators, callback administration. This is `RUNTIME_WABA_TOKEN`. |
| **Exchanged "business token"** — `business_token`, Step 4 | ES code exchange | No — see below | **Not guaranteed** | The Step 5 WABA subscription, and as an audit record. Nothing else, ever. |
| **Legacy per-client tokens** — e.g. `bloop_waa_token` | AWS, pre-dating the tech-provider setup | No | Yes | SFCS only. Do not mint new ones. |

### The exchanged token's problem is scope, not lifetime

With the current ES configuration ("Access token: System-user access token / Token
will never expire" — `waba_es_configuration.md`) the code exchange returns a
*client-business system-user* token that never expires. What varies is its
**granular scope**, which follows the Advanced Tasks granted during signup.

If the `messaging` task is not granted, the token silently carries
`whatsapp_business_management` only. Everything you would naturally test still
works — reading the phone number, reading and writing `subscribed_apps`, updating
the callback URL — and the failure surfaces only when a real customer sends a
message:

```
pywa.errors.WhatsAppError: WhatsAppError(code=100, message='Authorization Error',
    type='OAuthException', ...)
```

Meta rejects `POST /{phone_id}/messages` at the authorization layer, before it
parses the payload. There is no clue in the error that scope is the problem.

### Verifying any token's scope

```python
from utils_common.waba_es.api_funcs import debug_token
debug_token(some_token)   # app access token = waba_provider_app_id|app_secret
```

Requirements for a runtime credential:
- `is_valid: true`
- `scopes` includes `whatsapp_business_messaging`
- if `granular_scopes` lists `target_ids` for that scope, the client's WABA id must be in it
  (`target_ids: None` means unrestricted, which is what the provider token has)

`debug_token` only works when the token was issued by the **viewing app**. A token
from a different app returns `(#100) The App_id in the input_token did not match
the Viewing App` — that is a tooling limitation, not a verdict on the token.

### System-user inventory (as of 2026-08-20)

| Used by | System user | ID | Issuing app | Messaging scope |
|---|---|---|---|---|
| **All new clients** | `waba` | `122163057284680916` | EmbeddedSignupApp (2491523197914160) | Yes, unrestricted |
| SFCS | `waba` | `122176473128680916` | byteLoopAi (604290168832304) | Yes, unrestricted |
| ELAS | `TestAppForAppReview System User` | `122174415674964219` | EmbeddedSignupApp | Yes, on `['1529867968356425','2335277966870509']` |
| — (BNAT's broken token) | `EmbeddedSignupApp System User` | `122097067509449730` | EmbeddedSignupApp | **No** |

> **Trap:** two different system users are both named `waba`. Always select by ID
> in Business Suite, never by name.

> **Risk:** ELAS runs on a system user named "TestAppForAppReview System User" —
> the kind of asset that gets deleted in a tidy-up, which would take ELAS down with
> the same `#100`. Move it to the provider system user when convenient.

---

## Runtime Credential Policy

**Every ES-onboarded client uses the same `waba_provider_token` value. Never the
exchanged `business_token`.**

That token's granular targets are `None`, so it covers every WABA its system user
can reach — one credential, one rotation, no per-client decision to get wrong.

The value is copied into each namespace (`<ns>_waa_token`) rather than shared via a
single key. That is a deliberate choice: it keeps
`WabaBusinessSettings.for_namespace`'s "load one exact namespace and never fall
back" invariant intact. The cost is that rotating the provider token means editing
every `<ns>_waa_token`.

Alongside the token, set for each ES-onboarded namespace:

| Key | Value |
|---|---|
| `<ns>_waa_token` | the `waba_provider_token` value |
| `<ns>_waa_app_id` | `2491523197914160` (EmbeddedSignupApp) |
| `<ns>_waa_app_secret` | the provider app secret |

The app id/secret are inert at runtime (`WABA_VALIDATE_UPDATES = False`, ADR-0022),
but they make `restaurant_agent_runtime.waba_callback.validate_token_app_binding()`
a check that can actually pass rather than one that fails by construction.

**Open question, deliberately not assumed:** it is not established whether ES
automatically grants the provider system user access to a newly created client
WABA, or whether the manual assignment step is what does it. The policy does not
depend on the answer — Step 7's test message is the gate. To settle it, on the next
onboarding check whether the provider token can message the new phone *before*
doing any Business Suite assignment, and record the result here.

---

## Case Study: BNAT (2026-08-19)

Symptom: every inbound message raised `WhatsAppError(code=100, message='Authorization
Error')` from `msg.indicate_typing()`, the first line of the message handler.
Meanwhile updating the WABA callback URL from a notebook worked fine.

What made it confusing:
- Webhook verification passed — it only checks `verify_token`, which is the same
  dummy value across every namespace, so it proves nothing about credentials.
- Every management call succeeded, so the token looked healthy.
- `indicate_typing()` is unchanged since the monorepo's first commit, so the
  traceback pointed at code that was never wrong. It calls
  `POST /{phone_id}/messages` — the same endpoint as `send_message` — so it was
  simply the first thing to touch the broken credential.

What isolated it: sending a structurally invalid body (`{"messaging_product":
"whatsapp"}` — no recipient, no content, nothing deliverable) to
`POST /{phone_id}/messages` for both BNAT and a known-good namespace.
SFCS returned `The parameter to is required.` — authorization passed, payload
rejected. BNAT returned `Authorization Error` — stopped at authorization. That
isolates the credential from the payload without sending anything.

Root cause: `bnat_waa_token` held the ES-exchanged business token, whose scopes were
`["whatsapp_business_management", "public_profile"]`.

Why onboarding did not catch it: `onboard_business_customer()` tested one token and
stored another. `register_phone_number()` and `send_test_message()` used a
system-user token, while the exchanged token was what got persisted and later copied
into the runtime secret. The completion log said "save this !!!" next to it.

Fixed by: setting `bnat_waa_token` to the provider token value. `send_test_message()`
now sends with `RUNTIME_WABA_TOKEN` so the step validates the credential that
actually ships, and the misleading log line is gone.

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
# onboarding_utils.py line 60 — UPDATE THIS FOR EVERY ONBOARDING PROCESS
TEMP_STORE = {"phone_num": "00441689637476", "business_ref": "bnat"}
```

This is currently hardcoded and must be changed for each onboarding. `TEMP_STORE` is a **module-level singleton**, so it is shared across all requests to the process — only one onboarding can be in flight at a time, and stale keys from a previous run (`code`, `business_token`, `waba_id`, …) persist until overwritten. Verify the `Updated TEMP_STORE with WA data: {...}` log line shows the intended `business_ref`/`phone_num` before letting the flow proceed.

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

### Configuring the client for the restaurant-agents runtime

This is the step that was missing when BNAT broke. Nothing in the ES flow writes
these — they are added by hand to the AWS secret `restaurant-agents-env`.

1. Assign the new WABA to system user **`122163057284680916`** in Meta Business
   Suite with the `messaging` task (`waba_es_configuration.md`). Select by ID.
2. Add under the client's namespace prefix: `waa_phone_id`, `waa_account_id`,
   `waa_business_account_id`, `waa_verify_token`, `waa_callback_url`,
   `waa_private_key_password`.
3. Set `<ns>_waa_token`, `<ns>_waa_app_id`, `<ns>_waa_app_secret` per
   [Runtime Credential Policy](#runtime-credential-policy). **Do not paste
   `business_token` here.**
4. Boot the app and confirm its own view of the credential:
   ```bash
   curl -s http://<host>/details | python3 -m json.tool
   ```
   `details_errors` must be `{}`, `display_number` must be the client's number, and
   `token_hint` must match the provider token's last four characters.
5. Point the WABA callback at the deployment (above, or
   `restaurant-agents/notebooks/update_callback_url.py`).

Note `<ns>_waa_callback_url` is **diagnostics only** — it is read by `/details` and
the offline-mode router, never used to configure Meta. Stale values there are
harmless and currently present in several namespaces.

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `(#3) Application does not have the API granular permission` on test message | Wrong token used for messaging | Ensure `send_test_message()` uses `RUNTIME_WABA_TOKEN` |
| `(#100) Authorization Error` on every send at runtime, while callback/management calls succeed | The exchanged `business_token` was configured as `<namespace>_waa_token`; it lacks `whatsapp_business_messaging` | Configure `RUNTIME_WABA_TOKEN`'s value instead. Confirm with `api_funcs.debug_token()` — `scopes` must include `whatsapp_business_messaging` |
| Webhook verification passes but the agent still fails on every message | Verification only checks `verify_token`, which is the same dummy value in every namespace — it proves nothing about credentials or which client's WABA is wired up | Ignore verification as a signal; check `/details` and the token's scope instead |
| Assigned the WABA but the token still cannot message | Two different system users are both named `waba` — the wrong one was picked in Business Suite | Re-assign to ID `122163057284680916`; see [System-user inventory](#system-user-inventory-as-of-2026-08-20) |
| Messages to a client's number reach a laptop/tunnel instead of production | A stale WABA-level `override_callback_uri` from a past debugging session | `api_funcs.get_subscribed_apps(waba_id)` shows the effective override per subscribed app. Note each subscribed app has its own override, so two subscribed apps means the WABA delivers to both |
| `Unhandled event type: None` in logs | Raw (non-JSON) message events from FB SDK | Harmless — these are now handled and logged at debug level (`twilio_webhook.py:114`) |
| Phone registration takes >10 seconds | Normal for Meta — the reference run took **15.2 s** | No action needed, wait for completion |
| `No code found in TEMP_STORE` | `WA_EMBEDDED_SIGNUP` event arrived but `FB_AUTH_RESPONSE` did not | User may have closed the popup before completing auth — retry signup |
| `No WABA ID available` / `No phone number ID available` | `FB_AUTH_RESPONSE` arrived **before** `WA_EMBEDDED_SIGNUP`, so `TEMP_STORE` had no assets yet | Retry the signup. In the reference run the gap was ~380 ms in the correct order (`.211` → `.591`) |
| Onboarding runs against the wrong business | Stale `TEMP_STORE` singleton from a previous onboarding | Restart the process (or re-edit line 60) and re-check the `Updated TEMP_STORE with WA data` line |
| `waba_es` insert returns `409 Conflict` instead of `201 Created` | Duplicate record for the same `waba_id`/`phone_number_id` | Onboarding already ran for this business — inspect the existing row rather than re-running |
| WABA subscription fails | Business token expired or lacks permissions | Re-run signup flow to get a fresh auth code |
| Log ends after `Successfully obtained business token` with no `Step 2` | Supabase insert raised — caught by the outer `try` in `onboard_business_customer` | Check the `Error in onboard_business_customer` line; the business token is already in `temp_store.pkl`, so resume manually from `subscribe_app_to_waba` |

### Verifying a Successful Onboarding

1. Diff the run's logs against [Reference Log: Successful Onboarding](#reference-log-successful-onboarding) and work through the verification checklist there
2. Check `waba_es` table for the new record
3. Run `get_wabas_with_phone_numbers()` to confirm the WABA appears under the tech provider
4. Assign the new WABA to the system user — see `waba_es_configuration.md` → "Actions — Assign New WABA to System User". Select system user **`122163057284680916`** by ID
5. Send a test message via the Graph API or via the `send_test_message()` function
6. **Confirm the runtime credential's scope** before configuring the client — `debug_token()` must show `whatsapp_business_messaging`; see [Verifying any token's scope](#verifying-any-tokens-scope)
7. Complete [Configuring the client for the restaurant-agents runtime](#configuring-the-client-for-the-restaurant-agents-runtime)
8. Verify webhooks are received by checking app logs after sending a message to the new number
