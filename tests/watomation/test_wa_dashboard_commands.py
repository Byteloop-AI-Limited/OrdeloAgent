"""WhatsApp /login and /sysadmin: links come from ordelo/dashboard_links.py for the verified wa_id (never typed text)."""

from __future__ import annotations

import pytest

from ordelo import dashboard_links
from ordelo.dashboard_links import Issued, PortalLink
from tests.fixtures.fake_wa import FakeAsyncWhatsApp, FakeMessage
from watomation import on_message_wa_handler as handler

ADA = "447700900101"


@pytest.fixture
def issued(monkeypatch):
    calls = []
    outcome = {"value": None}

    async def issue(portal, actor):
        calls.append((portal, actor.wa_phone, actor.tuid))
        if isinstance(outcome["value"], Exception):
            raise outcome["value"]
        return outcome["value"]

    monkeypatch.setattr(dashboard_links, "issue", issue)
    return calls, outcome


def texts(wa):
    return [s.kwargs["text"] for s in wa.sent]


async def test_login_sends_one_link_per_restaurant(issued):
    calls, outcome = issued
    outcome["value"] = Issued("ok", (PortalLink("Manage Elas", "https://x/rest-admin/activate/a", "ELAS"),
                                     PortalLink("Manage Wren", "https://x/rest-admin/activate/b", "WREN")))
    wa = FakeAsyncWhatsApp()
    await handler.handle_login_wa_msg(wa, FakeMessage(text="/login 447700900999", sender=ADA))
    assert calls == [("rest_admin", ADA, None)]  # the sender, never the typed number
    (text,) = texts(wa)
    assert "Manage Elas:\nhttps://x/rest-admin/activate/a" in text and "Manage Wren:\nhttps://x/rest-admin/activate/b" in text


@pytest.mark.parametrize("result", ["not_linked", "not_allowed"])
async def test_login_refuses_a_non_admin(issued, result):
    calls, outcome = issued
    outcome["value"] = Issued(result)
    wa = FakeAsyncWhatsApp()
    await handler.handle_login_wa_msg(wa, FakeMessage(text="/login", sender=ADA))
    assert texts(wa) == ["You are not a registered restaurant admin."]


async def test_sysadmin_link_and_refusal_and_failure(issued):
    calls, outcome = issued
    wa = FakeAsyncWhatsApp()
    outcome["value"] = Issued("ok", (PortalLink("Open system dashboard", "https://x/sys-admin/activate/t"),))
    await handler.handle_sysadmin_wa_msg(wa, FakeMessage(text="/sysadmin", sender=ADA))
    outcome["value"] = Issued("not_allowed")
    await handler.handle_sysadmin_wa_msg(wa, FakeMessage(text="/sysadmin", sender=ADA))
    outcome["value"] = RuntimeError("down https://x/secret")
    await handler.handle_sysadmin_wa_msg(wa, FakeMessage(text="/sysadmin", sender=ADA))
    assert calls[0] == ("sys_admin", ADA, None)
    t = texts(wa)
    assert "https://x/sys-admin/activate/t" in t[0]
    assert t[1] == "You are not authorized as sys-admin." and t[2] == "Something went wrong. Please try again."
