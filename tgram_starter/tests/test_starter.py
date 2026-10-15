"""Offline tests: no network, no real token."""
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.update(TGRAM_BOT_TOKEN="123456:TESTTOKEN", TGRAM_WEBHOOK_SECRET="s3cret",
                  TGRAM_ADMIN_API_KEY="adm", TGRAM_BOT_USERNAME="test_bot")

from tgram_starter import invites  # noqa: E402
from tgram_starter.keyboards import Counter, DemoOrder  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    invites.TGRAM_INVITES.clear()
    # aiogram routers attach to ONE Dispatcher; each test boots a fresh app, so detach them.
    from tgram_starter.handlers import basic, interactive, onboarding
    for m in (onboarding, interactive, basic):
        m.router._parent_router = None


def claim(code, uid=1, chat=1):
    return invites.claim_invite(code, user_id=uid, chat_id=chat, username="u", first_name="F", language_code="en")[0]


def test_invite_lifecycle():
    row = invites.create_invite("+44 7700 900123")
    assert row["phone_number"] == "447700900123"
    assert claim(row["invite_code"], uid=7, chat=7) == "ok"
    assert row["telegram_user_id"] == 7 and row["telegram_chat_id"] == 7
    assert claim(row["invite_code"], uid=7) == "ok"      # same person again
    assert claim(row["invite_code"], uid=8) == "used"    # someone else
    assert claim("nope") == "unknown"


def test_expired_and_revoked():
    r = invites.create_invite("1")
    r["expires_at"] -= timedelta(days=9)
    assert claim(r["invite_code"]) == "expired"
    r2 = invites.create_invite("2")
    assert invites.revoke(r2["invite_code"]) and claim(r2["invite_code"]) == "revoked"


def test_phone_verification():
    r = invites.create_invite("447700900123")
    claim(r["invite_code"], uid=5)
    assert not invites.mark_phone_verified(5, "+44 1111")
    assert invites.mark_phone_verified(5, "+447700900123") and r["phone_verified"]


def test_invite_code_fits_start_payload():
    code = invites.create_invite("1")["invite_code"]
    assert len(code) <= 64 and all(c.isalnum() or c in "_-" for c in code)


def test_callback_data_within_64_bytes():
    for cd in (DemoOrder(order_id=10**9, action="a"), Counter(value=-999999, delta=-1)):
        assert 1 <= len(cd.pack().encode()) <= 64
    assert DemoOrder.unpack(DemoOrder(order_id=5, action="d").pack()).order_id == 5


def test_webhook_rejects_bad_secret_and_accepts_good():
    from tgram_starter.app import app
    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json={"update_id": 1}).status_code == 403
        assert c.post("/telegram/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}).status_code == 403
        ok = c.post("/telegram/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
        assert ok.status_code == 200


def test_invite_http_api_requires_key():
    from tgram_starter.app import app
    with TestClient(app) as c:
        assert c.post("/invites?phone_number=1").status_code == 401
        r = c.post("/invites?phone_number=447700900123", headers={"X-Admin-Key": "adm"})
        assert r.status_code == 200 and r.json()["link"].startswith("https://t.me/test_bot?start=")
