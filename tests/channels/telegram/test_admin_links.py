"""channels/telegram/admin_links.py: argument names sent to each RPC and mapping of every result shape."""

from __future__ import annotations

import pytest

from channels.telegram import admin_links
from channels.telegram.admin_links import AdminRestaurant

ADA = "447700900301"


async def test_link_maps_every_field(admin_db):
    admin_db.add_admin(ADA, "ELAS", "WREN")
    admin_db.record(ADA, tuid=9, tcid=9, t_username="old", channels=["whatsapp"])
    out = await admin_links.link(111, 222, "+44 7700 900301", "ada", "Ada")
    assert out.result == "relinked" and out.is_linked
    assert (out.phone, out.previous_tuid, out.previous_username) == (ADA, 9, "old")
    assert out.restaurants == (AdminRestaurant("ELAS", "Ela's Kitchen"), AdminRestaurant("WREN", "Wren <Cafe>"))
    assert isinstance(out.channels, tuple)
    assert admin_db.rpc_args[-1] == ("t_admin_link", {"p_tuid": 111, "p_tcid": 222, "p_phone": "+44 7700 900301",
                                                     "p_username": "ada", "p_first_name": "Ada"})


@pytest.mark.parametrize("phone, result, linked", [(ADA, "linked", True), ("447700900399", "not_on_roster", False),
                                                    ("12", "bad_phone", False)])
async def test_link_results(admin_db, phone, result, linked):
    admin_db.add_admin(ADA)
    out = await admin_links.link(1, 1, phone, None, None)
    assert out.result == result and out.is_linked is linked


async def test_tuid_taken_carries_the_last_four_digits(admin_db):
    admin_db.add_admin(ADA)
    admin_db.add_admin("447700900302")
    await admin_links.link(1, 1, ADA, None, None)
    out = await admin_links.link(1, 1, "447700900302", None, None)
    assert out.result == "tuid_taken" and out.phone_last4 == "0301" and not out.is_linked


async def test_profile_results(admin_db):
    admin_db.add_admin(ADA)
    assert (await admin_links.profile(1)).result == "not_linked"
    await admin_links.link(1, 1, ADA, "ada", "Ada")
    prof = await admin_links.profile(1)
    assert prof.is_admin and prof.phone == ADA and prof.channels == ("telegram",) and prof.t_first_name == "Ada"
    assert prof.restaurants == (AdminRestaurant("ELAS", "Ela's Kitchen"),)
    admin_db.restaurants["ELAS"][1].clear()
    gone = await admin_links.profile(1)
    assert gone.result == "not_on_roster" and not gone.is_admin


@pytest.mark.parametrize("bad", [None, [], "x", {"no_result": 1}])
async def test_unexpected_response_raises(monkeypatch, bad):
    class Bad:
        def rpc(self, *_a, **_k):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": bad})()})()

    monkeypatch.setattr("channels.telegram.admin_links.client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await admin_links.link(1, 1, ADA, None, None)
    with pytest.raises(RuntimeError):
        await admin_links.profile(1)
