"""Real HTTP guards: remove arbitrary-phone issuers and authenticate payout report/mutation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Depends
from fastapi import HTTPException

from watomation.routers import rest_admin_auth_session as rest, sys_admin_auth_session as sys


@pytest.fixture
def app():
    app=FastAPI()
    app.include_router(rest.router)
    app.include_router(sys.router)
    return app


async def test_http_issuers_are_removed_and_payout_routes_require_a_session(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test') as client:
        for path in ('/rest-admin/dashboard-session','/sys-admin/dashboard-session','/rider/dashboard-session'):
            assert (await client.post(path,params={'wa_number':'447700900101'})).status_code==404
        assert (await client.get('/sys-admin/rider-payout',params={'start':'2026-10-01'})).status_code==401
        assert (await client.post('/sys-admin/update-paid',json={'dispatch_ids':[1]})).status_code==401


async def test_proxy_credential_is_bound_to_activated_sysadmin_and_ua(app,monkeypatch):
    now=datetime.now(timezone.utc)
    row={'id':'session','principal_id':'447700900101','role':'sys_admin','revoked':False,
         'activated_at':now.isoformat(),'hard_expires_at':(now+timedelta(hours=2)).isoformat(),
         'last_seen_at':now.isoformat(),'bound_ua_hash':sys._sha256_hex('Browser')}
    class Query:
        def select(self,*args): return self
        def eq(self,key,value):
            assert key=='cookie_hash' and value==sys._sha256_hex('cookie')
            return self
        def maybe_single(self): return self
        def execute(self): return SimpleNamespace(data=row)
    monkeypatch.setattr(sys,'client_ordelo_service',SimpleNamespace(table=lambda _:Query()))
    async def allowed(principal): assert principal=='447700900101'
    monkeypatch.setattr(sys,'_ensure_sys_admin',allowed)
    @app.get('/protected',dependencies=[Depends(sys.require_sys_admin)])
    async def protected(): return {'ok':True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test') as client:
        headers={'Authorization':'Bearer cookie','X-Dashboard-User-Agent':'Browser'}
        assert (await client.get('/protected',headers=headers)).status_code==200
        row['role']='rider'
        assert (await client.get('/protected',headers=headers)).status_code==401
        row['role']='sys_admin'; row['revoked']=True
        assert (await client.get('/protected',headers=headers)).status_code==401
        row['revoked']=False; headers['X-Dashboard-User-Agent']='Other browser'
        assert (await client.get('/protected',headers=headers)).status_code==401


async def test_overwatch_removal_is_not_hidden_by_the_alerts_cache(monkeypatch):
    state={'value':'447700900101'}
    class Config:
        def select(self,*args): return self
        def eq(self,*args): return self
        def limit(self,*args): return self
        def execute(self): return SimpleNamespace(data=[{'config_value':state['value']}])
    monkeypatch.setattr(sys,'client_ordelo_service',SimpleNamespace(table=lambda _:Config()))
    assert await sys._ensure_sys_admin('447700900101')=='447700900101'
    state['value']='447700900102'
    with pytest.raises(HTTPException) as error:
        await sys._ensure_sys_admin('447700900101')
    assert error.value.status_code==403
