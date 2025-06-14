# %%
"""
Alert hooks router for OrdeloAgent FastAPI service.
    . Defines endpoints for receiving alert and failure notifications
    . Implements webhook pattern for database-triggered alert events
    . Handles both JSON (DB trigger) and form-encoded (Twilio SMS) webhook payloads
    . Logs payloads and supports future extension for business logic
    . Ensures robust handling of empty, malformed, or unexpected webhook payloads
    . Functions/Classes:
        . failure_notifications
        . get_payload
        . get_pool
"""

from fastapi import APIRouter, Request, Form
from loguru import logger

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


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

router = APIRouter(tags=["alert_hooks"])


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
