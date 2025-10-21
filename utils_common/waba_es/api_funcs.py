# %%
"""
Utilities for WhatsApp Business Account (WABA) Graph API interactions
  . Centralizes wrappers around Facebook Graph endpoints used by the project
  . Fetches assigned WABAs for the configured business/tech provider
  . Lists phone numbers for a given WABA
  . Provides a merged helper to get all WABAs with their phone numbers in one call
 Functions/Classes
  . get_assigned_wabas
  . list_phone_numbers_for_waba
  . get_wabas_with_phone_numbers
 Key Functions:
  . get_assigned_wabas - Returns the WABAs assigned to the configured business
  . list_phone_numbers_for_waba - Lists phone numbers for a WABA id
  . get_wabas_with_phone_numbers - Returns all assigned WABAs and their phone numbers
"""

# %%
from pywa import WhatsApp
from config import waba_business_settings, logger, waba_provider_settings
from typing import Dict, Any, List
import requests

# %%

(
    waba_business_settings,
    # waba_business_settings.business_account_id,
    waba_provider_settings,
)

# %%

token = waba_business_settings.token
phone_number_id = "813532365168347"
phone_number_id = "813532365168347"

# %%

wa = WhatsApp(
    token=token,
    # business_account_id=waba_business_settings.account_id,
    # verify_token=waba_business_settings.verify_token,
    phone_id=phone_number_id,
)

# %%
# wa.update_business_profile(
#     # about="South indian restaurant",
#     websites=("https://www.elai.uk/"),
# )
# wa.get_business_phone_number()
# wa.get_business_profile()
waba_business_settings


# %% Get onboarded wabas
def get_assigned_wabas() -> Dict[str, Any]:
    """
    Note the business_id is the business_protfolio_id from the business profile
    """
    try:
        logger.info("Step 5: Getting assigned WABAs")
        assigned_wabas_url = f"https://graph.facebook.com/v23.0/{waba_provider_settings.business_portfolio_id}/client_whatsapp_business_accounts"
        business_id = waba_business_settings.account_id
        params = {"business": business_id}
        headers = {"Authorization": f"Bearer {waba_provider_settings.token}"}
        assigned_wabas_response = requests.get(
            assigned_wabas_url, headers=headers, params=params
        )
        if assigned_wabas_response.status_code not in [200, 201]:
            logger.error(
                f"Failed to get assigned WABAs: {assigned_wabas_response.text}"
            )
            return {"status": "error", "message": "Failed to get assigned WABAs"}

        logger.info("Successfully got assigned WABAs")
        return assigned_wabas_response.json()

    except Exception as e:
        logger.error(f"Error getting assigned WABAs: {str(e)}")
        return {
            "status": "error",
            "message": f"Assigned WABAs retrieval failed: {str(e)}",
        }


# %%


def get_wabas_with_phone_numbers() -> Dict[str, Any]:
    """
    Retrieves all assigned WABAs and, for each, fetches their phone numbers.

    Returns a payload in the form:
      {
        "status": "success",
        "count": <int>,
        "wabas": [
          {"waba_id": <str>, "phone_numbers": [ {...}, ... ]},
          ...
        ]
      }
    or an error dict with status = "error".
    """
    try:
        assigned = get_assigned_wabas()
        if isinstance(assigned, dict) and assigned.get("status") == "error":
            return assigned

        wabas = assigned.get("data", [])
        results: List[Dict[str, Any]] = []

        for waba in wabas:
            waba_id = waba.get("id") if isinstance(waba, dict) else None
            if not waba_id:
                continue

            pn = list_phone_numbers_for_waba(waba_id)
            if isinstance(pn, dict) and pn.get("status") == "error":
                logger.error(
                    f"Failed to fetch phone numbers for WABA {waba_id}: {pn.get('message')}"
                )
                results.append(
                    {
                        "waba_id": waba_id,
                        "phone_numbers": [],
                        "error": pn.get("message"),
                    }
                )
            else:
                phone_numbers = pn.get("data", pn) if isinstance(pn, dict) else pn
                results.append({"waba_id": waba_id, "phone_numbers": phone_numbers})

        return {"status": "success", "count": len(results), "wabas": results}
    except Exception as e:
        logger.error(f"Error merging WABAs with phone numbers: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to get WABAs with phone numbers: {str(e)}",
        }


def list_phone_numbers_for_waba(waba_id: str) -> Dict[str, Any]:
    try:
        phone_numbers_url = f"https://graph.facebook.com/v23.0/{waba_id}/phone_numbers"
        # params = {"fields": "display_phone_number,verified_name,id"}
        headers = {"Authorization": f"Bearer {waba_provider_settings.token}"}
        phone_numbers_response = requests.get(
            phone_numbers_url,
            headers=headers,
            # , params=params
        )
        if phone_numbers_response.status_code not in [200, 201]:
            logger.error(f"Failed to list phone numbers: {phone_numbers_response.text}")
            return {"status": "error", "message": "Failed to list phone numbers"}

        logger.info("Successfully listed phone numbers")
        return phone_numbers_response.json()

    except Exception as e:
        logger.error(f"Error listing phone numbers: {str(e)}")
        return {
            "status": "error",
            "message": f"Phone numbers listing failed: {str(e)}",
        }


# %% Display all the details of WABA associated to tech provider

# Example manual calls (avoid running on import)
# get_assigned_wabas()
get_wabas_with_phone_numbers()
# list_phone_numbers_for_waba(waba_id="2335277966870509")
# get_wabas_with_phone_numbers()
# %% IMPORTANT: Once the emebedded signup is complete, do the number registration. Dont forget, the token is from the business account, stored in the db
# %%
# get phone number id from the output of get_wabas_with_phone_numbers
phone_number_id = 796698196867835
waba_es_graph_api_version = waba_provider_settings.graph_api_version
register_phone_number(phone_number_id)


# %%


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


# %% Overriding callback URL
from pywa import WhatsApp
from config import waba_business_settings

wa = WhatsApp(
    token=waba_business_settings.token,
    phone_id=waba_business_settings.phone_id,
)

wa.override_waba_callback_url(
    callback_url="https://6q5ecb-ip-217-39-41-153.tunnelmole.net",
    verify_token="123456",
    waba_id="2242211042906352",
)

wa.update_business_profile(
    about="Best Movers in London",
)
