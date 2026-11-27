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
from utils_common.notify import customer_notifier
from utils_common.web_ordering import lifecycle, monitoring
from watomation.routers import sweep_hooks

URL = "/rider-hooks/invite-alerts"

# phase 2 (option B): (path, module, attribute, log name)
CUSTOMER_ROUTES = [
    ("/customer-hooks/outbox-sweep", customer_notifier, "sweep_pending", "customer_outbox_sweep"),
    ("/web-hooks/lifecycle-sweep", lifecycle, "sweep", "web_lifecycle_sweep"),
    ("/web-hooks/price-audit", monitoring, "sweep", "web_price_audit"),
]
ALL_PATHS = [URL] + [r[0] for r in CUSTOMER_ROUTES]


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


def test_the_routes_are_hidden_from_the_schema(client):
    paths = client.get("/openapi.json").json().get("paths", {})
    assert not [p for p in ALL_PATHS if p in paths]


# ---- phase 2: customer outbox, web lifecycle, price audit -------------------------------------------------------------

def _recorder(calls, name, result=None, error=None):
    async def sweep():
        calls.append(name)
        if error is not None:
            raise error
        return result

    return sweep


@pytest.mark.parametrize("path, module, attr, name", CUSTOMER_ROUTES, ids=[r[3] for r in CUSTOMER_ROUTES])
@pytest.mark.parametrize("body", [None, {"event_type": "anything"}])
def test_each_customer_route_schedules_only_its_own_sweep(client, monkeypatch, logs, path, module, attr, name, body):
    calls = []
    for _, m, a, n in CUSTOMER_ROUTES:
        monkeypatch.setattr(m, a, _recorder(calls, n, result=2))
    monkeypatch.setattr(invite_alerts, "sweep_pending", _recorder(calls, "rider_invite_alerts"))
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code == 200 and r.json() == {"status": "accepted"}
    assert calls == [name]
    assert any(f"sweep[{name}]: done result=2" in line for line in logs)


@pytest.mark.parametrize("failing", [r[3] for r in CUSTOMER_ROUTES])
def test_one_failing_customer_sweep_does_not_affect_the_others(client, monkeypatch, logs, failing):
    calls = []
    for _, m, a, n in CUSTOMER_ROUTES:
        err = RuntimeError("detail that must not be logged") if n == failing else None
        monkeypatch.setattr(m, a, _recorder(calls, n, result=0, error=err))
    for path, *_ in CUSTOMER_ROUTES:
        r = client.post(path)
        assert r.status_code == 200 and r.json() == {"status": "accepted"}
    assert calls == [r[3] for r in CUSTOMER_ROUTES]   # every sweep ran, the failing one included
    text = "\n".join(logs)
    for *_, n in CUSTOMER_ROUTES:
        if n == failing:
            assert f"sweep[{n}]: failed error_type=RuntimeError" in text
        else:
            assert f"sweep[{n}]: done result=0" in text
    assert "must not be logged" not in text
