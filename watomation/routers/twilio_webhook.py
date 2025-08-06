"""
Alert hooks router for OrdeloAgent FastAPI service.
    . Defines endpoints for receiving alert and failure notifications
    . Implements webhook pattern for database-triggered alert events
    . Handles both JSON (DB trigger) and form-encoded (Twilio SMS) webhook payloads
    . Logs payloads and supports future extension for business logic
    . Ensures robust handling of empty, malformed, or unexpected webhook payloads
  Functions/Classes:
    . get_payload - Extracts JSON payload from request with empty fallback
    . get_pool - Returns the async connection pool from FastAPI app state
    . failure_notifications - Handles Twilio SMS and DB trigger notifications
"""

from fastapi import APIRouter, Request, Form, Response
from loguru import logger
from twilio.twiml.voice_response import VoiceResponse

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os
import requests
from fastapi.responses import RedirectResponse, HTMLResponse

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
templates = Jinja2Templates(directory=os.path.join(Path(__file__).parent, "templates"))
app_id = "249******"
app_secret = "6d2e******"
configuration_id = "240******"
graph_api_version = "v22.0"


async def get_payload(request: Request):
    """Return request body as JSON (may be empty)."""
    try:
        return await request.json()
    except Exception:
        # In case of an empty body or invalid JSON we still return an empty dict.
        return {}


async def get_pool(request: Request):
    """Return the async connection pool stored in FastAPI app state."""
    return request.app.state.pool


# ---------------------------------------------------------------------------
# Router & Endpoints
# ---------------------------------------------------------------------------

router = APIRouter(tags=["twilio_webhook"])


@router.get("/waba-embedded-signup", response_class=HTMLResponse)
async def waba_embedded_signup(request: Request):
    """Render the removals collection form."""

    return templates.TemplateResponse(
        "waba_embedded_signup.html",
        {
            "request": request,
            "app_id": app_id,
            "graph_api_version": graph_api_version,
            "configuration_id": configuration_id,
        },
    )


TEMP_STORE = {}


async def onboard_business_customer():
    """Onboard business customer using stored data from TEMP_STORE."""
    try:
        code = TEMP_STORE.get("code")
        waba_id = TEMP_STORE.get("waba_id")

        if not code:
            logger.error("No code found in TEMP_STORE")
            return {"status": "error", "message": "No code available"}

        if not waba_id:
            logger.error("No waba_id found in TEMP_STORE")
            return {"status": "error", "message": "No WABA ID available"}

        # Step 1: Exchange code for business_token
        logger.info("Step 1: Exchanging code for business token")
        token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
        token_params = {"client_id": app_id, "client_secret": app_secret, "code": code}

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
        TEMP_STORE["business_token"] = business_token

        # Step 2: Subscribe app to WABA
        logger.info("Step 2: Subscribing app to WABA")
        subscribe_url = (
            f"https://graph.facebook.com/{graph_api_version}/{waba_id}/subscribed_apps"
        )
        headers = {"Authorization": f"Bearer {business_token}"}

        subscribe_response = requests.post(subscribe_url, headers=headers)
        if subscribe_response.status_code not in [200, 201]:
            logger.error(f"Failed to subscribe app to WABA: {subscribe_response.text}")
            return {"status": "error", "message": "Failed to subscribe app to WABA"}

        logger.info("Successfully subscribed app to WABA")

        # Step 3: Register the customer's phone number
        logger.info("Step 3: Registering customer's phone number")
        phone_number_id = TEMP_STORE.get("phone_number_id")
        if not phone_number_id:
            logger.error("No phone_number_id found in TEMP_STORE")
            return {"status": "error", "message": "No phone number ID available"}

        register_url = (
            f"https://graph.facebook.com/{graph_api_version}/{phone_number_id}/register"
        )
        register_data = {"messaging_product": "whatsapp", "pin": "141414"}

        register_response = requests.post(
            register_url, headers=headers, json=register_data
        )
        if register_response.status_code not in [200, 201]:
            logger.error(f"Failed to register phone number: {register_response.text}")
            return {"status": "error", "message": "Failed to register phone number"}

        logger.info("Successfully registered phone number")

        # Step 4: Send a test message
        logger.info("Step 4: Sending test message")
        messages_url = (
            f"https://graph.facebook.com/{graph_api_version}/{phone_number_id}/messages"
        )
        message_data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "447448440754",
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


