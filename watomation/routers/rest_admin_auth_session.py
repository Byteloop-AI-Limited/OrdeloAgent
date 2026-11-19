"""rest admin auth session: the (empty) /rest-admin router kept for app wiring; there is no HTTP link issuer.
    . Restaurant-admin dashboard links are minted by ordelo/dashboard_links.py issue("rest_admin", actor), called by
      WhatsApp `/login` (watomation/on_message_wa_handler.py) and Telegram `/manage` (channels/telegram/rest_admin/manage.py).
      The authority check and the auth_sessions insert are one SQL transaction (rest_admin_dashboard_mint,
      ordelo_datamodels/admin_dashboard/auth_sessions.sql). There is deliberately no endpoint that accepts a phone.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/rest-admin", tags=["rest_admin"])
