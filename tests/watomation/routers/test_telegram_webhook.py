"""Tests for watomation.routers.telegram_webhook using a minimal FastAPI app (no WhatsApp stack)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.telegram.bots import build_registry
from config.tgram_setting import TgramBotSettings
from tests.channels.telegram.conftest import FakeInboxDb, RecordingSession, message_update
from watomation.routers import telegram_webhook

SECRET = "wh-secret"
URL = "/telegram/rest-admin/webhook"
HDR = "X-Telegram-Bot-Api-Secret-Token"


@pytest.fixture
def inbox_db(monkeypatch):
    db = FakeInboxDb()
    monkeypatch.setattr("channels.telegram.inbox.client_ordelo_service", db)
    return db


@pytest.fixture
def env(inbox_db):
    from aiogram import Bot

    session = RecordingSession()
    bot = Bot(token="123456:TEST-token", session=session)
    settings = TgramBotSettings.for_bot(
        "rest_admin",
        {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": SECRET},
    )
    app = FastAPI()
    app.include_router(telegram_webhook.router)
    app.state.telegram_bots = build_registry([(settings, bot)])
    return app, session


def test_unknown_slug_is_404(env):
    app, _ = env
    assert TestClient(app).post("/telegram/rider/webhook", json={}, headers={HDR: SECRET}).status_code == 404


def test_unregistered_bot_is_404(env):
    app, _ = env
    app.state.telegram_bots = {}
    assert TestClient(app).post(URL, json={}, headers={HDR: SECRET}).status_code == 404


def test_missing_wrong_or_non_ascii_secret_is_403(env):
    app, session = env
    c = TestClient(app)
    assert c.post(URL, json=message_update("/start")).status_code == 403
    assert c.post(URL, json=message_update("/start"), headers={HDR: "nope"}).status_code == 403
    assert c.post(URL, json=message_update("/start"), headers={HDR: "sécret".encode("latin-1")}).status_code == 403
    assert session.calls == []


def test_valid_update_is_handled(env):
    app, session = env
    r = TestClient(app).post(URL, json=message_update("/help"), headers={HDR: SECRET})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "/whoami" in session.sent_texts[0]


def test_malformed_update_still_200(env):
    app, session = env
    r = TestClient(app).post(URL, json={"update_id": 5, "message": "garbage"}, headers={HDR: SECRET})
    assert r.status_code == 200 and session.calls == []


def test_handler_exception_still_200(env):
    app, _ = env
    tg = app.state.telegram_bots["rest_admin"]

    async def boom(*a, **k):
        raise RuntimeError("boom")

    object.__setattr__(tg.dp, "feed_update", boom)
    r = TestClient(app).post(URL, json=message_update("/start"), headers={HDR: SECRET})
    assert r.status_code == 200


def test_handler_timeout_still_200(env, monkeypatch):
    app, _ = env
    tg = app.state.telegram_bots["rest_admin"]

    async def slow(*a, **k):
        await asyncio.sleep(5)

    object.__setattr__(tg.dp, "feed_update", slow)
    monkeypatch.setattr(telegram_webhook, "HANDLER_TIMEOUT_SECS", 0.01)
    r = TestClient(app).post(URL, json=message_update("/start"), headers={HDR: SECRET})
    assert r.status_code == 200


def test_retried_update_is_handled_once_and_recorded(env, inbox_db):
    """Telegram redelivers an update; the second POST is answered 200 but not handled again."""
    app, session = env
    c = TestClient(app)
    for _ in range(2):
        r = c.post(URL, json=message_update("/help", update_id=77), headers={HDR: SECRET})
        assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(session.sent_texts) == 1
    assert inbox_db.status_of(77) == "done"
    assert list(inbox_db.rows) == [("rest_admin", 77)]


def test_failed_handler_is_recorded_failed_and_retry_is_not_rerun(env, inbox_db):
    app, session = env
    calls = []

    # make the Bot API send blow up, so the /help handler raises
    async def failing_request(bot, method, timeout=None):
        calls.append(1)
        raise RuntimeError("telegram down")

    session.make_request = failing_request
    c = TestClient(app)
    for _ in range(2):
        assert c.post(URL, json=message_update("/help", update_id=78), headers={HDR: SECRET}).status_code == 200
    assert len(calls) == 1
    assert inbox_db.status_of(78) == "failed"
