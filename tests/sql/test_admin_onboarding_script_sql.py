"""The fake-row harness ordelo_datamodels/test_support/test_admin_onboarding.sql on the isolated DB.

Runs every stage the way the owner will (one block at a time, twice) and checks the results the comments promise, that a
re-run from STAGE 0 is clean, and that the harness touches ONLY fiction-range phones (4477009009...), their pauses, and the
fake entries in STRK's admins list: the owner's own number and every other row stay exactly as they were. STAGE 12 is manual
(live Telegram) and contains only comments, which is checked too.
"""

from __future__ import annotations

import re

import pytest

from .conftest import ROOT

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "test_support" / "test_admin_onboarding.sql").read_text()
OWNER = "447448440754"


def stage(name: str) -> str:
    m = re.search(rf"-- ===== {re.escape(name)}\b.*?=====\n(.*?)(?=\n-- ===== |\Z)", SCRIPT, re.S)
    assert m, name
    return m.group(1)


def run(db, name):
    """Execute a stage statement by statement; return the last row of every SELECT."""
    out = []
    for stmt in (s.strip() for s in re.split(r";\s*(?:--[^\n]*)?\n", stage(name) + "\n")):
        body = "\n".join(ln for ln in stmt.splitlines() if not ln.lstrip().startswith("--")).strip()
        if not body:
            continue
        cur = db.execute(body)
        if body.upper().startswith("SELECT"):
            rows = cur.fetchall()
            out.append(rows[-1] if rows else None)
    return out


@pytest.fixture(autouse=True)
def world(db):
    db.execute("TRUNCATE public.restaurant_admin, public.t_invites, public.restaurant_master CASCADE")
    db.execute("DELETE FROM public.pauses WHERE principal LIKE '4477009009%'")
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_REST_ADMIN', '6h,1d,3d')"
               " ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('STRK', 'Strk Test', %s),"
               " ('ELAS', 'Elas Kitchen', %s)", ([OWNER], ["447000000111"]))
    db.execute("INSERT INTO public.restaurant_admin (phone) VALUES (%s)", (OWNER,))  # the owner's own record must survive
    yield
    run(db, "STAGE 0")
    db.execute("TRUNCATE public.restaurant_admin, public.t_invites, public.restaurant_master CASCADE")


def others(db):
    return (db.execute("SELECT rest_ref, rest_name, admins FROM public.restaurant_master WHERE rest_ref <> 'STRK' ORDER BY 1").fetchall(),
            db.execute("SELECT phone, channels, tuid FROM public.restaurant_admin WHERE phone NOT LIKE '4477009009%' ORDER BY 1").fetchall())


def strk_admins(db):
    return db.execute("SELECT admins FROM public.restaurant_master WHERE rest_ref = 'STRK'").fetchone()[0]


def test_prerequisites_query(db):
    assert run(db, "PREREQUISITES CHECK") == [(9, True, True)]


@pytest.mark.parametrize("attempt", [1, 2])
def test_every_stage_gives_what_its_comments_promise(db, attempt):
    before = others(db)
    assert run(db, "STAGE 0") == [(0, 0)]
    assert run(db, "STAGE 1") == [("not_on_roster",), (0,)]
    assert run(db, "STAGE 2") == [(1, 0, False)]
    (linked,), counts = run(db, "STAGE 3")
    assert linked["result"] == "linked" and any(r["rest_ref"] == "STRK" for r in linked["restaurants"])
    assert counts == (0, 1, 1)
    assert run(db, "STAGE 4") == [("already_linked",), (-100901, "harness_a2", ["telegram"])]
    (moved,), who = run(db, "STAGE 5")
    assert moved["result"] == "relinked" and moved["previous_tuid"] == 999000000901 and moved["previous_username"] == "harness_a2"
    assert who == (None, "447700900901")
    taken, none = run(db, "STAGE 6")
    assert taken[0] == {"result": "tuid_taken", "phone_last4": "0901"} and none == (0,)
    s7 = run(db, "STAGE 7")
    assert s7[0][0] == {"result": "ok", "channels": ["telegram", "whatsapp"]} and s7[1] == (1, 1)
    assert [r[0] for r in s7[2:]] == ["ok", "bad_channels", "bad_channels", "not_found", "ok"]
    s8 = run(db, "STAGE 8")
    assert [r[0] for r in s8[:2]] == ["ok", "paused"] and s8[2] == (0, 0, 1) and s8[3] == ("resumed",) and s8[4] == (1, 1)
    s9 = run(db, "STAGE 9")
    assert s9 == [("not_on_roster", None, 1), ("ok", "447700900901")]
    s10 = run(db, "STAGE 10")
    assert s10 == [("ok",), (["whatsapp"], None), ("not_linked",)]
    s11 = run(db, "STAGE 11")
    assert s11 == [None]  # the owner has only a record here (no claimed invite), and STAGE 10 left the fake with no Telegram chat
    run(db, "STAGE 0")
    assert others(db) == before and strk_admins(db) == [OWNER]


def test_the_harness_leaves_the_owner_and_other_restaurants_untouched_even_with_the_owner_linked(db):
    db.execute("SELECT public.t_admin_link(555, 555, %s, 'owner', 'Lohith')", (OWNER,))
    snap = db.execute("SELECT phone, channels, tuid, tcid FROM public.restaurant_admin WHERE phone = %s", (OWNER,)).fetchall()
    for n in range(0, 12):
        run(db, f"STAGE {n}")
    run(db, "STAGE 0")
    assert db.execute("SELECT phone, channels, tuid, tcid FROM public.restaurant_admin WHERE phone = %s", (OWNER,)).fetchall() == snap
    assert strk_admins(db) == [OWNER]
    assert db.execute("SELECT count(*) FROM public.pauses WHERE principal = %s", (OWNER,)).fetchone()[0] == 0


def test_every_write_in_the_script_is_scoped_to_fake_rows():
    code = "\n".join(ln for ln in SCRIPT.splitlines() if not ln.lstrip().startswith("--"))
    for m in re.finditer(r"\b(DELETE FROM|UPDATE)\s+(public\.\w+)(.*?);", code, re.S | re.I):
        stmt = m.group(0)
        if "restaurant_master" in stmt:
            assert "rest_ref = 'STRK'" in stmt, stmt
            assert "4477009009" in stmt or "array_append" in stmt or "array_remove" in stmt, stmt
            assert OWNER not in stmt, stmt
        else:
            assert "4477009009" in stmt or "999000000" in stmt, stmt
    assert not re.search(r"\b(DROP|TRUNCATE)\b", code, re.I)
    assert not re.search(r"\bINSERT\b", code, re.I)


def test_stage_12_is_manual_and_only_comments():
    assert [ln for ln in stage("STAGE 12").splitlines() if ln.strip() and not ln.lstrip().startswith("--")] == []
