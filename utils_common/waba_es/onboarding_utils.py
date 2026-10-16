"""
WhatsApp Business API onboarding utility functions for the embedded-signup webhook router.
    . Handles WhatsApp Business Account (WABA) onboarding process
    . Exchanges authorization codes for business tokens
    . Persists the onboarding record to temp_store.pkl and the `waba_es` Supabase table
    . Subscribes applications to WABA for webhook notifications
    . Registers phone numbers for WhatsApp messaging
    . Sends test messages to verify successful setup
    . Temporarily stores display phone number (if present) as TEMP_STORE['phone_num']
    . Driven by watomation/routers/twilio_webhook.py:waba_embedded_signup_callback on FB_AUTH_RESPONSE
  Functions/Classes:
    . exchange_code_for_business_token - Exchanges authorization code for business access token
    . subscribe_app_to_waba - Subscribes the app to WhatsApp Business Account
    . update_pin - Sets the two-step verification PIN (intentionally disabled in the orchestrator)
    . register_phone_number - Registers phone number for WhatsApp messaging
    . send_test_message - Sends a test message to verify setup
    . onboard_business_customer - Main orchestration function for complete onboarding
    . get_assigned_users - Diagnostic: lists users assigned to a WABA
  Expected log signature of a healthy run (elapsed times from the 2026-08-19 reference run):
    . "Step 1: Exchanging code for business token"  -> "Successfully obtained business token"  (~1.1s)
    . httpx POST .../rest/v1/waba_es "HTTP/2 201 Created"                                      (~0.2s)
    . "Step 2: Subscribing app to WABA"             -> "Successfully subscribed app to WABA"   (~1.2s)
    . "Step 3: Registering customer's phone number" -> "Successfully registered phone number"  (~15.2s, slowest)
    . "Step 4: Sending test message"                -> "Successfully sent test message"        (~1.2s)
    . "Business customer onboarding completed successfully: {...}"                             (~18.8s total)
    . "Runtime credential for this client is the shared system-user token ..."                  (immediately after)
    . "Step 2.5: Updating PIN for phone number" must NOT appear - update_pin() is commented out
    . Full annotated transcript + verification checklist: utils_common/waba_es/embedded_signup_guide.md
  Caveats:
    . TEMP_STORE is a module-level singleton - only one onboarding may be in flight per process,
      and stale keys from a previous run persist until overwritten
    . The completion log line emits the raw `code` and `business_token` at INFO level;
      scrub logs before sharing them outside the team

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . waba_es (table, ordelo_datamodels/core/waba_es.sql): inserts, named in code (passed to a query helper)
(end of database objects)
"""

# %%
import requests
from loguru import logger
from typing import Dict, Any
from config import waba_business_settings, waba_provider_settings
import pickle
from config import client_ordelo


# waba_business_settings.token
# %%

# Configuration constants
waba_es_app_id = waba_provider_settings.app_id
waba_es_app_secret = waba_provider_settings.app_secret
waba_es_configuration_id = waba_provider_settings.configuration_id
waba_es_graph_api_version = waba_provider_settings.graph_api_version
waba_es_pin = waba_provider_settings.pin
waba_business_protfolio_id = waba_provider_settings.business_portfolio_id

# The credential a deployed restaurant agent uses at runtime. This is
# deliberately NOT the token returned by the ES code exchange.
#
# The exchanged token is a client-business system-user token whose granular
# scopes depend on the Advanced Tasks granted during signup. It is only
# guaranteed `whatsapp_business_management`; if the `messaging` task is not
# granted it silently lacks `whatsapp_business_messaging`, every management
# call still succeeds, and the first real customer message fails with
# OAuthException #100 "Authorization Error". That is exactly what happened to
# BNAT (WABA 1370775671249488) — onboarding passed because the steps below
# test with a system-user token, while the exchanged token was the one stored.
#
# Verify any replacement with api_funcs.debug_token(): it must list
# `whatsapp_business_messaging` in scopes.
RUNTIME_WABA_TOKEN = waba_provider_settings.token

# %% UPDATE THIS FOR EVERY ONBOARDING PROCES
# Module-level singleton. twilio_webhook.waba_embedded_signup_callback fills in
# phone_number_id / waba_id / business_id / event_type on WA_EMBEDDED_SIGNUP, then
# `code` on FB_AUTH_RESPONSE. Confirm the "Updated TEMP_STORE with WA data: {...}"
# log line shows the intended business_ref/phone_num before the flow proceeds.
TEMP_STORE = {"phone_num": "00441689637476", "business_ref": "bnat"}
# %%
# register_phone_number(phone_number_id="", business_token="")

