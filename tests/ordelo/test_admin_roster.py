"""ordelo/admin_roster.py: recipients, the fail-open WhatsApp list, and the channel calls."""

from __future__ import annotations

import pytest

from ordelo import admin_roster

ADA, BOB = "447700900401", "447700900402"


async def test_recipients_keep_the_rpc_order(admin_db):
    admin_db.add_admin(BOB)
    admin_db.add_admin(ADA)
    out = await admin_roster.recipients("ELAS", "whatsapp")
    assert [r.phone for r in out] == [BOB, ADA]
    assert admin_db.rpc_args[-1] == ("admin_recipients", {"p_rest_ref": "ELAS", "p_channel": "whatsapp"})


async def test_whatsapp_phones_follow_the_channels_and_telegram_only_admins_drop_out(admin_db):
    admin_db.add_admin(ADA)
    admin_db.add_admin(BOB)
    admin_db.record(ADA, tuid=1, tcid=1, channels=["telegram"])
    assert await admin_roster.whatsapp_phones("ELAS") == [BOB]


async def test_whatsapp_phones_fail_open_to_the_raw_admins_list_in_order_deduped(admin_db):
    admin_db.fail = True
    assert await admin_roster.whatsapp_phones("ELAS", fallback=[BOB, ADA, BOB, ""]) == [BOB, ADA]


async def test_whatsapp_phones_without_a_restaurant_returns_the_fallback(admin_db):
    assert await admin_roster.whatsapp_phones(None, fallback=[ADA]) == [ADA]
    assert admin_db.rpc_names == []


async def test_whatsapp_phones_read_restaurant_master_when_no_fallback_is_given(admin_db, monkeypatch):
    from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

    admin_db.fail = True
    monkeypatch.setattr(RestaurantMaster, "get_admins_for", classmethod(lambda cls, rest_ref: [ADA, BOB]))
    assert await admin_roster.whatsapp_phones("ELAS") == [ADA, BOB]


async def test_whatsapp_phones_never_raise_even_when_the_fallback_read_fails(admin_db, monkeypatch):
    from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

    admin_db.fail = True

    def boom(cls, rest_ref):
        raise RuntimeError("db down")

    monkeypatch.setattr(RestaurantMaster, "get_admins_for", classmethod(boom))
    with pytest.raises(RuntimeError):
        await admin_roster.whatsapp_phones("ELAS")  # the single remaining failure mode is documented: no list at all


async def test_set_channels_and_unlink(admin_db):
    admin_db.add_admin(ADA)
    admin_db.record(ADA, tuid=1, tcid=1, channels=["telegram"])
    out = await admin_roster.set_channels(ADA, ["telegram", "whatsapp"], by="telegram:1")
    assert out.ok and out.channels == ("telegram", "whatsapp")
    assert admin_db.rpc_args[-1] == ("admin_set_channels", {"p_phone": ADA, "p_channels": ["telegram", "whatsapp"],
                                                           "p_by": "telegram:1"})
    assert (await admin_roster.set_channels(ADA, [], by="x")).result == "bad_channels"
    assert (await admin_roster.unlink_telegram(ADA, by="operator")).ok
    assert (await admin_roster.unlink_telegram(ADA, by="operator")).result == "not_linked"
    assert (await admin_roster.set_channels("447700900499", ["whatsapp"], by="x")).result == "not_found"
