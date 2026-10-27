import pytest

from ordelo import job_exit
from ordelo.rider_messaging.fake import RecordingRiderMessenger


@pytest.mark.parametrize("status, expected", [
    ("assigned", job_exit.Verdict.ASK_CONFIRM), ("pickedup", job_exit.Verdict.REFUSE),
    ("declined", job_exit.Verdict.ALLOW_CLOSE), ("completed", job_exit.Verdict.ALLOW_CLOSE),
    ("missed", job_exit.Verdict.ALLOW_CLOSE), ("unassigned", job_exit.Verdict.ALLOW_CLOSE),
    (None, job_exit.Verdict.ALLOW_CLOSE), ("unknown-status", job_exit.Verdict.UNKNOWN),
])
def test_decide(status, expected):
    assert job_exit.decide(status) is expected


async def test_status_read_failure_is_closed():
    class Broken:
        async def status(self, dispatch_id):
            raise RuntimeError("offline")
    assert await job_exit.verdict_for(None, Broken()) is job_exit.Verdict.ALLOW_CLOSE
    assert await job_exit.verdict_for(1, Broken()) is job_exit.Verdict.UNKNOWN


async def test_refusal_alerts_every_time_and_masks_phone():
    messenger = RecordingRiderMessenger()
    alerts = []
    async def alert(text):
        alerts.append(text)
    for _ in range(3):
        await job_exit.refuse_after_pickup(messenger=messenger, order_number="ORDER-1", dispatch_id=17,
            rider_name="Sam", rider_phone="447700900123", rider_words="I cannot continue", alert=alert)
    assert messenger.texts == [job_exit.REFUSE_TEXT] * 3
    assert len(alerts) == 3
    assert 'ORDER-1' in alerts[0] and '…0123' in alerts[0] and '447700900123' not in alerts[0]
    assert '"I cannot continue"' in alerts[0]
