"""Offline tests for the Demo Kitchen mini app: initData auth, server-side pricing, owner-only orders."""
import hashlib
import hmac
import json
import os
import time
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

TOKEN = "123456:TESTTOKEN"
os.environ.update(TGRAM_BOT_TOKEN=TOKEN, TGRAM_WEBHOOK_SECRET="s3cret", TGRAM_ADMIN_API_KEY="adm",
                  TGRAM_BOT_USERNAME="test_bot", TGRAM_WEBHOOK_BASE_URL="https://bot.example.com")

from tgram_starter import invites  # noqa: E402
from tgram_starter.miniapp import store  # noqa: E402
from tgram_starter.miniapp.auth import InitDataError, validate_init_data  # noqa: E402


def make_init_data(user_id=7, token=TOKEN, auth_date=None, first_name="Lo", tamper=None) -> str:
    """Independent re-implementation of what Telegram does when it signs initData."""
    fields = {"auth_date": str(int(auth_date if auth_date is not None else time.time())), "query_id": "AAH",
              "user": json.dumps({"id": user_id, "first_name": first_name, "username": f"u{user_id}"}, separators=(",", ":"))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, dcs.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields.update(tamper)
    return urlencode(fields)


@pytest.fixture(autouse=True)
def clean():
    invites.TGRAM_INVITES.clear()
    store.ORDERS.clear()
    store._IDEMPOTENT.clear()


@pytest.fixture
def client():
    from tgram_starter.app import app
    with TestClient(app) as c:
        app.state.bot.send_message = AsyncMock()
        c.bot_send = app.state.bot.send_message
        yield c


def hdr(**kw):
    return {"X-Telegram-Init-Data": make_init_data(**kw)}


# ---- auth ----------------------------------------------------------------------------------------------------
def test_valid_init_data():
    r = validate_init_data(make_init_data(user_id=42), TOKEN)
    assert r["user_id"] == 42 and r["user"]["first_name"] == "Lo"


def test_tampered_user_is_rejected():
    forged = make_init_data(user_id=1, tamper={"user": json.dumps({"id": 999, "first_name": "Admin"})})
    with pytest.raises(InitDataError, match="bad signature"):
        validate_init_data(forged, TOKEN)


def test_wrong_bot_token_is_rejected():
    with pytest.raises(InitDataError, match="bad signature"):
        validate_init_data(make_init_data(token="999:OTHER"), TOKEN)


def test_expired_is_rejected_even_with_valid_signature():
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(make_init_data(auth_date=time.time() - 7200), TOKEN, max_age=3600)


@pytest.mark.parametrize("bad", ["", "auth_date=1&user=%7B%7D", "a=1&a=2&hash=x"])
def test_malformed_is_rejected(bad):
    with pytest.raises(InitDataError):
        validate_init_data(bad, TOKEN)


# ---- store ---------------------------------------------------------------------------------------------------
def test_server_computes_total_and_merges_lines():
    o, created = store.create_order(1, [store.Line("marg", 2), store.Line("cola", 1), store.Line("marg", 1)], "key-12345678")
    assert created and o["total"] == 3 * 850 + 200
    assert {i["id"]: i["qty"] for i in o["items"]} == {"marg": 3, "cola": 1}


@pytest.mark.parametrize("lines", [[], [store.Line("nope", 1)], [store.Line("cola", 0)], [store.Line("cola", 11)],
                                    [store.Line("cola", 6), store.Line("cola", 6)]])
def test_invalid_orders_rejected(lines):
    with pytest.raises(store.OrderError):
        store.create_order(1, lines, "key-12345678")


def test_idempotent_per_user_and_key():
    a, c1 = store.create_order(1, [store.Line("cola", 1)], "same-key-1")
    b, c2 = store.create_order(1, [store.Line("cola", 1)], "same-key-1")
    other, c3 = store.create_order(2, [store.Line("cola", 1)], "same-key-1")
    assert (c1, c2, c3) == (True, False, True) and a["id"] == b["id"] != other["id"]


# ---- HTTP API ------------------------------------------------------------------------------------------------
def test_page_is_served_and_api_requires_auth(client):
    r = client.get("/miniapp/")
    assert r.status_code == 200 and "telegram-web-app.js" in r.text
    assert client.get("/miniapp/api/menu").status_code == 401
    assert client.get("/miniapp/api/menu", headers={"X-Telegram-Init-Data": "hash=x&auth_date=1"}).status_code == 401
    assert client.get("/miniapp/api/menu", headers=hdr()).status_code == 200


def test_session_reports_verified_identity_and_ordelo_link(client):
    row = invites.create_invite("+44 7700 900123")
    invites.claim_invite(row["invite_code"], user_id=7, chat_id=7, username="u7", first_name="Lo", language_code="en")
    body = client.get("/miniapp/api/session", headers=hdr(user_id=7)).json()
    assert body["user"]["id"] == 7 and body["ordelo_link"]["phone"] == "+447700900123"
    assert client.get("/miniapp/api/session", headers=hdr(user_id=8)).json()["ordelo_link"] is None


def test_place_order_ignores_client_prices_and_notifies_once(client):
    payload = {"items": [{"id": "burg", "qty": 2, "price": 1}], "idempotency_key": "abcdefgh-1", "total": 1}
    r1 = client.post("/miniapp/api/orders", json=payload, headers=hdr(user_id=7))
    assert r1.status_code == 200 and r1.json()["order"]["total"] == 2100 and r1.json()["chat_notified"] is True
    r2 = client.post("/miniapp/api/orders", json=payload, headers=hdr(user_id=7))
    assert r2.json()["created"] is False and r2.json()["order"]["id"] == r1.json()["order"]["id"]
    assert client.bot_send.await_count == 1                       # retry did not send a second message
    chat_id, text = client.bot_send.await_args.args[:2]
    assert chat_id == 7 and "£21.00" in text
    kb = client.bot_send.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].web_app.url == f"https://bot.example.com/miniapp/?order={r1.json()['order']['id']}"


