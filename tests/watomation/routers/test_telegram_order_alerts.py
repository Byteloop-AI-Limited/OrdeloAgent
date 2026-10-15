"""Tests for watomation.routers.telegram_order_alerts using a minimal FastAPI app."""

from __future__ import annotations

import pytest
from aiogram import Bot
from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.telegram.bots import build_registry
from channels.telegram.rest_admin.order_cards import OrderRef
from config.tgram_setting import TgramBotSettings
from tests.channels.telegram.conftest import RecordingSession
from watomation.routers import telegram_order_alerts

URL = "/telegram/rest-admin/order-alerts"


class SpyCards:
    def __init__(self):
        self.calls = []

    async def remind(self, order, n, of):
        self.calls.append(("remind", order, n, of))

    async def refresh(self, order):
        self.calls.append(("refresh", order))


@pytest.fixture
def env():
    bot = Bot(token="123456:TEST-token", session=RecordingSession())
    settings = TgramBotSettings.for_bot(
        "rest_admin", {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "s"}
    )
    app = FastAPI()
    app.include_router(telegram_order_alerts.router)
    app.state.telegram_bots = build_registry([(settings, bot)])
    spy = SpyCards()
    object.__setattr__(app.state.telegram_bots["rest_admin"], "cards", spy)
    return app, spy


BODY = {
    "event_type": "t_order_alerts",
    "timestamp": 1.0,
    "reminders": [{"order_number": "ELAS-CEKT-22", "order_type": "delivery", "n": 2, "of": 4}],
    "refreshes": [{"order_number": "ELAS-TK-1", "order_type": "takeaway"}],
}


def test_503_without_bot(env):
    app, spy = env
    app.state.telegram_bots = {}
    assert TestClient(app).post(URL, json=BODY).status_code == 503
    assert spy.calls == []


def test_503_when_registry_missing():
    app = FastAPI()
    app.include_router(telegram_order_alerts.router)
    assert TestClient(app).post(URL, json=BODY).status_code == 503


def test_accepts_and_runs_remind_and_refresh(env):
    app, spy = env
    r = TestClient(app).post(URL, json=BODY)
    assert r.status_code == 200 and r.json() == {"status": "accepted", "reminders": 1, "refreshes": 1}
    assert spy.calls == [
        ("remind", OrderRef("ELAS-CEKT-22", "delivery"), 2, 4),
        ("refresh", OrderRef("ELAS-TK-1", "takeaway")),
    ]


def test_empty_lists_are_fine(env):
    app, spy = env
    assert TestClient(app).post(URL, json={"event_type": "t_order_alerts"}).json()["reminders"] == 0
    assert spy.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        {"reminders": [{"order_number": "X", "order_type": "pizza", "n": 1, "of": 1}]},
        {"reminders": [{"order_number": "", "order_type": "delivery", "n": 1, "of": 1}]},
        {"reminders": [{"order_number": "X", "order_type": "delivery", "n": 0, "of": 1}]},
        {"refreshes": [{"order_number": "X"}]},
    ],
)
def test_invalid_payload_is_422_and_nothing_runs(env, bad):
    app, spy = env
    assert TestClient(app).post(URL, json=bad).status_code == 422
    assert spy.calls == []
