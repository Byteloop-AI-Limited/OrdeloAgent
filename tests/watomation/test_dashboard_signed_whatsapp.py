"""Dashboard WhatsApp issuers require authentic Meta ingress, not a forged sender payload."""
import hashlib
import hmac
from unittest.mock import AsyncMock

import httpx


async def test_only_signed_meta_payloads_reach_whatsapp_handlers(monkeypatch):
    from config import waba_business_settings
    monkeypatch.setattr(waba_business_settings,'private_key_base64','dGVzdA==')
    from watomation.fapp_ordelo_agent import app, wa

    called=AsyncMock()
    monkeypatch.setattr(wa,'_call_handlers',called)
    body=b'{"object":"whatsapp_business_account","entry":[]}'
    signature='sha256='+hmac.new(waba_business_settings.app_secret.encode(),body,hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test') as client:
        missing=await client.post('/',content=body)
        assert missing.status_code in (401,422)  # FastAPI may reject its required signature header before PyWa
        called.assert_not_awaited()
        forged=await client.post('/',content=body,headers={'X-Hub-Signature-256':'sha256='+'0'*64})
        assert 'Unmatching signature' in forged.text  # PyWa acknowledges discarded payloads with 200
        called.assert_not_awaited()
        accepted=await client.post('/',content=body,headers={'X-Hub-Signature-256':signature})
        assert accepted.status_code==200
        called.assert_awaited_once()
