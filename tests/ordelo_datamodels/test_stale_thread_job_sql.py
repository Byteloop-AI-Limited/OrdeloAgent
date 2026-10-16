import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
JOB_SQL_PATH = (
    REPOSITORY_ROOT
    / "ordelo_datamodels"
    / "agent_threads"
    / "job_terminate_stale_active_threads.sql"
)
INDEX_SQL_PATH = (
    REPOSITORY_ROOT
    / "ordelo_datamodels"
    / "migrations"
    / "add_stale_thread_dispatch_index.sql"
)


def _new_job_definition() -> str:
    """Only the active job's definition: the file also keeps the old, unscheduled job_terminate_stale_active_threads()."""
    text = JOB_SQL_PATH.read_text()
    start = re.search(r"CREATE OR REPLACE FUNCTION (public\.)?job_terminate_stale_active_threads_new\b", text).start()
    nxt = re.search(r"CREATE OR REPLACE FUNCTION", text[start + 10 :])
    return text[start : start + 10 + nxt.start()] if nxt else text[start:]


def test_stale_thread_job_owns_selection_and_dispatch_contract():
    sql = _new_job_definition()

    assert "RETURNS JSONB" in sql
    assert "upper(split_part(t.thread_id, '-', 1))" in sql
    assert "rm.rest_stale_active_threads_minutes" in sql
    assert "c.checkpoint_ns = ''" in sql
    assert "ORDER BY c.checkpoint_id DESC" in sql
    assert "w.retain_thread_value = 'true'::jsonb" in sql
    assert "oc.config_key = s.rest_ref || '_APP_URL'" in sql
    assert "'observed_last_access_dtts'" not in sql
    assert "'observed_checkpoint_id'" not in sql
    assert "|| '/thread-hooks/'" in sql
    assert "|| '/terminate-stale-active-threads'" in sql
    assert "ORDELO_APP_URL" not in sql


def test_stale_thread_job_is_not_invoked_while_loading_definition():
    executable_lines = [
        line.strip().lower()
        for line in JOB_SQL_PATH.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]

    for name in ("job_terminate_stale_active_threads", "job_terminate_stale_active_threads_new"):
        assert f"select {name}();" not in executable_lines
        assert f"select * from {name}();" not in executable_lines


def test_stale_thread_dispatch_index_supports_prefix_and_age_lookup():
    sql = INDEX_SQL_PATH.read_text()

    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in sql
    assert "upper(split_part(thread_id, '-', 1))" in sql
    assert "last_access_dtts" in sql
    assert "WHERE is_active IS TRUE" in sql
