from unittest.mock import AsyncMock

import pytest

from ordelo import offer_reminders as subject
from ordelo.rider_messaging import use_messenger
from ordelo.rider_messaging.fake import RecordingRiderMessenger

ROW = dict(dispatch_id=41, order_number='STRK-TEST-101500', rider_id='447448440754', rider_payout=5,
           vehicle_type='bicycle', distance=1.5, pickup_time='2026-10-26T19:30:00+00:00', rest_name='Strk Kitchen',
           rest_address='40b The Walnuts', customer_name='Test Customer', customer_address='1 Test Street')


def snapshot(state='open', reason=None):
    return subject.Snapshot(state, reason, 41, ROW['order_number'], ROW['rider_id'], 123, 'tg:123:1', ROW)


@pytest.fixture
def store():
    fake = AsyncMock()
    fake.snapshot.return_value = snapshot()
    fake.reminder_sent.return_value = subject.Swap('swapped', 'tg:123:1', 'open', None)
    fake.order_open.return_value = True
    return fake


async def test_reminder_swaps_and_deletes(monkeypatch, store):
    monkeypatch.setattr(subject, 'rider_dispatch_allowed', AsyncMock(return_value=True))
    messenger = RecordingRiderMessenger('telegram')
    with use_messenger(messenger):
        assert await subject.remind(41, 3, 7, store=store) == 'sent'
    assert messenger.methods == ['offer_job', 'delete']
    assert messenger.calls[0][1]['offer'].notice == '⏰ Still open · reminder 3 of 7'
    store.reminder_sent.assert_awaited_once_with(41, 'fake:1', 'tg:123:1')


@pytest.mark.parametrize('result,state,reason,expected,methods', [
    ('stale', 'open', None, 'stale', ['offer_job', 'delete']),
    ('swapped', 'closed', 'taken', 'closed:taken', ['offer_job', 'delete', 'offer_closed']),
    ('gone', 'closed', 'gone', 'closed:gone', ['offer_job', 'delete', 'offer_closed']),
])
async def test_swap_outcomes(monkeypatch, store, result, state, reason, expected, methods):
    monkeypatch.setattr(subject, 'rider_dispatch_allowed', AsyncMock(return_value=True))
    store.reminder_sent.return_value = subject.Swap(result, 'tg:123:1', state, reason)
    messenger = RecordingRiderMessenger('telegram')
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == expected
    assert messenger.methods == methods


async def test_rechecks_and_escalates(monkeypatch, store):
    monkeypatch.setattr(subject, 'rider_dispatch_allowed', AsyncMock(return_value=True))
    store.snapshot.side_effect = [snapshot(), snapshot('closed', 'accepted')]
    messenger = RecordingRiderMessenger('telegram')
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == 'closed:accepted'
    alert = AsyncMock()
    assert await subject.escalate(ROW['order_number'], 120, 2, 1, store=store, alert=alert)
    assert 'after 2 min (2 offered on Telegram, 1 declined)' in alert.await_args.args[0]
    store.order_open.return_value = False
    assert not await subject.escalate(ROW['order_number'], 120, 2, 1, store=store, alert=alert)
    assert alert.await_count == 1


async def test_skips_closed_and_fallback(monkeypatch, store):
    store.snapshot.return_value = snapshot('quiet', 'paused')
    assert await subject.remind(41, 1, 7, store=store) == 'skipped:paused'
    store.snapshot.return_value = snapshot()
    monkeypatch.setattr(subject, 'rider_dispatch_allowed', AsyncMock(return_value=True))
    messenger = RecordingRiderMessenger('whatsapp')
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == 'skipped:no_rider_bot'
    assert not messenger.calls


async def test_disallowed_send_failure_and_delete_failure(monkeypatch, store):
    allowed = AsyncMock(return_value=False)
    monkeypatch.setattr(subject, 'rider_dispatch_allowed', allowed)
    messenger = RecordingRiderMessenger('telegram')
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == 'skipped:not_allowed'
    assert not messenger.calls
    allowed.return_value = True
    messenger.offer_job = AsyncMock(side_effect=RuntimeError('send failed'))
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == 'failed'
    store.reminder_sent.assert_not_awaited()
    messenger.offer_job = AsyncMock(return_value='tg:123:2')
    messenger.delete = AsyncMock(side_effect=RuntimeError('delete failed'))
    store.reminder_sent.return_value = subject.Swap('swapped', 'tg:123:1', 'closed', 'taken')
    with use_messenger(messenger):
        assert await subject.remind(41, 1, 7, store=store) == 'closed:taken'
    assert messenger.calls[-1][0] == 'offer_closed'


async def test_redispatch_escalation_text(store):
    alert = AsyncMock()
    assert await subject.escalate(ROW['order_number'], 120, 2, 1, True, store=store, alert=alert)
    assert 'no rider has accepted 2 min after re-dispatch (2 offered on Telegram, 1 declined)' in alert.await_args.args[0]
