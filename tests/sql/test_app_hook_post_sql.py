"""app_hook_post() (ordelo_datamodels/platform/app_hook_post.sql) on isolated Postgres: URL building, fallback, body, status,
the never-raise contract, the curl timeout set/reset and the grants (ADR 0019)."""

import json

import pytest

from .conftest import fetch_one

pytestmark = pytest.mark.usefixtures("sql_env")


@pytest.fixture(autouse=True)
def clean(db):
    db.execute("TRUNCATE public.http_calls, public.http_curlopts")
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL'")
    yield
    db.execute("UPDATE public.http_stub_status SET status = 200")
    db.execute("DELETE FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL'")


def set_url(db, value):
    db.execute("INSERT INTO public.ordelo_config (config_key, config_value) VALUES ('ORDELO_APP_URL', %s)", (value,))


def post(db, path="/rider-hooks/invite-alerts", payload=None, timeout=None):
    if timeout is None:
        return fetch_one(db, "SELECT public.app_hook_post(%s, %s::jsonb)", (path, json.dumps(payload or {"a": 1})))
    return fetch_one(db, "SELECT public.app_hook_post(%s, %s::jsonb, %s)", (path, json.dumps(payload or {"a": 1}), timeout))


def calls(db):
    return db.execute("SELECT url, body FROM public.http_calls ORDER BY id").fetchall()


@pytest.mark.parametrize("base", ["https://app.example.test", "https://app.example.test/"])
@pytest.mark.parametrize("path", ["/rider-hooks/invite-alerts", "rider-hooks/invite-alerts"])
def test_url_joins_base_and_path_with_one_slash(db, base, path):
    set_url(db, base)
    assert post(db, path) == 200
    assert [c[0] for c in calls(db)] == ["https://app.example.test/rider-hooks/invite-alerts"]   # exactly one POST


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_url_falls_back_to_production(db, value):
    if value is not None:
        set_url(db, value)
    assert post(db) == 200
    assert calls(db)[0][0] == "https://agent.ordelo.app/rider-hooks/invite-alerts"


def test_body_is_the_json_payload(db):
    set_url(db, "https://app.example.test")
    post(db, payload={"event_type": "rider_invite_alerts", "due": 2})
    assert json.loads(calls(db)[0][1]) == {"event_type": "rider_invite_alerts", "due": 2}


@pytest.mark.parametrize("status", [200, 204, 404, 500])
def test_returns_the_status_as_given(db, status):
    set_url(db, "https://app.example.test")
    db.execute("UPDATE public.http_stub_status SET status = %s", (status,))
    assert post(db) == status


def test_a_failed_call_returns_null_and_never_raises(db):
    set_url(db, "https://app.example.test")
    db.execute("UPDATE public.http_stub_status SET status = -1")   # the stub raises
    assert post(db) is None
    # the EXCEPTION block rolls back the stub's own inserts, so nothing is asserted about http_calls here


def test_timeout_is_set_before_the_post_and_reset_after(db):
    set_url(db, "https://app.example.test")
    post(db, timeout=7)
    assert db.execute("SELECT opt, val FROM public.http_curlopts ORDER BY id").fetchall() == [
        ("CURLOPT_TIMEOUT", "7"), ("RESET", None)]


@pytest.mark.parametrize("timeout, expected", [(None, "5"), (0, "1"), (-3, "1")])
def test_timeout_defaults_to_5_and_is_at_least_1(db, timeout, expected):
    set_url(db, "https://app.example.test")
    if timeout is None:
        post(db)
    else:
        db.execute("SELECT public.app_hook_post('/x', '{}'::jsonb, %s)", (timeout,))
    assert fetch_one(db, "SELECT val FROM public.http_curlopts WHERE opt = 'CURLOPT_TIMEOUT'") == expected


def test_null_payload_posts_an_empty_object(db):
    set_url(db, "https://app.example.test")
    assert fetch_one(db, "SELECT public.app_hook_post('/x', NULL)") == 200
    assert calls(db)[0][1] == "{}"


def test_service_role_only(db):
    sig = "public.app_hook_post(text, jsonb, integer)"
    for role in ("anon", "authenticated"):
        assert fetch_one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig)) is False
    assert fetch_one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (sig,)) is True
