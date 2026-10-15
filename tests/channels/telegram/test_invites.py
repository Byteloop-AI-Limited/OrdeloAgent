"""Tests for channels.telegram.invites (thin async wrapper over the tgram_* SQL functions)."""

from __future__ import annotations

import pytest

from channels.telegram import invites


async def test_preview_rejects_malformed_code_without_calling_db(invite_db):
    for bad in ("", "has space", "a" * 65, "semi;colon"):
        assert (await invites.preview_invite("rest_admin", bad, 1)).result == "unknown"
    assert invite_db.rpc_names == []


async def test_preview_and_claim_round_trip(invite_db):
    code = invite_db.add()
    assert (await invites.preview_invite("rest_admin", code, 7)).result == "pending"
    out = await invites.claim_invite("rest_admin", code, user_id=7, chat_id=7, username="u", first_name="F")
    assert out.result == "ok" and out.is_linked and out.rest_ref == "ELAS"
    row = invite_db.invites[code]
    assert row["uid"] == 7 and row["cid"] == 7 and row["username"] == "u"
    # same person again is idempotent; someone else is told it is used
    assert (await invites.preview_invite("rest_admin", code, 7)).result == "claimed_by_you"
    assert (await invites.preview_invite("rest_admin", code, 8)).result == "used"


async def test_second_claimer_loses(invite_db):
    code = invite_db.add()
    a = await invites.claim_invite("rest_admin", code, user_id=1, chat_id=1, username=None, first_name=None)
    b = await invites.claim_invite("rest_admin", code, user_id=2, chat_id=2, username=None, first_name=None)
    assert a.result == "ok" and b.result == "used" and invite_db.invites[code]["uid"] == 1


async def test_wrong_bot_key_is_unknown(invite_db):
    code = invite_db.add(bot_key="rider")
    assert (await invites.preview_invite("rest_admin", code, 1)).result == "unknown"


@pytest.mark.parametrize("status", ["expired", "revoked"])
async def test_unusable_statuses(invite_db, status):
    code = invite_db.add(status=status)
    out = await invites.claim_invite("rest_admin", code, user_id=1, chat_id=1, username=None, first_name=None)
    assert out.result == status and not out.is_linked


async def test_linked_restaurants(invite_db):
    c1, c2 = invite_db.add("AAAAAAAAAAAA", "ELAS"), invite_db.add("BBBBBBBBBBBB", "WREN")
    for c in (c1, c2):
        await invites.claim_invite("rest_admin", c, user_id=5, chat_id=5, username=None, first_name=None)
    assert {r.rest_ref for r in await invites.linked_restaurants("rest_admin", 5)} == {"ELAS", "WREN"}
    assert await invites.linked_restaurants("rest_admin", 6) == []


async def test_unexpected_rpc_payload_raises(monkeypatch):
    class Bad:
        def rpc(self, *a, **k):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": None})()})()

    monkeypatch.setattr("channels.telegram.invites.client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await invites.preview_invite("rest_admin", "ABC", 1)