@router.post("/waba-embedded-signup")
async def waba_embedded_signup_callback(request: Request):
    """Process WhatsApp embedded signup event data from frontend."""
    try:
        # Get JSON data from request body
        event_data = await request.json()
        logger.info(f"Received event: {event_data}")

        # Handle WA_EMBEDDED_SIGNUP event
        if event_data.get("type") == "WA_EMBEDDED_SIGNUP":
            # Extract WhatsApp business data and update TEMP_STORE
            data = event_data.get("data", {})
            TEMP_STORE["phone_number_id"] = data.get("phone_number_id")
            TEMP_STORE["waba_id"] = data.get("waba_id")
            TEMP_STORE["business_id"] = data.get("business_id")
            TEMP_STORE["event_type"] = event_data.get("event")

            logger.info(f"Updated TEMP_STORE with WA data: {TEMP_STORE}")
            return {"status": "success", "message": "WA_EMBEDDED_SIGNUP data stored"}

        # Handle FB_AUTH_RESPONSE event
        elif event_data.get("type") == "FB_AUTH_RESPONSE":
            # Extract code and update TEMP_STORE
            auth_response = event_data.get("authResponse", {})
            code = auth_response.get("code")
            TEMP_STORE["code"] = code

            logger.info(f"Updated TEMP_STORE with auth code: {code}")

            # Call onboard_business_customer function
            onboard_result = await onboard_business_customer()
            return onboard_result

        else:
            logger.warning(f"Unhandled event type: {event_data.get('type')}")
            return {"status": "ignored", "message": "Event type not handled"}

    except Exception as e:
        logger.error(f"Error processing callback: {str(e)}")
        return {"status": "error", "message": f"Failed to process callback: {str(e)}"}


@router.post("/failure-notifications")
async def failure_notifications(
    from_number: str = Form(..., alias="From"),
    body: str = Form(..., alias="Body"),
    message_sid: str = Form(None, alias="MessageSid"),
):
    """
    Handle both:
      - Twilio SMS (form-encoded with From, Body, etc.)
      - DB trigger JSON (fallback)

    Returns {"status":"success"} unconditionally.
    """
    logger.info("SMS from {} ({}): {}", from_number, message_sid, body)
    # TODO: do something with `body`…
    return {"status": "success"}


@router.post("/voice")
async def voice():
    """Return TwiML that records the caller's message."""
    resp = VoiceResponse()
    # resp.say("Please leave your message after the beep. Press pound when finished.")
    resp.record(
        action="/voice/recording", method="POST", max_length=120, finish_on_key="#"
    )
    resp.say("Goodbye")
    return Response(content=str(resp), media_type="application/xml")


@router.post("/voice/recording")
async def handle_recording(
    recording_url: str = Form(..., alias="RecordingUrl"),
    recording_duration: str = Form(..., alias="RecordingDuration"),
    call_sid: str = Form(..., alias="CallSid"),
):
    """Process completed recordings from Twilio."""
    logger.info(
        "Received recording for CallSid=%s URL=%s Duration=%ss",
        call_sid,
        recording_url,
        recording_duration,
    )
    # TODO: save URL to database, trigger transcription, notify user, etc.
    return {"status": "success"}


# https://agent.ordelo.app/twilio-webhook/voice
# https://agent.ordelo.app/twilio-webhook/failure-notifications


# # Twilio credentials from env vars
# TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
# TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# @router.post("/voice/recording")
# async def handle_recording(
#     recording_url: str = Form(..., alias="RecordingUrl"),
#     recording_sid: str = Form(..., alias="RecordingSid"),
#     recording_duration: str = Form(..., alias="RecordingDuration"),
#     call_sid: str = Form(..., alias="CallSid"),
#     from_number: str = Form(None, alias="From")
# ):
#     """
#     1. Download the MP3
#     2. Save locally under /recordings/{RecordingSid}.mp3
#     3. (Optionally) upload to S3
#     4. Transcribe with Twilio or AssemblyAI
#     """
#     # 1. Build the MP3 URL and download via basic auth
#     mp3_url = f"{recording_url}.mp3"
#     resp = requests.get(mp3_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
#     if resp.status_code != 200:
#         logger.error("Failed to download recording: %s", resp.text)
#         return {"status": "download_error"}

#     # 2. Save to local disk
#     recordings_dir = Path("recordings")
#     recordings_dir.mkdir(exist_ok=True)
#     file_path = recordings_dir / f"{recording_sid}.mp3"
#     with open(file_path, "wb") as f:
#         f.write(resp.content)
#     logger.info("Saved recording to %s", file_path)
