"""watomation/routers/sweep_hooks.py: thin routes woken by pg_cron (ADR 0019), tested with a minimal FastAPI app.

Each route answers 200 {"status": "accepted"} at once, ignores the body and runs one sweep in BackgroundTasks; a failing
sweep is logged by class and never raised.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from channels.telegram.rider import invite_alerts
from watomation.routers import sweep_hooks

URL = "/rider-hooks/invite-alerts"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(sweep_hooks.router)
    return TestClient(app)


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO")
    yield lines
    logger.remove(sink)


@pytest.mark.parametrize("body", [None, {"event_type": "rider_invite_alerts", "due": 1}, {"anything": ["ignored"]}])
def test_rider_invite_alerts_schedules_the_sweep_once(client, monkeypatch, logs, body):
    calls = []

    async def sweep_pending():
        calls.append(1)
        return 3

    monkeypatch.setattr(invite_alerts, "sweep_pending", sweep_pending)
    r = client.post(URL, json=body) if body is not None else client.post(URL)
    assert r.status_code == 200 and r.json() == {"status": "accepted"}
    assert calls == [1]
    assert any("sweep[rider_invite_alerts]: done result=3" in line for line in logs)


def test_a_failing_sweep_is_logged_by_class_not_raised(client, monkeypatch, logs):
    async def sweep_pending():
        raise RuntimeError("secret-looking detail ri_should_not_be_logged")

    monkeypatch.setattr(invite_alerts, "sweep_pending", sweep_pending)
    r = client.post(URL)
    assert r.status_code == 200 and r.json() == {"status": "accepted"}
    failed = [line for line in logs if "sweep[rider_invite_alerts]: failed" in line]
    assert failed and "error_type=RuntimeError" in failed[0]
    assert "ri_should_not_be_logged" not in "\n".join(logs)


def test_the_route_is_hidden_from_the_schema(client):
    assert URL not in client.get("/openapi.json").json().get("paths", {})
