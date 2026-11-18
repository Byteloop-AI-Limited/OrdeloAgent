"""Postcode recovery boundaries, rate limits and grant redaction."""
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from utils_common.web_ordering import order_lookup as lookup, order_access
from utils_common.web_ordering.common import WebError

N = 'SFCS-RIDR-25'


@pytest.fixture
def fakes(monkeypatch):
    count = AsyncMock(return_value=[{'attempts': 1}])
    rpc = AsyncMock(return_value={'orders': []})
    monkeypatch.setattr(lookup, 'query', count)
    monkeypatch.setattr(lookup, 'one', rpc)
    monkeypatch.setattr(order_access, 'issue_status_only', AsyncMock(return_value={N: 'status-token'}))
    monkeypatch.setattr(lookup.customer_order_view, 'get_view', AsyncMock(return_value={
        'display_status': 'rider_assigned', 'page_path': '/town/salisbury/orders/' + N,
        'pickup_time': {'at': '2026-11-17T12:00:00Z', 'is_estimate': False, 'updated': False},
    }))
    return count, rpc


@pytest.mark.parametrize('postcode', [' br6 0ab ', 'BR60AB'])
async def test_find_canonicalises_and_empty_is_success(fakes, postcode):
    count, rpc = fakes
    assert await lookup.find(postcode, 'sfcs', 'visitor') == {'orders': []}
    assert rpc.await_args.args[1] == ('BR6 0AB', 'SFCS', 7, 10)
    for call in count.await_args_list:
        assert len(call.args[1][0]) == 64
        assert 'BR6' not in call.args[1][0]


@pytest.mark.parametrize('postcode,ref', [('BR6', 'SFCS'), ('BR6 0AB', 'ZZZZ')])
async def test_find_rejects_bad_input(fakes, postcode, ref):
    with pytest.raises(WebError) as caught:
        await lookup.find(postcode, ref, 'visitor')
    assert caught.value.status == 400
    fakes[1].assert_not_awaited()


async def test_find_uses_status_view_and_short_lived_grants(fakes):
    fakes[1].return_value = {'orders': [{'order_number': N, 'placed_at': 'now', 'mode': 'delivery', 'can_unlock': True}]}
    result = await lookup.find('SP1 2AB', 'SFCS', 'visitor')
    order_access.issue_status_only.assert_awaited_once_with([N], timedelta(hours=1))
    lookup.customer_order_view.get_view.assert_awaited_once_with(N, 'status_only')
    assert result['orders'][0]['token'] == 'status-token'
    assert result['orders'][0]['display_status'] == 'rider_assigned'
    assert result['orders'][0]['pickup_time']


@pytest.mark.parametrize('attempts', [[{'attempts': 11}], [{'attempts': 1}, {'attempts': 21}]])
async def test_find_rate_limits(fakes, attempts):
    fakes[0].side_effect = [[x] for x in attempts]
    with pytest.raises(WebError) as caught:
        await lookup.find('SP1 2AB', 'SFCS', 'visitor')
    assert caught.value.status == 429
    fakes[1].assert_not_awaited()


async def test_unlock_truncates_house_and_issues_token(fakes):
    fakes[1].return_value = {'outcome': {'result': 'ok', 'expires_at': 'later'}}
    result = await lookup.unlock(N, 'sp12ab', 'a' * 100, 'visitor')
    assert len(result['token']) == 43
    assert result['page_path'] == '/town/salisbury/orders/' + N
    assert fakes[1].await_args.args[1][2] == 'a' * 60
    assert result['token'] not in str(fakes[1].await_args.args[1])


@pytest.mark.parametrize('postcode', ['SP1', 'SP1 2AB'])
async def test_unlock_mismatch_is_always_not_found(fakes, postcode):
    fakes[1].return_value = {'outcome': {'result': 'no_match'}}
    with pytest.raises(WebError) as caught:
        await lookup.unlock(N, postcode, '9', 'visitor')
    assert (caught.value.status, caught.value.body) == (404, {'error': 'not_found'})


async def test_unlock_sixth_order_attempt_is_limited(fakes):
    fakes[0].side_effect = [[{'attempts': 1}], [{'attempts': 6}]]
    with pytest.raises(WebError) as caught:
        await lookup.unlock(N, 'SP1 2AB', '10', 'visitor')
    assert caught.value.status == 429


async def test_status_grants_are_one_batch_insert(monkeypatch):
    run = AsyncMock(return_value=[{'order_number': N}])
    monkeypatch.setattr(order_access, 'query', run)
    tokens = await order_access.issue_status_only([N], timedelta(hours=1))
    sql, params = run.await_args.args
    assert "'status_only'" in sql and 'unnest' in sql and 'least(now()' in sql
    assert params[0] == timedelta(hours=1)
    assert params[2] == [order_access.digest(tokens[N])]
    run.assert_awaited_once()


def test_fingerprint_preserves_pre_lookup_literal():
    from tests.utils_common.web_ordering.test_payment_routing_compatibility import request
    from utils_common.web_ordering.web_checkout import fingerprint
    assert fingerprint(request(), None) == 'ff69390a5497e8b052066bec4d54f3977554a366f687965af268281684ea121d'


@pytest.mark.parametrize('mode,typed,expected', [('delivery', 'BR6 0AB', 'SP1 2AB'), ('collection', ' br60ab ', 'BR6 0AB'), ('collection', None, None)])
async def test_create_persists_authoritative_lookup_postcode(monkeypatch, mode, typed, expected):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from tests.utils_common.web_ordering.test_payment_routing_compatibility import request
    from utils_common.web_ordering import web_checkout as checkout

    class InsertReached(Exception):
        pass

    saved = []

    class Cursor:
        sql = ''

        async def execute(self, sql, params=()):
            self.sql = sql
            if 'INSERT INTO web_order_request(' in sql:
                saved.append((sql, params))
                raise InsertReached()

        async def fetchone(self):
            if 'count(*)' in self.sql:
                return {'n': 0}
            if 'get_next_daily_seq' in self.sql:
                return {'seq': 1}
            return None

    @asynccontextmanager
    async def context(value=None, **kwargs):
        yield value

    cursor = Cursor()
    conn = SimpleNamespace(transaction=lambda: context(), cursor=lambda **kwargs: context(cursor))
    pool = SimpleNamespace(connection=lambda: context(conn))
    monkeypatch.setattr(checkout, 'pg_settings', SimpleNamespace(get_pool=AsyncMock(return_value=pool)))
    monkeypatch.setattr(checkout, 'session', AsyncMock(return_value={'mode': mode, 'rest_ref': 'ELAS', 'postcode': 'SP1 2AB', 'address': {'postcode': 'SP1 2AB', 'latitude': 51, 'longitude': 0}}))
    monkeypatch.setattr(checkout.availability, 'available', AsyncMock(return_value={}))
    monkeypatch.setattr(checkout.availability, 'pricing', AsyncMock(return_value={'minimum_order_value': 0}))
    with pytest.raises(InsertReached):
        await checkout.create(request(lookup_postcode=typed), 'key')
    assert saved[0][1][-1] == expected


async def test_collection_rejects_invalid_postcode_before_database(monkeypatch):
    from tests.utils_common.web_ordering.test_payment_routing_compatibility import request
    from utils_common.web_ordering import web_checkout as checkout
    monkeypatch.setattr(checkout, 'session', AsyncMock(return_value={'mode': 'collection'}))
    with pytest.raises(WebError) as caught:
        await checkout.create(request(lookup_postcode='bad'), 'key')
    assert caught.value.status == 400
