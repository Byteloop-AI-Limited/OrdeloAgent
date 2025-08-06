# %%
import httpx
from config.waba_setting import waba_business_settings

(
    waba_business_settings.phone_id,
    waba_business_settings.business_account_id,
    # waba_business_settings.token,
)


# %% Methods for Creating and deleting whatsapp templates


def get_whatsapp_template():
    """
    Retrieve a WhatsApp message template by its ID via the Facebook Graph API.
    Args:
        message_template_id (str): The ID of the WhatsApp message template.
    Returns:
        httpx.Response: The response from the Graph API.
    """
    url = f"https://graph.facebook.com/v22.0/{waba_business_settings.business_account_id}/message_templates"
    headers = waba_business_settings.headers
    # params = {"name": template_name}
    with httpx.Client() as client:
        print(f"Calling {url}")
        response = client.get(url, headers=headers)
        print(f"Status: {response.status_code}, Response: {response.text}")
        return response


def create_whatsapp_template(
    name: str,
    category: str,
    language: str,
    components: list,
    parameter_format: str = "POSITIONAL",
):
    """
    Create a WhatsApp template via the Facebook Graph API.
    Args:
        business_account_id (str): WhatsApp Business Account ID.
        name (str): Template name.
        category (str): Template category (e.g. UTILITY, MARKETING, AUTHENTICATION).
        language (str): Language/locale code (e.g. en_US).
        components (list): List of template components (BODY, BUTTONS, etc).
        parameter_format (str): NAMED or POSITIONAL (default POSITIONAL).
        library_template_name (str): Optional. Name of Template Library template.
    Returns:
        httpx.Response: The response from the Graph API.
    """
    url = f"https://graph.facebook.com/v22.0/{waba_business_settings.business_account_id}/message_templates"
    headers = waba_business_settings.headers
    body = {
        "name": name,
        "category": category,
        "parameter_format": parameter_format,
        "language": language,
        "components": components,
    }
    with httpx.Client() as client:
        print(f"Calling {url} with body {body}")
        response = client.post(url, headers=headers, json=body)
        print(f"Status: {response.status_code}, Response: {response.text}")
        return response


def delete_whatsapp_template(template_name: str):
    """
    Delete a WhatsApp template by name via the Facebook Graph API.
    Args:
        template_name (str): The name of the template to delete.
    Returns:
        httpx.Response: The response from the Graph API.
    """
    url = f"https://graph.facebook.com/v22.0/{waba_business_settings.business_account_id}/message_templates"
    headers = waba_business_settings.headers
    params = {"name": template_name}
    with httpx.Client() as client:
        print(f"Calling {url} with params {params}")
        response = client.delete(url, headers=headers, params=params)
        print(f"Status: {response.status_code}, Response: {response.text}")
        return response


async def send_whatsapp_template_message(recipient: str):
    """
    Send a WhatsApp template message using the Facebook Graph API via httpx.
    Args:
        recipient (str): WhatsApp recipient phone number (international format, no +).
    """

    url = f"https://graph.facebook.com/v22.0/{waba_business_settings.phone_id}/messages"
    headers = waba_business_settings.headers

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {"name": "hello_world", "language": {"code": "en_US"}},
    }

    async with httpx.AsyncClient() as client:
        print(f"Calling {url} with payload {payload}")
        response = await client.post(url, headers=headers, json=payload)
        print(f"Status: {response.status_code}, Response: {response.text}")
        return response


# %% Creating a WhatsApp message template

create_whatsapp_template(
    name="app_review_template",
    category="MARKETING",
    language="en_US",
    components=[{"type": "BODY", "text": "Hello World"}],
)

# %% Get/Read WhatsApp message template
response = get_whatsapp_template()
templates = response.json()["data"]
for template in templates:
    print(f"Name: {template['name']}, Status: {template['status']}")

# %% Deleting a template

delete_whatsapp_template("app_review_template")

# %% Sending a template message
from pywa import WhatsApp
from pywa.types import Template as Temp
from config import _sync_wa_client as wa

wa.send_template(
    to="447448440754",
    template=Temp(
        name="hello_world",
        language=Temp.Language.ENGLISH_US,
    ),
)
