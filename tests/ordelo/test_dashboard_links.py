"""ordelo/dashboard_links.py: every portal x actor x RPC result, through access()/issue() only (fake RPC contract)."""

from __future__ import annotations

import hashlib

import pytest

from ordelo import dashboard_links as dl
from ordelo.dashboard_links import Actor

BASE = "https://restaurant.example"


class FakeRpc:
    """Mimics the auth_sessions.sql RPC contract: portal_access / rider / rest_admin / sys_admin mints."""

    def __init__(self, access=None, mint=None):
        self.access = access or {"result": "ok", "phone": "447700900911", "sys_admin": False,
                                 "restaurants": [{"rest_ref": "ELAS", "rest_name": "Elas"},
                                                 {"rest_ref": "WREN", "rest_name": "Wren"}]}
        self.mint = mint or {}
        self.calls = []

    async def __call__(self, name, args):
        self.calls.append((name, args))
        if name == "portal_access":
            return self.access
        key = (name, args.get("p_rest_ref"))
        return {"result": self.mint.get(key, self.mint.get(name, "ok"))}


@pytest.fixture
def fake(monkeypatch):
    rpc = FakeRpc()
    monkeypatch.setattr(dl, "_rpc", rpc)

    async def origin(role):
        return BASE + "/"
    monkeypatch.setattr(dl, "get_dashboard_app_url_async", origin)
    return rpc


def token_of(url):
    return url.rsplit("/", 1)[1]


def test_actor_needs_exactly_one_identity():
    with pytest.raises(ValueError):
        Actor()
    with pytest.raises(ValueError):
        Actor(tuid=1, wa_phone="447700900911")


async def test_access_maps_the_rpc(fake):
    acc = await dl.access(Actor(tuid=7))
    assert acc.result == "ok" and [r.rest_ref for r in acc.restaurants] == ["ELAS", "WREN"] and acc.sys_admin is False
    assert fake.calls == [("portal_access", {"p_tuid": 7, "p_phone": None})]
    assert acc.can_open_anything


async def test_access_not_linked_and_nothing_to_open(fake):
    fake.access = {"result": "not_linked"}
    assert (await dl.access(Actor(tuid=7))).can_open_anything is False
    fake.access = {"result": "ok", "phone": "x", "restaurants": [], "sys_admin": False}
    assert (await dl.access(Actor(wa_phone="447700900999"))).can_open_anything is False


async def test_access_rejects_an_unknown_shape(fake):
    fake.access = {"oops": 1}
    with pytest.raises(RuntimeError):
        await dl.access(Actor(tuid=7))


async def test_rest_admin_one_link_per_restaurant_with_matching_hash(fake):
    out = await dl.issue("rest_admin", Actor(tuid=7))
    assert out.ok and [(link.label, link.rest_ref) for link in out.links] == [("Manage Elas", "ELAS"), ("Manage Wren", "WREN")]
    mints = [args for name, args in fake.calls if name == "rest_admin_dashboard_mint"]
    for link, args in zip(out.links, mints):
        assert link.url.startswith(BASE + "/rest-admin/activate/")
        assert hashlib.sha256(token_of(link.url).encode()).hexdigest() == args["p_token_hash"]
        assert args["p_tuid"] == 7 and args["p_phone"] is None
    assert len({token_of(link.url) for link in out.links}) == 2


async def test_rest_admin_skips_a_restaurant_removed_between_access_and_mint(fake):
    fake.mint = {("rest_admin_dashboard_mint", "WREN"): "not_allowed"}
    out = await dl.issue("rest_admin", Actor(wa_phone="447700900911"))
    assert [link.rest_ref for link in out.links] == ["ELAS"]


async def test_rest_admin_with_no_restaurants_or_unlinked(fake):
    fake.access = {"result": "ok", "phone": "x", "restaurants": [], "sys_admin": True}
    assert await dl.issue("rest_admin", Actor(tuid=7)) == dl.Issued("not_allowed")
    fake.access = {"result": "not_linked"}
    assert await dl.issue("rest_admin", Actor(tuid=7)) == dl.Issued("not_linked")


@pytest.mark.parametrize("result", ["ok", "not_linked", "not_allowed"])
async def test_sys_admin_every_result(fake, result):
    fake.mint = {"sys_admin_dashboard_mint": result}
    out = await dl.issue("sys_admin", Actor(tuid=7))
    assert out.result == result and out.ok is (result == "ok")
    if result == "ok":
        assert out.links[0].url.startswith(BASE + "/sys-admin/activate/") and out.links[0].label == "Open system dashboard"


async def test_sys_admin_whatsapp_actor_passes_the_phone(fake):
    await dl.issue("sys_admin", Actor(wa_phone="447700900913"))
    assert fake.calls[-1][1]["p_phone"] == "447700900913" and fake.calls[-1][1]["p_tuid"] is None


@pytest.mark.parametrize("result", ["ok", "not_linked"])
async def test_rider_every_result(fake, result):
    fake.mint = {"rider_dashboard_mint": result}
    out = await dl.issue("rider", Actor(tuid=891))
    assert out.result == result
    assert fake.calls[-1][1]["p_tuid"] == 891 and "p_phone" not in fake.calls[-1][1]
    if result == "ok":
        assert out.links[0].url.startswith(BASE + "/rider/activate/")


async def test_rider_is_never_issued_to_a_whatsapp_actor(fake):
    assert await dl.issue("rider", Actor(wa_phone="447700900911")) == dl.Issued("not_allowed")
    assert fake.calls == []


@pytest.mark.parametrize("origin", ["http://restaurant.example", "https://restaurant.example/path",
                                    "https://u:p@restaurant.example", "https://restaurant.example?q=1"])
async def test_non_https_or_odd_origins_are_refused(fake, monkeypatch, origin):
    async def bad(role):
        return origin
    monkeypatch.setattr(dl, "get_dashboard_app_url_async", bad)
    with pytest.raises(ValueError):
        await dl.issue("sys_admin", Actor(tuid=7))
    assert fake.calls == []


async def test_unexpected_mint_outcome_raises(fake):
    fake.mint = {"sys_admin_dashboard_mint": "weird"}
    with pytest.raises(RuntimeError):
        await dl.issue("sys_admin", Actor(tuid=7))


async def test_alias_restaurant_is_covered_by_its_canonical_link(fake):
    """CHKS shares ELAS's orders and settings (config.params alias): one ELAS link, not an empty CHKS dashboard."""
    fake.access = {"result": "ok", "phone": "p", "sys_admin": False,
                   "restaurants": [{"rest_ref": "CHKS", "rest_name": "Wings"}, {"rest_ref": "ELAS", "rest_name": "Elai"}]}
    out = await dl.issue("rest_admin", Actor(tuid=7))
    assert [link.rest_ref for link in out.links] == ["ELAS"]


async def test_alias_only_admin_keeps_the_alias_link(fake):
    fake.access = {"result": "ok", "phone": "p", "sys_admin": False, "restaurants": [{"rest_ref": "CHKS", "rest_name": "Wings"}]}
    out = await dl.issue("rest_admin", Actor(tuid=7))
    assert [link.rest_ref for link in out.links] == ["CHKS"]
