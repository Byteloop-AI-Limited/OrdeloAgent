"""Stand-ins for Ordelo's delivery hooks, so the card can be driven without the real system.

    POST /demo/order-card?chat_id=...                   create the demo order and send its card
    POST /demo/order-card/{ref}/event?event=picked_up   what a delivery hook would do
Both need the X-Admin-Key header (TGRAM_ADMIN_API_KEY).
"""
import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from .service import refresh_order_card, send_order_card
from .state import EVENTS, apply_event, demo_order, load_order, save_order

router = APIRouter(prefix="/demo/order-card", tags=["order card demo"])

# Hook-driven changes the restaurant should notice get an alerting reply; the card edit itself is silent.
NOTIFY = {
    "rider_assigned": "🛵 Rider assigned: {rider_name}",
    "picked_up": "📦 Order picked up by the rider",
    "delivered": "✅ Order delivered",
    "cancelled": "❌ Order cancelled",
}


def _require_admin(request: Request, key: str):
    expected = request.app.state.settings.admin_api_key
    if not expected or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "bad admin key")


@router.post("")
async def create_demo_card(request: Request, chat_id: int, ref: str = "DEMO-ORDR-21",
                           x_admin_key: str = Header(default="")):
    _require_admin(request, x_admin_key)
    await save_order(demo_order(ref))  # resets the demo order every time
    cards = await send_order_card(request.app.state.bot, ref, [chat_id])
    return {"ref": ref, "cards": [c.__dict__ for c in cards]}


@router.post("/{ref}/event")
async def demo_delivery_event(request: Request, ref: str, event: str, background: BackgroundTasks,
                              rider_name: str = "Demo Rider", rider_phone: str = "+447700900123",
                              x_admin_key: str = Header(default="")):
    """The pattern every real delivery hook follows: update state, respond, refresh the card in the background."""
    _require_admin(request, x_admin_key)
    if event not in EVENTS:
        raise HTTPException(400, f"event must be one of {sorted(EVENTS)}")
    state = await load_order(ref)
    if state is None:
        raise HTTPException(404, "unknown order")
    new = apply_event(state, event, rider_name=rider_name, rider_phone=rider_phone,
                      live_url=f"https://example.com/live-location-map/{ref}")
    if new is None:
        raise HTTPException(409, f"'{event}' not allowed while order is {state.status.value}")
    await save_order(new)
    background.add_task(refresh_order_card, request.app.state.bot, ref, NOTIFY[event].format(rider_name=rider_name))
    return {"ref": ref, "status": new.status.value}
