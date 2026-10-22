"""The live harness ordelo_datamodels/test_support/test_rider_telegram_jobs.sql on the isolated DB.

Runs every stage the way the owner will (one block at a time, twice) and checks: the script deletes and inserts nothing;
its only writes are closing threads of STRK-TEST-* dispatches (STAGE 0) and the owner's own rider row (STAGE 0b); the
read-only stages run against the R2-R4 shape and show what the comments promise; STAGE 9 is comments only.
"""

from __future__ import annotations

import re

import pytest

from .conftest import ROOT

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "test_support" / "test_rider_telegram_jobs.sql").read_text()
ME, OTHER = "447448440754", "447700900991"


def stages() -> dict[str, str]:
    parts = re.split(r"^-- ===== (.+?) =====\s*$", SCRIPT, flags=re.M)
    return {re.match(r"(PREREQUISITES CHECK \(read only\)|STAGE \w+)", name).group(1): body
            for name, body in zip(parts[1::2], parts[2::2])}


STAGES = stages()


def statements(body: str) -> list[str]:
    out = []
    for stmt in re.split(r";\s*(?:--[^\n]*)?\n", body + "\n"):
        code = "\n".join(ln for ln in stmt.splitlines() if not ln.lstrip().startswith("--")).strip()
        if code:
            out.append(code)
    return out


def run(db, name):
    rows = []
    for stmt in statements(STAGES[name]):
        cur = db.execute(stmt)
        if stmt.upper().startswith("SELECT"):
            rows.append(cur.fetchall())
    return rows


@pytest.fixture(autouse=True)
def data(db):
    def wipe():
        db.execute("DELETE FROM public.thread WHERE recipient IN (%s, %s)", (ME, OTHER))
        db.execute("DELETE FROM public.delivery_dispatch WHERE rider_id IN (%s, %s)", (ME, OTHER))
        db.execute("DELETE FROM public.delivery_summary WHERE order_number IN ('STRK-TEST-120000', 'REAL-1')")
        db.execute("DELETE FROM public.rider_master WHERE rider_id IN (%s, %s)", (ME, OTHER))

    wipe()
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, channel, tuid, tcid)"
               " VALUES (%s, 'Me', 'bicycle', 'Salisbury', 'inactive', false, 'telegram', 999000000991, 999000000991),"
               "        (%s, 'Other', 'bike', 'Salisbury', 'active', true, 'whatsapp', NULL, NULL)", (ME, OTHER))
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('overwatch_list', %s)"
               " ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value", (f'["{ME}"]',))
    db.execute("INSERT INTO public.delivery_summary (order_number) VALUES ('STRK-TEST-120000'), ('REAL-1')")
    fake = db.execute("INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES ('STRK-TEST-120000', %s, 'assigned')"
                      " RETURNING dispatch_id", (ME,)).fetchone()[0]
    real = db.execute("INSERT INTO public.delivery_dispatch (order_number, rider_id, status) VALUES ('REAL-1', %s, 'assigned')"
                      " RETURNING dispatch_id", (OTHER,)).fetchone()[0]
    db.execute("SELECT public.rider_thread_open('ORDELO', %s, %s)", (ME, fake))
    db.execute("SELECT public.rider_thread_open('ORDELO', %s, %s)", (OTHER, real))
    yield fake, real
    wipe()


def test_the_script_has_every_stage():
    assert list(STAGES) == ["PREREQUISITES CHECK (read only)", "STAGE 0", "STAGE 0b"] + [f"STAGE {n}" for n in range(1, 10)]


def test_it_deletes_and_inserts_nothing_and_updates_only_its_scope():
    writes = [s for body in STAGES.values() for s in statements(body) if not s.upper().startswith("SELECT")]
    assert all(not re.match(r"(DELETE|INSERT|TRUNCATE|DROP|ALTER)\b", s, re.I) for s in writes)
    assert len(writes) == 2
    thread_update, rider_update = writes
    assert thread_update.startswith("UPDATE public.thread") and "LIKE 'STRK-TEST-%'" in thread_update
    assert rider_update.startswith("UPDATE public.rider_master") and f"WHERE rider_id = '{ME}'" in rider_update
    assert statements(STAGES["STAGE 9"]) == []  # the channel switch back is manual (commented)


def test_prerequisites(db):
    [[row]] = run(db, "PREREQUISITES CHECK (read only)")
    assert row[:3] == (3, 1, 6)
    assert row[3].startswith("telegram / tcid 999000000991") and row[4] is True


def test_stage0_closes_only_fake_order_threads_and_is_repeatable(db, data):
    fake, real = data
    assert run(db, "STAGE 0")[-1] == [(0,)]
    assert run(db, "STAGE 0")[-1] == [(0,)]
    open_ = dict(db.execute("SELECT thread_id, is_active FROM public.thread WHERE recipient IN (%s, %s)", (ME, OTHER)).fetchall())
    assert open_ == {f"ORDELO-dispatch-{fake}": False, f"ORDELO-dispatch-{real}": True}


def test_stage0b_prepares_only_my_rider(db):
    before = db.execute("SELECT * FROM public.rider_master WHERE rider_id = %s", (OTHER,)).fetchone()
    rows = run(db, "STAGE 0b")
    assert rows[-1] == [(ME, "active", "dummy", "bicycle", True, "telegram", True)]
    assert db.execute("SELECT * FROM public.rider_master WHERE rider_id = %s", (OTHER,)).fetchone() == before


def test_the_read_only_stages_show_the_job(db, data):
    fake, _real = data
    db.execute("UPDATE public.delivery_dispatch SET channel_msg_ref = 'tg:999000000991:5' WHERE dispatch_id = %s", (fake,))
    assert run(db, "STAGE 1")[0][0][3:5] == ("telegram", "tg:999000000991:5")
    stage2 = run(db, "STAGE 2")
    assert stage2[0][0][:4] == (fake, "assigned", f"ORDELO-dispatch-{fake}", True)
    assert stage2[1][0][0]["channel"] == "telegram"
    assert run(db, "STAGE 3")[0][0][:2] == (f"ORDELO-dispatch-{fake}", True)
    for name in ("STAGE 4", "STAGE 5", "STAGE 6", "STAGE 7", "STAGE 8"):
        run(db, name)
        run(db, name)
