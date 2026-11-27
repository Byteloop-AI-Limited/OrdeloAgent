"""Phase 2 pg_cron jobs on isolated Postgres (ADR 0019, option B in docs/to-do.md):
notifications/job_customer_outbox_sweep.sql, ordering/job_web_lifecycle_sweep.sql and ordering/job_web_price_audit.sql.

Each job POSTs at most once per run through app_hook_post() (a second POST would mean the status was evaluated twice,
e.g. by `app_hook_post(...) BETWEEN ...`), returns false on non-2xx and never raises. The curl timeout is set and then
reset around the one call. Grants are service role only, and each file schedules the agreed cron string.

The outbox and lifecycle jobs POST every run (option B). The price audit runs hourly and POSTs only when web_monitor_run
has no row for today's London date (owner decision, 27 Nov 2026).

Limit: now() cannot be frozen in this harness (it is the transaction start time and the job's search_path resolves
pg_catalog.now first). The London-date tests therefore set the session TimeZone to zones whose current_date differs from
London's, which proves the job keys on (now() AT TIME ZONE 'Europe/London')::date and not on the session or UTC date.
The real 23:00-00:00 UTC BST window is not replayed.
"""

import json
import re

import pytest

from .conftest import fetch_one, sql_path

pytestmark = pytest.mark.usefixtures("sql_env")

BASE = "https://app.example.test"

# (function, file, hook path, event_type, cron schedule)
JOBS = [
    ("job_customer_outbox_sweep", "job_customer_outbox_sweep.sql", "/customer-hooks/outbox-sweep", "customer_outbox_sweep", "* * * * *"),
    ("job_web_lifecycle_sweep", "job_web_lifecycle_sweep.sql", "/web-hooks/lifecycle-sweep", "web_lifecycle_sweep", "* * * * *"),
    ("job_web_price_audit", "job_web_price_audit.sql", "/web-hooks/price-audit", "web_price_audit", "5 * * * *"),
]
IDS = [j[0] for j in JOBS]
# option B jobs: no due check in SQL, they POST on every run
ALWAYS_POST = [j for j in JOBS if j[0] != "job_web_price_audit"]
LONDON_TODAY = "(now() AT TIME ZONE 'Europe/London')::date"


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.http_calls, public.http_curlopts, public.web_monitor_run")
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('ORDELO_APP_URL', %s) "
               "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value", (BASE,))
    yield
    db.execute("RESET TimeZone")
    db.execute("TRUNCATE public.web_monitor_run")
    db.execute("UPDATE public.http_stub_status SET status = 200")
    # later files (test_order_cards_sql.py) expect the production fallback URL, so leave no ORDELO_APP_URL behind
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL'")


def run(db, fn):
    return fetch_one(db, f"SELECT public.{fn}()")


def posts(db):
    return db.execute("SELECT url, body FROM public.http_calls ORDER BY id").fetchall()


def curlopts(db):
    return db.execute("SELECT opt, val FROM public.http_curlopts ORDER BY id").fetchall()


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
@pytest.mark.parametrize("status", [200, 204])
def test_job_posts_exactly_once_to_its_hook_and_returns_true_on_2xx(db, fn, file, path, event, schedule, status):
    db.execute("UPDATE public.http_stub_status SET status = %s", (status,))
    assert run(db, fn) is True
    rows = posts(db)
    assert len(rows) == 1, f"{fn} must POST exactly once per run, got {len(rows)}"
    url, body = rows[0]
    assert url == BASE + path
    assert json.loads(body) == {"event_type": event}
    # the timeout is set for this one call and reset afterwards (curlopts are session state)
    assert curlopts(db) == [("CURLOPT_TIMEOUT", "5"), ("RESET", None)]


@pytest.mark.parametrize("fn, file, path, event, schedule", ALWAYS_POST, ids=[j[0] for j in ALWAYS_POST])
def test_job_posts_every_run_even_with_nothing_due(db, fn, file, path, event, schedule):
    # option B: no due check in SQL, the Python sweep decides
    assert run(db, fn) is True and run(db, fn) is True
    assert [u for u, _ in posts(db)] == [BASE + path, BASE + path]