# %%


def exchange_code_for_business_token(code: str) -> Dict[str, Any]:
    """Exchange authorization code for business access token.

    GET https://graph.facebook.com/v21.0/oauth/access_token — note the pinned v21.0,
    unlike the other calls which use waba_es_graph_api_version.

    Logs on success: "Step 1: Exchanging code for business token" then
    "Successfully obtained business token" (~1.1s apart in the reference run).
    The code is single-use; a replayed code fails with "Failed to get access token".

    Args:
        code: Authorization code from WhatsApp Business signup flow

    Returns:
        Dict containing status and either token or error message
    """
    try:
        logger.info("Step 1: Exchanging code for business token")
        token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
        token_params = {
            "client_id": waba_es_app_id,
            "client_secret": waba_es_app_secret,
            "code": code,
        }

        token_response = requests.get(token_url, params=token_params)
        if token_response.status_code != 200:
            logger.error(f"Failed to get access token: {token_response.text}")
            return {"status": "error", "message": "Failed to get access token"}

        token_data = token_response.json()
        business_token = token_data.get("access_token")

        if not business_token:
            logger.error("No access token in response")
            return {"status": "error", "message": "No access token received"}

        logger.info("Successfully obtained business token")
        return {"status": "success", "token": business_token}

    except Exception as e:
        logger.error(f"Error exchanging code for token: {str(e)}")
        return {"status": "error", "message": f"Token exchange failed: {str(e)}"}


# %%


def subscribe_app_to_waba(waba_id: str, business_token: str) -> Dict[str, Any]:
    """Subscribe the app to WhatsApp Business Account.

    Required for webhook delivery; without it sends fail with OAuthException #3.

    Logs on success: "Step 2: Subscribing app to WABA" then
    "Successfully subscribed app to WABA" (~1.2s apart in the reference run).
    Verify afterwards with api_funcs.get_subscribed_apps(waba_id).

    Args:
        waba_id: WhatsApp Business Account ID
        business_token: Business access token

    Returns:
        Dict containing status and message
    """
    try:
        logger.info("Step 2: Subscribing app to WABA")
        subscribe_url = f"https://graph.facebook.com/{waba_es_graph_api_version}/{waba_id}/subscribed_apps"
        headers = {"Authorization": f"Bearer {business_token}"}

        subscribe_response = requests.post(subscribe_url, headers=headers)
        if subscribe_response.status_code not in [200, 201]:
            logger.error(f"Failed to subscribe app to WABA: {subscribe_response.text}")
            return {"status": "error", "message": "Failed to subscribe app to WABA"}

        logger.info("Successfully subscribed app to WABA")
        return {"status": "success", "message": "App subscribed to WABA"}

    except Exception as e:
        logger.error(f"Error subscribing app to WABA: {str(e)}")
        return {"status": "error", "message": f"WABA subscription failed: {str(e)}"}


# %%


def update_pin(
    phone_number_id: str, business_token: str, pin: str = waba_es_pin
) -> Dict[str, Any]:
    """Update PIN for phone number before registration.

    NOT called by onboard_business_customer — register_phone_number() passes the PIN
    inline instead. A "Step 2.5: Updating PIN for phone number" line in the logs
    therefore means someone re-enabled this call; the reference run has no such line.

    Args:
        phone_number_id: Phone number ID to update PIN for
        business_token: Business access token
        pin: PIN to set for the phone number

    Returns:
        Dict containing status and message
    """
    try:
        logger.info("Step 2.5: Updating PIN for phone number")
        update_pin_url = f"https://graph.facebook.com/v23.0/{phone_number_id}"
        headers = {
            "Authorization": f"Bearer {business_token}",
            "Content-Type": "application/json",
        }
        pin_data = {"pin": pin}

        pin_response = requests.post(update_pin_url, headers=headers, json=pin_data)
        if pin_response.status_code not in [200, 201]:
            logger.error(f"Failed to update PIN: {pin_response.text}")
            return {"status": "error", "message": "Failed to update PIN"}

        logger.info("Successfully updated PIN")
        return {"status": "success", "message": "PIN updated"}

    except Exception as e:
        logger.error(f"Error updating PIN: {str(e)}")
        return {"status": "error", "message": f"PIN update failed: {str(e)}"}


