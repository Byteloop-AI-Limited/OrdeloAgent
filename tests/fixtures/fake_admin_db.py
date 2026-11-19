"""In-memory mimic of the admin roster SQL (ordelo_datamodels/restaurant_admin/admin_roster.sql) for offline tests.

Same result vocabulary and rules as t_admin_link, t_admin_profile, admin_set_channels, admin_unlink_telegram and
admin_recipients, plus is_overwatch (overwatch set) and the portal RPCs of admin_dashboard/auth_sessions.sql: portal_access,
rest_admin_dashboard_mint, sys_admin_dashboard_mint. Change it together with the SQL (tests/sql/test_admin_roster_sql.py and
tests/sql/test_admin_dashboard_sql.py prove the SQL side).

Key Functions:
  - admin_db - fixture: a FakeAdminDb patched in as client_ordelo_service of channels.telegram.admin_links and ordelo.admin_roster
"""

from __future__ import annotations

import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeAdminDb:
    """In-memory mimic of the roster SQL (admin_roster.sql): t_admin_link, t_admin_profile, admin_set_channels,
    admin_unlink_telegram, admin_recipients, admin_roster_status. Same result vocabulary and rules. Change it with the SQL."""

    def __init__(self):
        self.restaurants = {"ELAS": ("Ela's Kitchen", []), "WREN": ("Wren <Cafe>", [])}  # rest_ref -> (name, admins[])
        self.records: dict[str, dict] = {}  # phone -> record
        self.rpc_names: list[str] = []
        self.rpc_args: list[tuple[str, dict]] = []
        self.fail = False
        self.overwatch: set[str] = set()  # ordelo_config.overwatch_list (digits)
        self.minted: list[tuple] = []  # (role, phone, rest_ref) per successful mint

    @staticmethod
    def _digits(p):
        d = "".join(ch for ch in (p or "") if ch.isdigit())
        return d if 8 <= len(d) <= 15 else None

    def add_admin(self, phone, *rests):
        for r in rests or ("ELAS",):
            self.restaurants[r][1].append(phone)

    def record(self, phone, **kw):
        base = dict(phone=phone, channels=["whatsapp"], tuid=None, tcid=None, t_username=None, t_first_name=None)
        self.records[phone] = {**base, **kw}
        return self.records[phone]

    def _rests(self, phone):
        return [{"rest_ref": k, "rest_name": n} for k, (n, adm) in sorted(self.restaurants.items())
                if any(self._digits(a) == phone for a in adm)]

    def by_tuid(self, tuid):
        return next((r for r in self.records.values() if r["tuid"] == tuid), None)

    def _link(self, a):
        phone = self._digits(a["p_phone"])
        if phone is None or a["p_tuid"] is None or a["p_tcid"] is None:
            return {"result": "bad_phone"}
        if not self._rests(phone) and phone not in self.overwatch:
            return {"result": "not_on_roster"}
        other = self.by_tuid(a["p_tuid"])
        if other and other["phone"] != phone:
            return {"result": "tuid_taken", "phone_last4": other["phone"][-4:]}
        r = self.records.get(phone) or self.record(phone)
        prev = (r["tuid"], r["t_username"])
        if r["tuid"] is None:
            r.update(tuid=a["p_tuid"], tcid=a["p_tcid"], t_username=a["p_username"], t_first_name=a["p_first_name"],
                     channels=["telegram"])
            result = "linked"
        elif r["tuid"] == a["p_tuid"]:
            r.update(tcid=a["p_tcid"], t_username=a["p_username"], t_first_name=a["p_first_name"])
            result = "already_linked"
        else:
            r.update(tuid=a["p_tuid"], tcid=a["p_tcid"], t_username=a["p_username"], t_first_name=a["p_first_name"])
            result = "relinked"
        out = {"result": result, "phone": phone, "channels": list(r["channels"]), "restaurants": self._rests(phone),
               "sys_admin": phone in self.overwatch}
        if result == "relinked":
            out.update(previous_tuid=prev[0], previous_username=prev[1])
        return out

    def _profile(self, a):
        r = self.by_tuid(a["p_tuid"])
        if r is None:
            return {"result": "not_linked"}
        rests = self._rests(r["phone"])
        ops = r["phone"] in self.overwatch
        return {"result": "ok" if rests else ("ops_only" if ops else "not_on_roster"), "phone": r["phone"],
                "channels": list(r["channels"]), "t_first_name": r["t_first_name"], "restaurants": rests, "sys_admin": ops}

    def _actor_phone(self, a):
        if a.get("p_tuid") is not None:
            r = self.by_tuid(a["p_tuid"])
            return r and r["phone"]
        return self._digits(a.get("p_phone"))

    def _portal_access(self, a):
        phone = self._actor_phone(a)
        if phone is None:
            return {"result": "not_linked"}
        return {"result": "ok", "phone": phone, "restaurants": self._rests(phone), "sys_admin": phone in self.overwatch}

    def _rest_mint(self, a):
        phone = self._actor_phone(a)
        if phone is None:
            return {"result": "not_linked"}
        ref = (a["p_rest_ref"] or "").upper()
        if not any(x["rest_ref"] == ref for x in self._rests(phone)):
            return {"result": "not_allowed"}
        self.minted.append(("rest_admin", phone, ref))
        return {"result": "ok"}

    def _sys_mint(self, a):
        phone = self._actor_phone(a)
        if phone is None:
            return {"result": "not_linked"}
        if phone not in self.overwatch:
            return {"result": "not_allowed"}
        self.minted.append(("sys_admin", phone, None))
        return {"result": "ok"}

    def _set_channels(self, a):
        chans = sorted(set(a["p_channels"] or []))
        if not chans or not set(chans) <= {"whatsapp", "telegram"}:
            return {"result": "bad_channels"}
        r = self.records.get(self._digits(a["p_phone"]))
        if r is None:
            return {"result": "not_found"}
        if "telegram" in chans and r["tuid"] is None:
            return {"result": "not_linked", "channels": list(r["channels"])}
        r["channels"] = chans
        return {"result": "ok", "channels": chans}

    def _unlink(self, a):
        r = self.records.get(self._digits(a["p_phone"]))
        if r is None:
            return {"result": "not_found"}
        if r["tuid"] is None:
            return {"result": "not_linked"}
        r.update(tuid=None, tcid=None, t_username=None, t_first_name=None, channels=["whatsapp"])
        return {"result": "ok"}

    def _recipients(self, a):
        out = []
        for adm in self.restaurants[a["p_rest_ref"]][1]:
            phone = self._digits(adm)
            r = self.records.get(phone)
            chans = r["channels"] if r else ["whatsapp"]
            if phone and a["p_channel"] in chans and (a["p_channel"] != "telegram" or (r and r["tcid"])):
                out.append({"phone": phone, "tcid": r and r["tcid"], "tuid": r and r["tuid"],
                            "label": (r and r["t_first_name"]) or "…" + phone[-4:]})
        return out

    def rpc(self, name, args=None):
        if self.fail:
            raise RuntimeError("admin db down")
        self.rpc_names.append(name)
        self.rpc_args.append((name, dict(args or {})))
        fn = {"t_admin_link": self._link, "t_admin_profile": self._profile, "admin_set_channels": self._set_channels,
              "admin_unlink_telegram": self._unlink, "admin_recipients": self._recipients,
              "portal_access": self._portal_access, "rest_admin_dashboard_mint": self._rest_mint,
              "sys_admin_dashboard_mint": self._sys_mint}[name]
        data = fn(args or {})
        return type("Q", (), {"execute": lambda self_: _Resp(data)})()


@pytest.fixture
def admin_db(monkeypatch):
    db = FakeAdminDb()
    monkeypatch.setattr("channels.telegram.admin_links.client_ordelo_service", db)
    monkeypatch.setattr("ordelo.admin_roster.client_ordelo_service", db)
    monkeypatch.setattr("ordelo.dashboard_links.client_ordelo_service", db)

    async def app_url(role):
        return DASHBOARD_APP

    monkeypatch.setattr("ordelo.dashboard_links.get_dashboard_app_url_async", app_url)
    return db


DASHBOARD_APP = "https://restaurant-test.ordelo.app"