def test_price_audit_posts_once_when_todays_london_row_is_missing(db):
    db.execute("INSERT INTO public.web_monitor_run (run_day, completed_at) "
               f"VALUES ({LONDON_TODAY} - 1, now())")   # yesterday's finished audit does not count
    assert run(db, "job_web_price_audit") is True
    assert [u for u, _ in posts(db)] == [BASE + "/web-hooks/price-audit"]


@pytest.mark.parametrize("completed", [True, False], ids=["completed", "claimed"])
def test_price_audit_skips_without_posting_when_todays_london_row_exists(db, completed):
    # a finished audit, or a claim still running (or left by a crash): either way the hour's run does not call the app
    db.execute("INSERT INTO public.web_monitor_run (run_day, completed_at) "
               f"VALUES ({LONDON_TODAY}, CASE WHEN %s THEN now() END)", (completed,))
    db.execute("UPDATE public.http_stub_status SET status = 500")   # would make a POST return false
    assert run(db, "job_web_price_audit") is True
    assert posts(db) == [] and curlopts(db) == []


def test_price_audit_posts_again_after_a_failed_audit_deleted_its_claim(db):
    db.execute(f"INSERT INTO public.web_monitor_run (run_day) VALUES ({LONDON_TODAY})")
    assert run(db, "job_web_price_audit") is True and posts(db) == []
    # monitoring.sweep()'s except branch: DELETE ... WHERE run_day = day AND completed_at IS NULL
    db.execute(f"DELETE FROM public.web_monitor_run WHERE run_day = {LONDON_TODAY} AND completed_at IS NULL")
    assert run(db, "job_web_price_audit") is True
    assert len(posts(db)) == 1


# UTC+14 and UTC-12: at any instant at least one of them is on a different calendar date from London (UTC+0/+1).
@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "Etc/GMT+12"])
def test_price_audit_keys_on_the_london_date_not_the_session_date(db, zone):
    db.execute(f"SET TimeZone = '{zone}'")
    london, session = db.execute(f"SELECT {LONDON_TODAY}, current_date").fetchone()
    if london == session:
        pytest.skip(f"{zone} is on London's date at this instant; the other zone covers it")
    # a row for the session's date (across midnight from London) is not today's audit: the job POSTs
    db.execute("INSERT INTO public.web_monitor_run (run_day) VALUES (current_date)")
    assert run(db, "job_web_price_audit") is True
    assert len(posts(db)) == 1
    # a row for London's date is: the job skips
    db.execute(f"INSERT INTO public.web_monitor_run (run_day) VALUES ({LONDON_TODAY})")
    assert run(db, "job_web_price_audit") is True
    assert len(posts(db)) == 1


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_job_returns_false_on_500_after_one_post(db, fn, file, path, event, schedule):
    db.execute("UPDATE public.http_stub_status SET status = 500")
    assert run(db, fn) is False
    assert len(posts(db)) == 1   # read once: a second evaluation of the status would POST twice


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_job_returns_false_when_the_call_raises_and_does_not_raise(db, fn, file, path, event, schedule):
    db.execute("UPDATE public.http_stub_status SET status = -1")   # the http stub raises
    assert run(db, fn) is False
    # app_hook_post's EXCEPTION block rolls back the stub's insert and the timeout row; its handler's RESET survives.
    # Exactly one RESET means exactly one attempt.
    assert posts(db) == []
    assert curlopts(db) == [("RESET", None)]


@pytest.mark.parametrize("fn", IDS)
def test_service_role_only(db, fn):
    sig = f"public.{fn}()"
    for role in ("anon", "authenticated"):
        assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig)) is False
    assert fetch_one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,)) is True


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_file_schedules_the_agreed_cron_string(db, fn, file, path, event, schedule):
    text = sql_path(file).read_text()
    calls = re.findall(r"^SELECT cron\.schedule\('([^']+)', '([^']+)', '([^']+)'\);$", text, re.M)
    assert calls == [(fn, schedule, f"SELECT public.{fn}()")]
    row = db.execute("SELECT schedule, command FROM cron.job WHERE jobname = %s", (fn,)).fetchone()
    assert row == (schedule, f"SELECT public.{fn}()")


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_no_between_on_the_volatile_call(db, fn, file, path, event, schedule):
    code = re.sub(r"--[^\n]*", "", sql_path(file).read_text())   # comments quote the forbidden form on purpose
    assert "app_hook_post" in code
    assert not re.search(r"app_hook_post\s*\([^;]*?\)\s*BETWEEN", code, re.S)
