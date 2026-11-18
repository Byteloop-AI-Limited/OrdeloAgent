"""Thin authenticated route contracts for find/unlock."""
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from watomation.routers import web_hooks
from utils_common.web_ordering.common import WebError

KEY = 'k' * 48
HEADERS = {'X-Ordelo-Web-Key': KEY, 'X-Ordelo-Visitor-Hash': 'a' * 64}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('ORDELO_WEB_KEY', KEY)
    monkeypatch.setattr(web_hooks.order_lookup, 'find', AsyncMock(return_value={'orders': []}))
    monkeypatch.setattr(web_hooks.order_lookup, 'unlock', AsyncMock(return_value={'token': 'opaque', 'page_path': '/order'}))
    app = FastAPI()
    app.include_router(web_hooks.router, prefix='/web')

    @app.exception_handler(WebError)
    async def error(request, exc):
        return JSONResponse(exc.body, status_code=exc.status)

    return TestClient(app)


@pytest.mark.parametrize('visitor', [None, 'bad'])
@pytest.mark.parametrize('path,body', [('/web/orders/find', {'postcode': 'SP1 2AB', 'rest_ref': 'SFCS'}), ('/web/orders/SFCS-RIDR-25/unlock', {'postcode': 'SP1 2AB', 'house': '10'})])
def test_visitor_required(client, visitor, path, body):
    headers = {'X-Ordelo-Web-Key': KEY}
    if visitor:
        headers['X-Ordelo-Visitor-Hash'] = visitor
    assert client.post(path, json=body, headers=headers).status_code == 400


def test_key_required(client):
    assert client.post('/web/orders/find', json={'postcode': 'SP1 2AB', 'rest_ref': 'SFCS'}).status_code == 401


@pytest.mark.parametrize('path,body,status', [('/web/orders/find', {'postcode': 'SP1 2AB', 'rest_ref': 'SFCS'}, 200), ('/web/orders/SFCS-RIDR-25/unlock', {'postcode': 'SP1 2AB', 'house': '10'}, 201)])
def test_private_headers(client, path, body, status):
    response = client.post(path, json=body, headers=HEADERS)
    assert response.status_code == status
    for k, v in web_hooks.PRIVATE.items():
        assert response.headers[k] == v


def test_find_does_not_shadow_order_get(client, monkeypatch):
    monkeypatch.setattr(web_hooks.order_access, 'verify', AsyncMock(return_value={'detail_level': 'status_only'}))
    monkeypatch.setattr(web_hooks.customer_order_view, 'get_view', AsyncMock(return_value={'order_number': 'SFCS-RIDR-25'}))
    response = client.get('/web/orders/SFCS-RIDR-25', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['order_number'] == 'SFCS-RIDR-25'
