"""watomation/routers/pause_hooks.py (POST /pause-hooks/sweep, called by job_pause_sweep()) with a minimal FastAPI app.

The route answers 200 at once and hands each item to ordelo.pause_notices by audience; a bad body is a 422 (the SQL job then
marks nothing and retries next minute). The notices themselves: tests/ordelo/test_pause_notices.py.
"""

from __future__ import annotations

import pytest
from aiogram import Bot
from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.telegram.bots import build_registry
from config.tgram_setting import TgramBotSettings
from tests.channels.telegram.conftest import RecordingSession
from watomation.routers import pause_hooks

URL = "/pause-hooks/sweep"
ITEM = {"pause_id": 1, "audience": "rider", "principal": "447700900541", "scope": None, "ends_at": "2026-10-23T17:30:00+00:00"}
ADMIN = {"pause_id": 2, "audience": "rest_admin", "principal": "447700900811", "scope": "ELAS", "ends_at": "2026-10-23T18:00:00+00:00"}


@pytest.fixture
def env(monkeypatch):
    calls = []

    async def tell_rider(rider_id, kind, ends_at):
        calls.append(("rider", rider_id, kind, ends_at.isoformat()))

    async def tell_admin(bot, bot_key, phone, rest_ref, kind, ends_at):
        calls.append(("admin", bot is not None, bot_key, phone, rest_ref, kind))

    monkeypatch.setattr(pause_hooks.pause_notices, "tell_rider", tell_rider)
    monkeypatch.setattr(pause_hooks.pause_notices, "tell_admin", tell_admin)
    app = FastAPI()
    app.include_router(pause_hooks.router)
    settings = TgramBotSettings.for_bot("rest_admin", {"tgram_rest_admin_bot_token": "123456:TEST-token",
                                                       "tgram_rest_admin_webhook_secret": "s"})
    app.state.telegram_bots = build_registry([(settings, Bot(token="123456:TEST-token", session=RecordingSession()))])
    return app, calls


def test_items_are_routed_by_audience(env):
    app, calls = env
    body = {"event_type": "pause_sweep", "ending_soon": [ITEM], "ended": [ADMIN, {**ADMIN, "scope": None}]}
    r = TestClient(app).post(URL, json=body)
    assert r.status_code == 200 and r.json() == {"status": "accepted", "ending_soon": 1, "ended": 2}
    assert calls == [("rider", "447700900541", "ending_soon", "2026-10-23T17:30:00+00:00"),
                     ("admin", True, "rest_admin", "447700900811", "ELAS", "ended")]  # an admin item without a scope is skipped


def test_without_the_restaurant_bot_admin_items_still_go_to_the_notifier(env):
    app, calls = env
    app.state.telegram_bots = {}
    assert TestClient(app).post(URL, json={"ended": [ADMIN]}).status_code == 200
    assert calls == [("admin", False, "rest_admin", "447700900811", "ELAS", "ended")]


@pytest.mark.parametrize("bad", [{"ended": [{**ITEM, "audience": "customer"}]}, {"ended": [{**ITEM, "principal": "12"}]},
                                 {"ending_soon": [{"pause_id": 1}]}])
def test_bad_bodies_are_rejected(env, bad):
    app, calls = env
    assert TestClient(app).post(URL, json=bad).status_code == 422 and calls == []


def test_the_app_mounts_the_route():
    """Importing the app needs the WhatsApp flow keys; the wiring line is checked in the source instead."""
    from pathlib import Path

    src = (Path(pause_hooks.__file__).parents[1] / "fapp_ordelo_agent.py").read_text()
    assert "app.include_router(pause_hooks.router)" in src and "import pause_hooks" in src.replace("routers import pause_hooks", "import pause_hooks")
