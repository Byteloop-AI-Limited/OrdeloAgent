"""Real find/unlock RPCs, on the skill's disposable local PostgreSQL cluster."""
import secrets
from datetime import timedelta
import pytest
from psycopg.types.json import Jsonb


@pytest.fixture
def orders(db):
    # Each case rolls back its own rows; unrelated SQL suites keep their fixtures.
    db.execute('BEGIN')
    db.execute("INSERT INTO thread(thread_id,agent) VALUES ('lookup-test','WEB')")
    yield db
    db.execute('ROLLBACK')


def add(db, n='SFCS-TEST-1', *, pc='SP1 2AB', house='12A', building=None,
        flat=None, days=0, action='delivery', origin='web'):
    db.execute("""INSERT INTO food_order(order_id,order_number,origin_channel,action,order_dtts)
               VALUES (%s,%s,%s,%s,now()-%s * interval '1 day')""", (n, n, origin, action, days))
    db.execute("""INSERT INTO web_order_request(idempotency_key,thread_id,body_hash,order_number,address,lookup_postcode)
               VALUES (%s,'lookup-test','hash',%s,%s,%s)""",
               (n, n, Jsonb({'house_number': house, 'building': building, 'flat': flat}), pc))


def find(db):
    return db.execute("SELECT web_order_lookup('SP1 2AB','SFCS')").fetchone()[0]


def unlock(db, n='SFCS-TEST-1', pc='SP1 2AB', house='12a'):
    return db.execute('SELECT web_order_unlock(%s,%s,%s,%s)', (n, pc, house, secrets.token_bytes(32))).fetchone()[0]


def test_find_boundary_restaurant_channel_null_and_limit(orders):
    add(orders, 'SFCS-TEST-100', days=7)
    add(orders, 'ELAS-TEST-1')
    add(orders, 'SFCS-TEST-101', origin='whatsapp')
    add(orders, 'SFCS-TEST-102', pc=None)
    for i in range(12):
        add(orders, f'SFCS-TEST-{i}', days=i / 10)
    rows = find(orders)
    assert len(rows) == 10
    assert [r['order_number'] for r in rows] == [f'SFCS-TEST-{i}' for i in range(10)]


@pytest.mark.parametrize('house,building,flat,action,expected', [
    ('12A', None, None, 'delivery', True),
    (None, 'Rose Cottage', None, 'delivery', True),
    (None, None, 'Flat 3', 'delivery', False),
    ('12A', None, None, 'collection', False),
])
def test_can_unlock(orders, house, building, flat, action, expected):
    add(orders, house=house, building=building, flat=flat, action=action)
    assert find(orders)[0]['can_unlock'] is expected


@pytest.mark.parametrize('house,building,typed', [('12A', None, ' 12a '), (None, 'Rose Cottage', 'rose-cottage')])
def test_unlock_inserts_one_recovered_grant(orders, house, building, typed):
    add(orders, house=house, building=building)
    result = unlock(orders, house=typed)
    assert result['result'] == 'ok'
    grant = orders.execute("SELECT detail_level,expires_at FROM order_access_grant WHERE order_number='SFCS-TEST-1'").fetchall()
    assert len(grant) == 1 and grant[0][0] == 'recovered'
    placed = orders.execute("SELECT order_dtts FROM food_order WHERE order_number='SFCS-TEST-1'").fetchone()[0]
    assert grant[0][1] == placed + timedelta(days=30)


@pytest.mark.parametrize('attrs,pc,house', [
    ({'house': None, 'flat': '3'}, 'SP1 2AB', '3'),
    ({}, 'SP2 2AB', '12a'),
    ({'action': 'collection'}, 'SP1 2AB', '12a'),
    ({'days': 7}, 'SP1 2AB', '12a'),
    ({'origin': 'whatsapp'}, 'SP1 2AB', '12a'),
    ({}, 'SP1 2AB', '9'),
])
def test_unlock_refusals_do_not_insert(orders, attrs, pc, house):
    add(orders, **attrs)
    assert unlock(orders, pc=pc, house=house) == {'result': 'no_match'}
    assert orders.execute("SELECT count(*) FROM order_access_grant WHERE order_number='SFCS-TEST-1'").fetchone()[0] == 0


def test_postcode_constraint(orders):
    with pytest.raises(Exception, match='web_order_request_lookup_postcode_format'):
        add(orders, pc='br60ab')


def test_detail_constraint(orders):
    add(orders)
    with pytest.raises(Exception, match='order_access_grant_detail_level_check'):
        orders.execute("""INSERT INTO order_access_grant(order_number,kind,secret_hash,detail_level,expires_at)
                      VALUES ('SFCS-TEST-1','page_token',%s,'other',now()+interval '1 hour')""", (secrets.token_bytes(32),))
