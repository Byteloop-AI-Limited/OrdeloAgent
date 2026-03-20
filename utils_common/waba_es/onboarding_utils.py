"""
WhatsApp Business API onboarding utility functions for Twilio webhook router.
    . Handles WhatsApp Business Account (WABA) onboarding process
    . Exchanges authorization codes for business tokens
    . Subscribes applications to WABA for webhook notifications
    . Registers phone numbers for WhatsApp messaging
    . Sends test messages to verify successful setup
    . Temporarily stores display phone number (if present) as TEMP_STORE['phone_num']
  Functions/Classes:
    . exchange_code_for_business_token - Exchanges authorization code for business access token
    . subscribe_app_to_waba - Subscribes the app to WhatsApp Business Account
    . register_phone_number - Registers phone number for WhatsApp messaging
    . send_test_message - Sends a test message to verify setup
    . onboard_business_customer - Main orchestration function for complete onboarding
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

# %% UPDATE THIS FOR EVERY ONBOARDING PROCES
TEMP_STORE = {"phone_num": "00441722433714", "business_ref": "elas"}
# %%
# register_phone_number(phone_number_id="", business_token="")

# %%


def exchange_code_for_business_token(code: str) -> Dict[str, Any]:
    """Exchange authorization code for business access token.

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
    phone_number_id: str, business_token: str, recipient: str = "447448440754"
) -> Dict[str, Any]:
    """Send a test message to verify WhatsApp setup.

    Args:
        phone_number_id: Phone number ID to send from
        business_token: Business access token
        recipient: Phone number to send test message to

    Returns:
        Dict containing status and message
    """
    try:
        logger.info("Step 4: Sending test message")
        messages_url = f"https://graph.facebook.com/{waba_es_graph_api_version}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {business_token}"}
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
    2. Subscribe app to WABA
    3. Register phone number
    4. Send test message

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

        # Step 4: Send test message
        message_result = send_test_message(phone_number_id, business_token)
        if message_result["status"] != "success":
            return message_result

        logger.info(
            f"Business customer onboarding completed successfully, save this !!!: {TEMP_STORE}"
        )
        return {
            "status": "success",
            "message": "Business customer onboarded successfully",
            "data": {
                "waba_id": waba_id,
                "business_token": business_token[:20] + "...",  # Truncated for security
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
