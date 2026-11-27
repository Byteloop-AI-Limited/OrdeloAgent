"""Phase 2 pg_cron jobs on isolated Postgres (ADR 0019, option B in docs/to-do.md):
notifications/job_customer_outbox_sweep.sql, ordering/job_web_lifecycle_sweep.sql and ordering/job_web_price_audit.sql.

Each job POSTs exactly once per run through app_hook_post() (a second POST would mean the status was evaluated twice,
e.g. by `app_hook_post(...) BETWEEN ...`), returns true only on 2xx and never raises. The curl timeout is set and then
reset around the one call. Grants are service role only, and each file schedules the agreed cron string.
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
    ("job_web_price_audit", "job_web_price_audit.sql", "/web-hooks/price-audit", "web_price_audit", "5 0 * * *"),
]
IDS = [j[0] for j in JOBS]


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.http_calls, public.http_curlopts")
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('ORDELO_APP_URL', %s) "
               "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value", (BASE,))
    yield
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


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_job_posts_every_run_even_with_nothing_due(db, fn, file, path, event, schedule):
    # option B: no due check in SQL, the Python sweep decides
    assert run(db, fn) is True and run(db, fn) is True
    assert [u for u, _ in posts(db)] == [BASE + path, BASE + path]


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
    # the catalog annotation must say the job is not live yet
    assert re.search(rf"^-- pg_cron job '{fn}': runs every .+, INACTIVE on live\b", text, re.M)
    row = db.execute("SELECT schedule, command FROM cron.job WHERE jobname = %s", (fn,)).fetchone()
    assert row == (schedule, f"SELECT public.{fn}()")


@pytest.mark.parametrize("fn, file, path, event, schedule", JOBS, ids=IDS)
def test_no_between_on_the_volatile_call(db, fn, file, path, event, schedule):
    code = re.sub(r"--[^\n]*", "", sql_path(file).read_text())   # comments quote the forbidden form on purpose
    assert "app_hook_post" in code
    assert not re.search(r"app_hook_post\s*\([^;]*?\)\s*BETWEEN", code, re.S)
