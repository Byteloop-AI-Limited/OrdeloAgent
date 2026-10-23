"""The live harness ordelo_datamodels/test_support/test_rider_pauses_and_locations.sql on the isolated DB (phases R5-R6).

Runs every stage the way the owner will (one block at a time, twice) and checks: the script deletes and inserts nothing; its
only writes are UPDATEs of pauses rows whose principal is the owner's phone (nobody else's pause is touched); the read-only
stages run against the R5-R6 shape and show what the comments promise.
"""

from __future__ import annotations

import re

import pytest

from .conftest import ROOT

pytestmark = pytest.mark.usefixtures("sql_env")

SCRIPT = (ROOT / "ordelo_datamodels" / "test_support" / "test_rider_pauses_and_locations.sql").read_text()
ME, OTHER, ADMIN2 = "447448440754", "447700900961", "447700900962"


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
        db.execute("DELETE FROM public.pauses WHERE principal IN (%s, %s, %s)", (ME, OTHER, ADMIN2))
        db.execute("DELETE FROM public.t_invites WHERE rest_ref = 'STRK'")
        db.execute("DELETE FROM public.restaurant_master WHERE rest_ref = 'STRK'")
        db.execute("DELETE FROM public.rider_master WHERE rider_id IN (%s, %s)", (ME, OTHER))
        db.execute("DELETE FROM cron.job WHERE jobname = 'job_pause_sweep'")

    wipe()
    db.execute("INSERT INTO public.rider_master (rider_id, rider_name, town, status, is_in_shift, channel, tuid, tcid) VALUES"
               " (%s, 'Me', 'dummy', 'active', true, 'telegram', 999000000754, 999000000754),"
               " (%s, 'Other', 'dummy', 'active', true, 'whatsapp', NULL, NULL)", (ME, OTHER))
    db.execute("INSERT INTO public.restaurant_master (rest_ref, rest_name, admins) VALUES ('STRK', 'Strikers', %s)", ([ME, ADMIN2],))
    db.execute("INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id)"
               " VALUES ('STRK', %s, 'claimed', now(), 999000000754, 999000000754)", (ME,))
    db.execute("SELECT cron.schedule('job_pause_sweep', '* * * * *', 'SELECT public.job_pause_sweep()')")
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_RIDER', '6h,1d,3d'),"
               " ('PAUSE_DURATIONS_REST_ADMIN', '6h,1d,3d') ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    yield
    wipe()


def pause(db, audience, who, scope=None, dur="6h"):
    return db.execute("SELECT public.pause_start(%s, %s, %s, %s, 'telegram', 'test')", (audience, who, scope, dur)).fetchone()[0]


def test_the_script_has_every_stage():
    assert list(STAGES) == ["PREREQUISITES CHECK (read only)"] + [f"STAGE {n}" for n in range(0, 11)]


def test_it_deletes_and_inserts_nothing_and_updates_only_your_pauses():
    writes = [s for body in STAGES.values() for s in statements(body) if not s.upper().startswith("SELECT")]
    assert all(not re.match(r"(DELETE|INSERT|TRUNCATE|DROP|ALTER)\b", s, re.I) for s in writes)
    assert len(writes) == 4
    assert all(s.startswith("UPDATE public.pauses") and f"principal = '{ME}'" in s for s in writes)


def test_prerequisites(db):
    [[row]] = run(db, "PREREQUISITES CHECK (read only)")
    assert row == (7, 1, "telegram / active / dummy / in_shift true", "6h,1d,3d", 2, 1)


def test_stage0_and_stage10_end_only_your_pauses(db):
    pause(db, "rider", ME)
    pause(db, "rider", OTHER)
    pause(db, "rest_admin", ME, "STRK")
    for name in ("STAGE 0", "STAGE 0", "STAGE 10"):
        assert run(db, name)[-1] == [(0,)]
    left = db.execute("SELECT principal FROM public.pauses WHERE ended_at IS NULL AND principal IN (%s, %s)", (ME, OTHER)).fetchall()
    assert left == [(OTHER,)]
    assert db.execute("SELECT DISTINCT end_reason FROM public.pauses WHERE principal = %s", (ME,)).fetchall() == [("operator",)]


def test_the_rider_stages_follow_a_break(db):
    assert run(db, "STAGE 1") == [[("active", True, "telegram", False)]]
    pause(db, "rider", ME)
    stage2 = run(db, "STAGE 2")
    assert len(stage2[0]) == 1 and stage2[0][0][4:] == ("telegram", "test") and stage2[1] == [(True,)]
    for _ in range(2):
        [[(ends_at, reminded)]] = run(db, "STAGE 3")
        assert reminded is None
    other_before = db.execute("SELECT count(*) FROM public.pauses WHERE principal = %s", (OTHER,)).fetchone()
    db.execute("UPDATE public.pauses SET starts_at = now() - interval '1 hour', ends_at = now() - interval '1 second'"
               " WHERE principal = %s AND ended_at IS NULL", (ME,))
    db.execute("SELECT public.job_pause_sweep()")
    assert run(db, "STAGE 4") == [[(True, "expired", True)], [(False,)]]
    pause(db, "rider", ME, dur="1d")
    db.execute("SELECT public.pause_end('rider', %s, NULL, 'resumed')", (ME,))
    assert run(db, "STAGE 5") == [[("resumed", True)]]
    assert db.execute("SELECT count(*) FROM public.pauses WHERE principal = %s", (OTHER,)).fetchone() == other_before


def test_the_admin_stages_show_new_alerts_versus_access(db):
    assert run(db, "STAGE 7") == [[(1, 1, False)]]
    assert pause(db, "rest_admin", ME, "STRK")["result"] == "paused"  # the second admin stays on
    assert run(db, "STAGE 7") == [[(0, 1, True)]]
    for _ in range(2):
        [[row]] = run(db, "STAGE 8")
        assert row[0] == "STRK" and row[2] is False and row[3] is None


def test_read_only_stages_run_twice(db):
    for name in ("STAGE 6", "STAGE 9"):
        run(db, name)
        rows = run(db, name)
    assert (ME, "Me") not in rows[0] and (OTHER, "Other") in rows[0]
