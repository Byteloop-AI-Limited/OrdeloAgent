from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from watomation.routers import rider_offer_alerts


def test_hook_checks_bot_and_validates():
    app = FastAPI()
    app.include_router(rider_offer_alerts.router)
    client = TestClient(app)
    body = {'reminders': [{'dispatch_id': 1, 'n': 1, 'of': 7}], 'escalations': [{'order_number': 'STRK-1', 'after_secs': 120}]}
    with patch('config.rider_bot', None):
        assert client.post('/rider-hooks/offer-alerts', json=body).status_code == 503
    body['reminders'][0]['dispatch_id'] = 0
    with patch('config.rider_bot', object()):
        assert client.post('/rider-hooks/offer-alerts', json=body).status_code == 422


async def test_hook_schedules_each_task(monkeypatch):
    from fastapi import BackgroundTasks
    import config
    monkeypatch.setattr(config, 'rider_bot', object())
    tasks = BackgroundTasks()
    payload = rider_offer_alerts.OfferAlertsPayload.model_validate({'reminders': [{'dispatch_id': 1, 'n': 1, 'of': 7, 'extra': 1}], 'escalations': [{'order_number': 'STRK-1', 'after_secs': 120}]})
    result = await rider_offer_alerts.offer_alerts(payload, tasks)
    assert result == {'status': 'accepted', 'reminders': 1, 'escalations': 1}
    assert [t.func for t in tasks.tasks] == [rider_offer_alerts.offer_reminders.remind, rider_offer_alerts.offer_reminders.escalate]


async def test_escalation_redispatch_forwarded_and_defaults(monkeypatch):
    import config
    from fastapi import BackgroundTasks
    monkeypatch.setattr(config, 'rider_bot', object())
    tasks = BackgroundTasks()
    payload = rider_offer_alerts.OfferAlertsPayload.model_validate({'escalations': [
        {'order_number': 'STRK-1', 'after_secs': 120, 'redispatched': True},
        {'order_number': 'STRK-2', 'after_secs': 120},
    ]})
    await rider_offer_alerts.offer_alerts(payload, tasks)
    assert [task.args[-1] for task in tasks.tasks] == [True, False]
