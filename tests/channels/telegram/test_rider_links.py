"""channels/telegram/rider_links.py: argument names sent to each RPC and mapping of every result shape."""

from __future__ import annotations

import pytest

from channels.telegram import rider_links


async def test_link_maps_every_field(rider_db):
    rider_db.add("447700900501", name="Sam", tuid=9, tcid=9)
    rider_db.riders["447700900501"]["t_username"] = "old"
    out = await rider_links.link(111, 222, "+447700900501", "ada", "Ada")
    assert out.result == "relinked" and out.is_linked and out.is_active
    assert (out.rider_id, out.previous_tuid, out.previous_username) == ("447700900501", 9, "old")
    assert rider_db.rpc_args[-1] == ("t_rider_link", {"p_tuid": 111, "p_tcid": 222, "p_phone": "+447700900501",
                                                       "p_username": "ada", "p_first_name": "Ada"})


@pytest.mark.parametrize("phone, result, linked", [("447700900502", "registered", True), ("12", "bad_phone", False)])
async def test_link_results(rider_db, phone, result, linked):
    out = await rider_links.link(1, 1, phone, None, None)
    assert out.result == result and out.is_linked is linked


async def test_set_profile_and_profile_and_choices(rider_db):
    await rider_links.link(1, 1, "447700900503", None, "Neo")
    out = await rider_links.set_profile(1, town="salisbury")
    assert (out.result, out.town, out.needs_profile) == ("ok", "Salisbury", True)
    assert rider_db.rpc_args[-1] == ("t_rider_set_profile", {"p_tuid": 1, "p_town": "salisbury", "p_vehicle_type": None})
    prof = await rider_links.profile(1)
    assert prof.is_linked and prof.rider_name == "Neo" and prof.channel == "telegram"
    assert not (await rider_links.profile(2)).is_linked
    ch = await rider_links.choices()
    assert ch.towns == ["Andover", "Salisbury"] and ch.vehicle_types == ["bike", "car"]


async def test_unexpected_response_raises(monkeypatch):
    class Bad:
        def rpc(self, *_a, **_k):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": None})()})()

    monkeypatch.setattr("channels.telegram.rider_links.client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await rider_links.link(1, 1, "447700900501", None, None)
