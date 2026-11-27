"""channels/telegram/rider/invite_alerts.py sweep_pending() against FakeRiderInviteDb, a copy of the take/finish contract
of t_rider_invite_alert_take / t_rider_invite_alert_finish (ordelo_datamodels/telegram/t_rider_invites.sql).

The sweep is woken by pg_cron through POST /rider-hooks/invite-alerts (ADR 0019). Change the fake whenever the RPCs change.
Phones and Telegram ids are fake; no invite code exists here and none may reach a log.
"""

from __future__ import annotations

import pytest
from loguru import logger

import config
import config.params
from channels.telegram import rider_invites
from channels.telegram.rider import invite_alerts

OPS = ["440000000001", "440000000002"]


class FakeRiderInviteDb:
    """In-memory t_invites alert state. take leases the first due alert (no code in the reply); finish fences on the lease.

    A retry/ambiguous finish makes the alert due again only after tick() (the real RPC reschedules one minute later).
    """

    def __init__(self, n: int = 1):
        self.alerts = {
            1000 + i: {"due": True, "lease": None, "result": "pending", "accepted": [], "ambiguous": 0}
            for i in range(n)
        }
        self.calls: list[tuple[str, dict]] = []

    def tick(self):
        for a in self.alerts.values():
            if a["result"] in ("retry", "ambiguous"):
                a["due"] = True

    async def rpc(self, name: str, args: dict) -> dict:
        self.calls.append((name, args))
        if name == "t_rider_invite_alert_take":
            for update_id, a in self.alerts.items():
                if a["due"]:
                    a["ambiguous"] += a["result"] == "sending"
                    a.update(due=False, lease=args["p_lease"], result="sending")
                    return {"result": "ok", "update_id": update_id, "phone_tail": "0123", "tuid": 990000000001,
                            "username": "rider_test", "previous_tuid": None, "previous_username": None,
                            "accepted": list(a["accepted"])}
            return {"result": "empty"}
        if name == "t_rider_invite_alert_finish":
            if args["p_result"] not in ("accepted", "retry", "ambiguous"):
                return {"result": "invalid"}
            a = self.alerts.get(args["p_update_id"])
            if a is None or a["lease"] != args["p_lease"]:
                return {"result": "stale"}
            a["accepted"] = sorted(set(a["accepted"]) | set(args["p_accepted"] or []))
            a["ambiguous"] += args["p_result"] == "ambiguous"
            a.update(lease=None, result=args["p_result"])
            return {"result": "ok"}
        raise AssertionError(f"unexpected rpc {name}")


class FakeWa:
    def __init__(self, fail_to=()):
        self.fail_to = set(fail_to)
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, to, text):
        if to in self.fail_to:
            raise RuntimeError("send failed")
        self.sent.append((to, text))


@pytest.fixture
def env(monkeypatch):
    def make(n=1, ops=OPS, fail_to=(), ops_error=False):
        db = FakeRiderInviteDb(n)
        wa = FakeWa(fail_to)

        def get_overwatch_list():
            if ops_error:
                raise RuntimeError("config read failed")
            return list(ops)

        monkeypatch.setattr(rider_invites, "_rpc", db.rpc)
        monkeypatch.setattr(config, "_async_wa_client", wa, raising=False)
        monkeypatch.setattr(config.params, "get_overwatch_list", get_overwatch_list)
        return db, wa

    return make


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO")
    yield lines
    logger.remove(sink)


async def test_all_recipients_accepted(env):
    db, wa = env()
    assert await invite_alerts.sweep_pending() == 1
    assert sorted(to for to, _ in wa.sent) == OPS
    assert db.alerts[1000]["result"] == "accepted" and db.alerts[1000]["accepted"] == OPS
    assert "…0123" in wa.sent[0][1] and "@rider_test" in wa.sent[0][1]
    assert await invite_alerts.sweep_pending() == 0   # nothing due: take answers empty


async def test_one_failed_recipient_is_ambiguous_and_the_next_sweep_sends_only_to_the_rest(env):
    db, wa = env(fail_to={OPS[1]})
    assert await invite_alerts.sweep_pending() == 1
    a = db.alerts[1000]
    assert (a["result"], a["accepted"], a["ambiguous"]) == ("ambiguous", [OPS[0]], 1)
    wa.fail_to.clear()
    wa.sent.clear()
    db.tick()
    assert await invite_alerts.sweep_pending() == 1
    assert [to for to, _ in wa.sent] == [OPS[1]]
    assert db.alerts[1000]["result"] == "accepted" and db.alerts[1000]["accepted"] == OPS


@pytest.mark.parametrize("kwargs", [{"ops": []}, {"ops_error": True}])
async def test_empty_or_failing_overwatch_list_is_a_retry(env, kwargs):
    db, wa = env(**kwargs)
    assert await invite_alerts.sweep_pending() == 1
    assert wa.sent == []
    assert db.alerts[1000]["result"] == "retry" and db.alerts[1000]["accepted"] == []


async def test_at_most_20_alerts_per_sweep(env):
    db, _ = env(n=25)
    assert await invite_alerts.sweep_pending() == 20
    assert sum(a["result"] == "accepted" for a in db.alerts.values()) == 20
    assert await invite_alerts.sweep_pending() == 5


async def test_claim_log_line_names_the_update_and_never_a_code(env, logs):
    db, _ = env()
    await invite_alerts.sweep_pending()
    assert any("invite alert update 1000 claimed by sweep" in line for line in logs)
    joined = "\n".join(logs)
    assert "ri_" not in joined and "start=" not in joined


async def test_a_lease_lost_before_finish_is_logged_as_stale_and_does_not_raise(env, logs):
    """Another sweep re-took the alert (lease expired) while this one was sending, so finish answers stale."""
    db, wa = env()
    send = wa.send_message

    async def send_then_lose_the_lease(to, text):
        await send(to, text)
        db.alerts[1000]["lease"] = "taken-by-another-sweep"

    wa.send_message = send_then_lose_the_lease
    assert await invite_alerts.sweep_pending() == 1   # no exception, the alert still counts as processed
    assert sorted(to for to, _ in wa.sent) == OPS
    finishes = [args for name, args in db.calls if name == "t_rider_invite_alert_finish"]
    assert len(finishes) == 1
    a = db.alerts[1000]
    assert (a["result"], a["accepted"]) == ("sending", [])   # the fenced finish recorded nothing
    assert any("invite alert update 1000 transport=accepted recorded=stale" in line for line in logs)

def test_there_is_no_in_process_loop():
    assert not hasattr(invite_alerts, "run_sweeper")
