"""
Alert hooks router for OrdeloAgent FastAPI service.
    . Defines endpoints for receiving alert and failure notifications
    . Implements webhook pattern for database-triggered alert events
    . Handles both JSON (DB trigger) and form-encoded (Twilio SMS) webhook payloads
    . Logs payloads and supports future extension for business logic
    . Stores display phone number (if present) into TEMP_STORE['phone_num'] during WA_EMBEDDED_SIGNUP
  Functions/Classes:
    . get_payload - Extracts JSON payload from request with empty fallback
    . get_pool - Returns the async connection pool from FastAPI app state
    . failure_notifications - Handles Twilio SMS and DB trigger notifications
"""

# %%
from fastapi import APIRouter, Request, Form, Response
from loguru import logger
from twilio.twiml.voice_response import VoiceResponse

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os
from fastapi.responses import RedirectResponse, HTMLResponse
from utils_common.waba_es.onboarding_utils import (
    TEMP_STORE,
    onboard_business_customer,
    waba_es_app_id,
    waba_es_configuration_id,
    waba_es_graph_api_version,
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
templates = Jinja2Templates(directory=os.path.join(Path(__file__).parent, "templates"))


# %%


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
            "app_id": waba_es_app_id,
            "graph_api_version": waba_es_graph_api_version,
            "configuration_id": waba_es_configuration_id,
        },
    )


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
            onboard_result = await onboard_business_customer(TEMP_STORE)
            return onboard_result

        else:
            logger.warning(f"Unhandled event type: {event_data.get('type')}")
            return {"status": "ignored", "message": "Event type not handled"}

    except Exception as e:
        logger.error(f"Error processing callback: {str(e)}")
        return {"status": "error", "message": f"Failed to process callback: {str(e)}"}


# %% Twilio stuff
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
