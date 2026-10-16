"""Isolated-database tests for ordelo_datamodels/telegram/create_t_inbox.sql (skipped without ORDELO_TEST_DB_URI)."""

from __future__ import annotations

import threading

import psycopg
import pytest


from .conftest import _connect, fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.t_inbox")


def claim(conn, update_id=1, bot="rest_admin", kind="message", tuid=111):
    return fetch_one(conn, "SELECT public.t_inbox_claim(%s, %s, %s, %s)", (bot, update_id, kind, tuid))


def finish(conn, update_id=1, status="done", err=None, bot="rest_admin"):
    return fetch_one(conn, "SELECT public.t_inbox_finish(%s, %s, %s, %s)", (bot, update_id, status, err))


def test_first_claim_is_new_second_is_duplicate_with_status(db):
    assert claim(db) == {"result": "new"}
    assert claim(db) == {"result": "duplicate", "status": "processing"}
    finish(db)
    assert claim(db) == {"result": "duplicate", "status": "done"}


def test_claim_is_per_bot(db):
    assert claim(db, bot="rest_admin")["result"] == "new"
    assert claim(db, bot="rider")["result"] == "new"


def test_claim_records_kind_and_tuid_and_allows_null_tuid(db):
    claim(db, 5, kind="callback_query", tuid=4242)
    claim(db, 6, kind="channel_post", tuid=None)
    rows = dict((r[0], r[1:]) for r in db.execute("SELECT update_id, kind, tuid, status FROM public.t_inbox").fetchall())
    assert rows[5] == ("callback_query", 4242, "processing")
    assert rows[6] == ("channel_post", None, "processing")


def test_finish_done_and_failed_and_not_processing(db):
    claim(db, 1)
    assert finish(db, 1, "done") == {"result": "ok"}
    assert finish(db, 1, "failed", "late") == {"result": "not_processing"}
    claim(db, 2)
    assert finish(db, 2, "failed", "boom") == {"result": "ok"}
    row = db.execute("SELECT status, error, finished_at IS NOT NULL FROM public.t_inbox WHERE update_id = 2").fetchone()
    assert row == ("failed", "boom", True)
    assert finish(db, 99) == {"result": "not_processing"}  # never claimed


def test_finish_truncates_long_error(db):
    claim(db, 1)
    finish(db, 1, "failed", "x" * 5000)
    assert fetch_one(db, "SELECT length(error) FROM public.t_inbox WHERE update_id = 1") == 2000


def test_finish_rejects_bad_status(db):
    claim(db, 1)
    with pytest.raises(psycopg.errors.RaiseException):
        finish(db, 1, "processing")


def test_status_check_constraint(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO public.t_inbox (bot_key, update_id, kind, status) VALUES ('b', 1, 'm', 'weird')")


def test_concurrent_claims_have_exactly_one_winner(sql_env):
    """Two connections race for the same update_id: exactly one gets 'new'."""
    results: list[str] = []
    barrier = threading.Barrier(8)

    def worker():
        conn = _connect()
        try:
            barrier.wait()
            results.append(fetch_one(conn, "SELECT public.t_inbox_claim('rest_admin', 777, 'message', 1)")["result"])
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["duplicate"] * 7 + ["new"]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_call_or_read(db, role):
    db.execute(f"SET ROLE {role}")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT public.t_inbox_claim('rest_admin', 1, 'message', 1)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT public.t_inbox_finish('rest_admin', 1, 'done', NULL)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT * FROM public.t_inbox")
    finally:
        db.execute("RESET ROLE")


def test_rls_enabled_on_table(db):
    assert fetch_one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.t_inbox'::regclass") is True


def test_migration_is_repeatable(db):
    from .conftest import sql_path

    claim(db, 1)
    db.execute(sql_path("create_t_inbox.sql").read_text())
    assert fetch_one(db, "SELECT count(*) FROM public.t_inbox") == 1
