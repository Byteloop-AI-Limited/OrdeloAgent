"""The fake-row harness ordelo_datamodels/test_support/test_rider_onboarding.sql on the isolated DB.

Runs every stage the way the owner will (one block at a time, twice) and checks the results the comments promise, that a
re-run from STAGE 0 is clean, and that the harness touches ONLY its own fiction-range riders (rider_id 4477009008...) and
their pauses. STAGE 8 is manual (live Telegram) and contains only comments, which is checked too.
"""

from __future__ import annotations

import re

import pytest

from .conftest import ROOT

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "test_support" / "test_rider_onboarding.sql").read_text()


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
            out.append(cur.fetchall()[-1])
    return out


@pytest.fixture(autouse=True)
def config(db):
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_RIDER', '6h,1d,3d')"
               " ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name, status) VALUES ('447000000999', 'Real Rider', 'active')"
               " ON CONFLICT (rider_id) DO NOTHING")
    yield
    run(db, "STAGE 0")
    db.execute("DELETE FROM public.rider_master WHERE rider_id = '447000000999'")


def snapshot_of_others(db):
    return db.execute("SELECT rider_id, status, channel, tuid FROM public.rider_master WHERE rider_id NOT LIKE '4477009008%'"
                      " ORDER BY rider_id").fetchall()


def test_prerequisites_query(db):
    # The R1 get_available_riders() (step 5 of the migration) is loaded here; the shared test env does not need it.
    db.execute("ALTER TABLE public.delivery_dispatch ADD COLUMN IF NOT EXISTS vehicle_type varchar(15)")
    db.execute((ROOT / "ordelo_datamodels" / "ordering" / "order_has_test_item.sql").read_text())
    db.execute((ROOT / "ordelo_datamodels" / "dispatch" / "job_create_dispatch.sql").read_text())
    assert run(db, "PREREQUISITES CHECK") == [(7, 10, True)]


@pytest.mark.parametrize("attempt", [1, 2])
def test_every_stage_gives_what_its_comments_promise(db, attempt):
    before = snapshot_of_others(db)
    assert run(db, "STAGE 0") == [(0,)]
    linked, row = run(db, "STAGE 1")
    assert linked == ("linked",)
    assert row == ("447700900801", "telegram", 999000000801, 999000000801, True, True)
    assert run(db, "STAGE 2") == [("already_linked",), (-100801, "harness_a2")]
    (moved,), tuid = run(db, "STAGE 3")
    assert moved["result"] == "relinked" and moved["previous_tuid"] == 999000000801
    assert moved["previous_username"] == "harness_a2" and tuid == (999000000802,)
    (taken,), other = run(db, "STAGE 4")
    assert taken == {"result": "tuid_taken", "rider_id": "447700900801"} and other == (None,)
    s5 = run(db, "STAGE 5")
    assert s5[0][0]["result"] == "registered" and s5[0][0]["needs_profile"] is True
    assert "dummy" in s5[1][0]["towns"] and "bike" in s5[1][0]["vehicle_types"]
    assert s5[2][0] == {"result": "ok", "town": "dummy", "vehicle_type": "TBD", "needs_profile": True}
    assert s5[3][0]["needs_profile"] is False
    assert s5[4] == ("bad_town",)
    assert s5[5] == ("447700900804", "Newbie", "inactive", "dummy", "bike", "telegram", True)
    s6 = run(db, "STAGE 6")
    assert [s6[0], s6[1], s6[3], s6[4], s6[5]] == [("paused",), (True,), ("bad_duration",), ("resumed",), (False,)]
    assert s6[2][0]["result"] == "extended"
    s7 = run(db, "STAGE 7")
    assert s7[0] == ("paused",)
    gate = db.execute("SELECT rider_id, status FROM public.rider_master WHERE rider_id LIKE '4477009008%' ORDER BY 1").fetchall()
    assert [g[1] for g in gate] == ["inactive", "inactive", "inactive"]  # STAGE 7 restores 803
    assert s7[-1] == ("resumed",)
    assert snapshot_of_others(db) == before  # nothing outside the harness rows changed


def test_stage_8_is_comments_only():
    assert all(ln.startswith("--") or not ln.strip() for ln in stage("STAGE 8").splitlines())


def test_deletes_are_limited_to_the_fake_range():
    deletes = re.findall(r"^DELETE FROM .*$", SCRIPT, re.M)
    assert len(deletes) == 2
    assert all("'4477009008%'" in d for d in deletes)