def register_phone_number(phone_number_id: str) -> Dict[str, Any]:
    """Register phone number for WhatsApp messaging.

    Uses the system user token (waba_business_settings.token), not the exchanged
    business token, and passes the PIN inline instead of calling update_pin().

    Logs on success: "Step 3: Registering customer's phone number" then
    "Successfully registered phone number". This is the slowest step by far —
    ~15.2s in the reference run — so keep any client timeout well above ~45s.

    Args:
        phone_number_id: Phone number ID to register

    Returns:
        Dict containing status and message
    """
    try:
        logger.info("Step 3: Registering customer's phone number")
        register_url = f"https://graph.facebook.com/{waba_es_graph_api_version}/{phone_number_id}/register"
        headers = {"Authorization": f"Bearer {waba_business_settings.token}"}
        register_data = {
            "messaging_product": "whatsapp",
            "pin": "141414",
            # "certificate": cert,
        }

        register_response = requests.post(
            register_url, headers=headers, json=register_data
        )
        if register_response.status_code not in [200, 201]:
            logger.error(f"Failed to register phone number: {register_response.text}")
            return {"status": "error", "message": "Failed to register phone number"}

        logger.info("Successfully registered phone number")
        return {"status": "success", "message": "Phone number registered"}

    except Exception as e:
        logger.error(f"Error registering phone number: {str(e)}")
        return {"status": "error", "message": f"Phone registration failed: {str(e)}"}


# %%


def send_test_message(
    phone_number_id: str, recipient: str = "447448440754"
) -> Dict[str, Any]:
    """Send a test message to verify WhatsApp setup.

    Sends with RUNTIME_WABA_TOKEN — the same token the deployed agent will use
    — so this step validates the credential that actually ships, not merely
    "some token that can send". The exchanged business token is never used
    here; it may lack `whatsapp_business_messaging` entirely.

    If this step fails, the client's WABA is most likely not assigned to the
    system user with the messaging task. See waba_es_configuration.md ->
    "Actions - Assign New WABA to System User".

    Logs on success: "Step 4: Sending test message" then "Successfully sent test
    message" (~1.2s apart in the reference run). A 200 here only proves the Graph
    API accepted the send — always confirm the message lands on the recipient
    handset before declaring the onboarding complete.

    Args:
        phone_number_id: Phone number ID to send from
        recipient: Phone number to send test message to

    Returns:
        Dict containing status and message
    """
    try:
        logger.info("Step 4: Sending test message")
        messages_url = f"https://graph.facebook.com/{waba_es_graph_api_version}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {RUNTIME_WABA_TOKEN}"}
        message_data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"body": "Business account successfully registered"},
        }

        message_response = requests.post(
            messages_url, headers=headers, json=message_data
        )
        if message_response.status_code not in [200, 201]:
            logger.error(f"Failed to send test message: {message_response.text}")
            return {"status": "error", "message": "Failed to send test message"}

        logger.info("Successfully sent test message")
        return {"status": "success", "message": "Test message sent"}

    except Exception as e:
        logger.error(f"Error sending test message: {str(e)}")
        return {"status": "error", "message": f"Test message failed: {str(e)}"}