def test_bad_orders_are_422(client):
    for items in ([], [{"id": "nope", "qty": 1}], [{"id": "cola", "qty": 11}]):
        r = client.post("/miniapp/api/orders", json={"items": items, "idempotency_key": "abcdefgh-2"}, headers=hdr())
        assert r.status_code == 422


def test_orders_are_owner_only(client):
    oid = client.post("/miniapp/api/orders", json={"items": [{"id": "cola", "qty": 1}], "idempotency_key": "abcdefgh-3"},
                      headers=hdr(user_id=7)).json()["order"]["id"]
    assert client.get(f"/miniapp/api/orders/{oid}", headers=hdr(user_id=7)).status_code == 200
    assert client.get(f"/miniapp/api/orders/{oid}", headers=hdr(user_id=8)).status_code == 404   # same as missing
    assert client.get("/miniapp/api/orders", headers=hdr(user_id=8)).json() == []
    assert len(client.get("/miniapp/api/orders", headers=hdr(user_id=7)).json()) == 1


def test_order_still_succeeds_if_chat_message_fails(client):
    from aiogram.exceptions import TelegramForbiddenError
    client.bot_send.side_effect = TelegramForbiddenError(method=None, message="Forbidden: bot was blocked")
    r = client.post("/miniapp/api/orders", json={"items": [{"id": "cola", "qty": 1}], "idempotency_key": "abcdefgh-4"}, headers=hdr())
    assert r.status_code == 200 and r.json()["chat_notified"] is False


# ---- bot side ------------------------------------------------------------------------------------------------
def test_app_command_sends_web_app_button():
    import asyncio

    from aiogram import Bot
    from aiogram.methods import SendMessage
    from aiogram.types import Chat, Message, Update

    from tgram_starter.bot_factory import build_dispatcher
    from tgram_starter.config import get_settings

    sent = []

    class FakeBot(Bot):
        async def __call__(self, method, request_timeout=None):
            sent.append(method)
            return Message(message_id=1, date=0, chat=Chat(id=5, type="private"))

    bot = FakeBot(TOKEN)
    dp = build_dispatcher(get_settings())
    upd = Update.model_validate({"update_id": 1, "message": {"message_id": 1, "date": 0, "chat": {"id": 5, "type": "private"},
        "from": {"id": 5, "is_bot": False, "first_name": "Lo"}, "text": "/app",
        "entities": [{"type": "bot_command", "offset": 0, "length": 4}]}}, context={"bot": bot})
    async def run():
        await dp.feed_update(bot, upd)
        await bot.session.close()

    asyncio.run(run())
    m = [x for x in sent if isinstance(x, SendMessage)][0]
    assert m.reply_markup.inline_keyboard[0][0].web_app.url == "https://bot.example.com/miniapp/"
