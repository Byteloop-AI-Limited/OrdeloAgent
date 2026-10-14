"""FastAPI host.   Run:  uvicorn tgram_starter.app:app --port 3200   (from the repo root)

Telegram POSTs every update to /telegram/webhook with header X-Telegram-Bot-Api-Secret-Token.
"""
import secrets
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from . import invites
from .bot_factory import build_bot, build_dispatcher
from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.bot_token or not settings.webhook_secret:
        raise RuntimeError("Set TGRAM_BOT_TOKEN and TGRAM_WEBHOOK_SECRET (see tgram_starter/.env.example)")
    app.state.settings = settings
    app.state.bot = build_bot(settings)
    app.state.dp = build_dispatcher(settings)
    yield
    await app.state.bot.session.close()  # do NOT delete the webhook here


app = FastAPI(title="Telegram starter kit", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    s = request.app.state.settings
    if not secrets.compare_digest(x_telegram_bot_api_secret_token, s.webhook_secret):
        raise HTTPException(403, "bad secret")
    bot, dp = request.app.state.bot, request.app.state.dp
    update = Update.model_validate(await request.json(), context={"bot": bot})
    # Fine for short demo handlers. Production: persist update_id first, ack fast, work in a worker.
    await dp.feed_update(bot, update)
    return {"ok": True}


# ---- Invite management over HTTP (what an Ordelo back-office would call) -------------------------
def _require_admin(request: Request, key: str):
    expected = request.app.state.settings.admin_api_key
    if not expected or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "bad admin key")


@app.post("/invites")
async def create_invite(request: Request, phone_number: str, x_admin_key: str = Header(default="")):
    """curl -X POST 'localhost:3200/invites?phone_number=447700900123' -H 'X-Admin-Key: ...'"""
    _require_admin(request, x_admin_key)
    s = request.app.state.settings
    row = invites.create_invite(phone_number, s.invite_ttl_hours)
    return {**row, "link": invites.invite_link(s.bot_username, row["invite_code"])}


@app.get("/invites")
async def list_invites(request: Request, x_admin_key: str = Header(default="")):
    _require_admin(request, x_admin_key)
    return list(invites.TGRAM_INVITES.values())


@app.post("/send")
async def send_message(request: Request, telegram_user_id: int, text: str, x_admin_key: str = Header(default="")):
    """Proactive message to a LINKED user - only works after they pressed Start."""
    _require_admin(request, x_admin_key)
    row = invites.find_by_telegram_user(telegram_user_id)
    if not row:
        raise HTTPException(404, "user not linked")
    msg = await request.app.state.bot.send_message(row["telegram_chat_id"], text)
    return {"message_id": msg.message_id, "chat_id": row["telegram_chat_id"]}