async def onboard_business_customer(TEMP_STORE):
    """Onboard business customer using stored data from TEMP_STORE.

    Orchestrates the complete onboarding process:
    1. Exchange code for business token
    1a. Persist TEMP_STORE to temp_store.pkl and the `waba_es` table (expect 201 Created)
    2. Subscribe app to WABA
    3. Register phone number
    4. Send test message

    Fails fast: each step returns {"status": "error", ...} and the chain stops, so the
    last "Step N:" line without a matching "Successfully ..." line identifies the failure
    point. Whatever ran before it is NOT rolled back — the `waba_es` row and the business
    token survive, so a partial run can be resumed manually from the failing step.

    Requires TEMP_STORE to already hold `waba_id` and `phone_number_id` from the earlier
    WA_EMBEDDED_SIGNUP event; if FB_AUTH_RESPONSE arrives first this returns
    "No WABA ID available" / "No phone number ID available".

    Final log lines on success: "Business customer onboarding completed successfully:
    {...}" — ~18.8s after the auth code arrives — followed by a line naming the runtime
    credential. The first contains the raw `code` and `business_token`, so scrub it
    before sharing logs. Neither token in that dict is the client's runtime credential;
    see RUNTIME_WABA_TOKEN.
    See utils_common/waba_es/embedded_signup_guide.md for the annotated reference log.

    Returns:
        Dict containing status, message, and data if successful
    """
    try:
        code = TEMP_STORE.get("code")
        waba_id = TEMP_STORE.get("waba_id")
        phone_number_id = TEMP_STORE.get("phone_number_id")

        # Validate required data
        if not code:
            logger.error("No code found in TEMP_STORE")
            return {"status": "error", "message": "No code available"}

        if not waba_id:
            logger.error("No waba_id found in TEMP_STORE")
            return {"status": "error", "message": "No WABA ID available"}

        if not phone_number_id:
            logger.error("No phone_number_id found in TEMP_STORE")
            return {"status": "error", "message": "No phone number ID available"}

        # Step 1: Exchange code for business token
        token_result = exchange_code_for_business_token(code)
        if token_result["status"] != "success":
            return token_result

        business_token = token_result["token"]
        # Recorded for audit and used for the WABA subscription below. It is
        # NOT the client's runtime credential — see RUNTIME_WABA_TOKEN.
        TEMP_STORE["business_token"] = business_token
        # Write TempStore to pickle file and to sbase
        with open("temp_store.pkl", "wb") as f:
            pickle.dump(TEMP_STORE, f)

        client_ordelo.table("waba_es").insert(TEMP_STORE).execute()
        # with open("/home/basal/PycharmProjects/OrdeloAgent/temp_store.pkl", "rb") as f:
        #     temp_store = pickle.load(f)
        #     print(temp_store)

        # Step 2: Subscribe app to WABA
        subscribe_result = subscribe_app_to_waba(waba_id, business_token)
        if subscribe_result["status"] != "success":
            return subscribe_result

        # # Step 2.5: Update PIN for phone number
        # pin_result = update_pin(phone_number_id, business_token)
        # if pin_result["status"] != "success":
        #     return pin_result

        # Step 3: Register phone number
        register_result = register_phone_number(phone_number_id)
        if register_result["status"] != "success":
            return register_result

        # Step 4: Send test message (uses system user token, not business_token)
        message_result = send_test_message(phone_number_id)
        if message_result["status"] != "success":
            return message_result

        logger.info(
            f"Business customer onboarding completed successfully: {TEMP_STORE}"
        )
        logger.info(
            "Runtime credential for this client is the shared system-user token "
            "(waba_provider_token) — already validated by the test message above. "
            "Do NOT copy business_token into <namespace>_waa_token; it is the ES "
            "exchange artefact and may lack whatsapp_business_messaging."
        )
        return {
            "status": "success",
            "message": "Business customer onboarded successfully",
            "data": {
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
                # Truncated for security. Audit/subscription artefact only.
                "business_token": business_token[:20] + "...",
                # The credential to configure as <namespace>_waa_token.
                "runtime_token_source": "waba_provider_token",
            },
        }

    except Exception as e:
        logger.error(f"Error in onboard_business_customer: {str(e)}")
        return {"status": "error", "message": f"Onboarding failed: {str(e)}"}


# %% get assigned users
def get_assigned_users(waba_id: str) -> Dict[str, Any]:
    try:
        logger.info("Step 5: Getting assigned users")
        assigned_users_url = f"https://graph.facebook.com/{waba_es_graph_api_version}/{waba_id}/assigned_users"
        business_id = "1812432326161275"
        params = {"business": business_id}
        headers = {"Authorization": f"Bearer {waba_provider_settings.token}"}
        assigned_users_response = requests.get(
            assigned_users_url, headers=headers, params=params
        )
        if assigned_users_response.status_code not in [200, 201]:
            logger.error(
                f"Failed to get assigned users: {assigned_users_response.text}"
            )
            return {"status": "error", "message": "Failed to get assigned users"}

        logger.info("Successfully got assigned users")
        return {"status": "success", "message": "Assigned users retrieved"}

    except Exception as e:
        logger.error(f"Error getting assigned users: {str(e)}")
        return {
            "status": "error",
            "message": f"Assigned users retrieval failed: {str(e)}",
        }


# waba_business_settings.business_account_id, waba_business_settings.account_id
