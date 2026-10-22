"""Rider bot onboarding SQL (ordelo_datamodels/telegram/t_rider_onboarding.sql) and the R1 dispatch gate, on the isolated DB.

Covers every result value of t_rider_link / t_rider_set_profile / t_rider_profile, the case-insensitive choices list, two
concurrent links of one new phone, the service-role-only grants, and get_available_riders(): only status = 'active' and
not paused riders are offered a job (D41, D51). Phones are in Ofcom's drama range 07700 900xxx (never a real rider).
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from .conftest import ROOT, URI, fetch_one, sql_path

pytestmark = pytest.mark.usefixtures("sql_env")

P1, P2, P3, P4 = "447700900501", "447700900502", "447700900503", "447700900504"
T1, T2, T3 = 999000000501, 999000000502, 999000000503
FAKE = "4477009005%"


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("DELETE FROM public.pauses WHERE principal LIKE %s", (FAKE,))
    db.execute("DELETE FROM public.rider_master WHERE rider_id LIKE %s OR tuid BETWEEN 999000000500 AND 999000000599", (FAKE,))
    db.execute("DELETE FROM public.rider_master WHERE rider_id IN ('RCHOICE1', 'RCHOICE2', 'RCHOICE3')")
    yield
    db.execute("DELETE FROM public.pauses WHERE principal LIKE %s", (FAKE,))
    db.execute("DELETE FROM public.rider_master WHERE rider_id LIKE %s OR tuid BETWEEN 999000000500 AND 999000000599", (FAKE,))
    db.execute("DELETE FROM public.rider_master WHERE rider_id IN ('RCHOICE1', 'RCHOICE2', 'RCHOICE3')")


def link(db, tuid, phone, tcid=None, username="ada", first="Ada"):
    return fetch_one(db, "SELECT public.t_rider_link(%s, %s, %s, %s, %s)", (tuid, tcid or tuid, phone, username, first))


def rider(db, phone):
    return db.execute(
        "SELECT rider_name, status, town, vehicle_type, channel, tuid, tcid, t_username, phone_verified, is_in_shift"
        " FROM public.rider_master WHERE rider_id = %s",
        (phone,),
    ).fetchone()


def add_rider(db, phone, status="active", town="Salisbury", vehicle="bike", in_shift=False, tuid=None):
    db.execute(
        "INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, tuid, tcid)"
        " VALUES (%s, 'Sam', %s, %s, %s, %s, %s, %s)",
        (phone, vehicle, town, status, in_shift, tuid, tuid),
    )


# ---- phone normalisation -------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, digits",
    [("+44 7700 900501", P1), ("447700900501", P1), ("(44) 7700-900501", P1), ("12345", None), ("", None), (None, None),
     ("4477009005011234", None)],
)
def test_phone_digits(db, raw, digits):
    assert fetch_one(db, "SELECT public.t_rider_phone_digits(%s)", (raw,)) == digits


# ---- t_rider_link: every result ------------------------------------------------------------------------------------
def test_unknown_phone_registers_an_inactive_rider(db):
    out = link(db, T1, "+" + P1, first="Priya")
    assert out["result"] == "registered"
    assert out["needs_profile"] is True and out["status"] == "inactive"
    name, status, town, vehicle, channel, tuid, tcid, username, verified, in_shift = rider(db, P1)
    assert (name, status, town, vehicle, channel, tuid, tcid, username, verified) == (
        "Priya", "inactive", "TBD", "TBD", "telegram", T1, T1, "ada", True)
    assert in_shift is True  # the column default: status is the gate, is_in_shift is not touched (D41)


def test_registration_without_first_name_uses_tbd(db):
    assert link(db, T1, P1, first="  ")["rider_name"] == "TBD"


def test_existing_rider_links_and_switches_channel(db):
    add_rider(db, P1, in_shift=False)
    out = link(db, T1, P1)
    assert out["result"] == "linked" and out["needs_profile"] is False and out["town"] == "Salisbury"
    _, status, _, _, channel, tuid, _, _, verified, in_shift = rider(db, P1)
    assert (status, channel, tuid, verified, in_shift) == ("active", "telegram", T1, True, True)


def test_same_person_again_refreshes_chat_and_names(db):
    link(db, T1, P1)
    out = link(db, T1, P1, tcid=-555, username="ada_new", first="Ada2")
    assert out["result"] == "already_linked"
    row = rider(db, P1)
    assert (row[6], row[7]) == (-555, "ada_new")


def test_another_account_with_the_same_phone_moves_the_link(db):
    link(db, T1, P1, username="old")
    out = link(db, T2, P1, username="new")
    assert out["result"] == "relinked"
    assert out["previous_tuid"] == T1 and out["previous_username"] == "old"
    assert rider(db, P1)[5] == T2


def test_account_linked_to_another_rider_is_refused(db):
    link(db, T1, P1)
    add_rider(db, P2)
    out = link(db, T1, P2)
    assert out == {"result": "tuid_taken", "rider_id": P1}
    assert rider(db, P2)[5] is None  # untouched


@pytest.mark.parametrize("phone", ["12", "abc", "", None])
def test_bad_phone(db, phone):
    assert link(db, T1, phone) == {"result": "bad_phone"}


def test_concurrent_first_links_of_one_phone_have_one_registration():
    results = []
    barrier = threading.Barrier(2)

    def go(tuid):
        with psycopg.connect(URI, autocommit=True) as c:
            barrier.wait()
            results.append(c.execute("SELECT public.t_rider_link(%s, %s, %s, 'x', 'X')", (tuid, tuid, P3)).fetchone()[0])

    threads = [threading.Thread(target=go, args=(t,)) for t in (T1, T2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    kinds = sorted(r["result"] for r in results)
    assert kinds == ["registered", "relinked"]
    with psycopg.connect(URI, autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM public.rider_master WHERE rider_id = %s", (P3,)).fetchone()[0] == 1


# ---- choices and profile -------------------------------------------------------------------------------------------
def test_choices_are_distinct_case_insensitive_and_never_tbd(db):
    add_rider(db, "RCHOICE1", town="salisbury", vehicle="car")
    add_rider(db, "RCHOICE2", town="Salisbury ", vehicle="bike")
    add_rider(db, "RCHOICE3", town="TBD", vehicle="TBD")
    choices = fetch_one(db, "SELECT public.t_rider_choices()")
    towns = [t.lower() for t in choices["towns"]]
    assert towns.count("salisbury") == 1 and "tbd" not in towns
    assert {"car", "bike"} <= set(choices["vehicle_types"]) and "TBD" not in choices["vehicle_types"]


def test_set_profile_fills_tbd_values_with_the_listed_spelling(db):
    add_rider(db, "RCHOICE1", town="Salisbury", vehicle="car")
    link(db, T1, P1)
    out = fetch_one(db, "SELECT public.t_rider_set_profile(%s, %s, NULL)", (T1, "SALISBURY"))
    assert out == {"result": "ok", "town": "Salisbury", "vehicle_type": "TBD", "needs_profile": True}
    out = fetch_one(db, "SELECT public.t_rider_set_profile(%s, NULL, %s)", (T1, "car"))
    assert out == {"result": "ok", "town": "Salisbury", "vehicle_type": "car", "needs_profile": False}


def test_set_profile_rejections(db):
    add_rider(db, "RCHOICE1", town="Salisbury", vehicle="car")
    add_rider(db, "RCHOICE2", town="Andover", vehicle="bike")
    assert fetch_one(db, "SELECT public.t_rider_set_profile(%s, 'Salisbury', NULL)", (T3,)) == {"result": "not_linked"}
    link(db, T1, P1)
    assert fetch_one(db, "SELECT public.t_rider_set_profile(%s, 'Atlantis', NULL)", (T1,)) == {"result": "bad_town"}
    assert fetch_one(db, "SELECT public.t_rider_set_profile(%s, NULL, 'jetpack')", (T1,)) == {"result": "bad_vehicle"}
    fetch_one(db, "SELECT public.t_rider_set_profile(%s, 'Salisbury', 'car')", (T1,))
    locked = fetch_one(db, "SELECT public.t_rider_set_profile(%s, 'Andover', NULL)", (T1,))
    assert locked["result"] == "locked" and locked["town"] == "Salisbury"
    # Repeating the same value is fine (a double tap).
    assert fetch_one(db, "SELECT public.t_rider_set_profile(%s, 'salisbury', 'car')", (T1,))["result"] == "ok"


def test_profile(db):
    assert fetch_one(db, "SELECT public.t_rider_profile(%s)", (T1,)) == {"result": "not_linked"}
    link(db, T1, P1, first="Priya")
    p = fetch_one(db, "SELECT public.t_rider_profile(%s)", (T1,))
    assert p["result"] == "ok" and p["rider_id"] == P1 and p["status"] == "inactive" and p["channel"] == "telegram"
    assert p["tcid"] == T1 and p["needs_profile"] is True


# ---- grants --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        for sql in ("SELECT public.t_rider_link(1, 1, '447700900501', NULL, NULL)",
                    "SELECT public.t_rider_set_profile(1, NULL, NULL)",
                    "SELECT public.t_rider_choices()",
                    "SELECT public.t_rider_profile(1)",
                    "SELECT public.t_rider_phone_digits('1')"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
    finally:
        db.execute("RESET ROLE")


def test_onboarding_file_is_repeatable(db):
    db.execute(sql_path("t_rider_onboarding.sql").read_text())
    db.execute(sql_path("rider_master.sql").read_text())


# ---- get_available_riders: the R1 dispatch gate --------------------------------------------------------------------
DISPATCH_SCHEMA = """
ALTER TABLE public.delivery_dispatch ADD COLUMN IF NOT EXISTS vehicle_type varchar(15);
"""


@pytest.fixture
def dispatch_fns(db):
    db.execute(DISPATCH_SCHEMA)
    db.execute((ROOT / "ordelo_datamodels" / "ordering" / "order_has_test_item.sql").read_text())
    db.execute(sql_path("job_create_dispatch.sql").read_text())
    db.execute("INSERT INTO public.food_order (order_id, order_number) VALUES ('R1-GATE-O', 'R1-GATE-1') ON CONFLICT DO NOTHING")
    yield
    db.execute("DELETE FROM public.food_order WHERE order_id = 'R1-GATE-O'")


def offered(db):
    rows = db.execute("SELECT rider_id FROM public.get_available_riders('R1-GATE-1', 'gatetown', 'bike')").fetchall()
    return {r[0] for r in rows}


def test_only_active_unpaused_riders_are_offered(db, dispatch_fns):
    add_rider(db, P1, status="active", town="GateTown", in_shift=True)
    add_rider(db, P2, status="inactive", town="GateTown", in_shift=True)
    add_rider(db, P3, status="Active", town="GateTown", in_shift=True)  # wrong spelling is NOT dispatchable
    add_rider(db, P4, status="active", town="GateTown", in_shift=True)
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('PAUSE_DURATIONS_RIDER', '6h,1d,3d')"
               " ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value")
    assert fetch_one(db, "SELECT public.pause_start('rider', %s, NULL, '6h', 'operator', 'test')", (P4,))["result"] == "paused"
    assert offered(db) == {P1}
    fetch_one(db, "SELECT public.pause_end('rider', %s, NULL, 'resumed')", (P4,))
    assert offered(db) == {P1, P4}


def test_expired_pause_no_longer_blocks_dispatch_before_any_sweep(db, dispatch_fns):
    add_rider(db, P1, status="active", town="GateTown", in_shift=True)
    db.execute("INSERT INTO public.pauses (audience, principal, starts_at, ends_at, created_via)"
               " VALUES ('rider', %s, now() - interval '2 hours', now() - interval '1 minute', 'operator')", (P1,))
    assert offered(db) == {P1}
