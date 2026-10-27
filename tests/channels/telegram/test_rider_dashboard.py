"""/my_jobs routing through the real rider dispatcher, without Bot API/network calls."""
from types import SimpleNamespace

import pytest
from aiogram.methods import SendMessage
from aiogram.types import Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.rider import dashboard
from channels.telegram.rider.commands import RIDER_COMMANDS, INFLIGHT_COMMANDS, HELP_TEXT
from config.tgram_setting import TgramBotSettings
from ordelo import rider_dashboard

from .conftest import message_update

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token":"654321:TEST-token","tgram_rider_webhook_secret":"abc"})


@pytest.fixture
def issued(monkeypatch):
    calls=[]
    async def issue(actor):
        calls.append(actor)
        return rider_dashboard.DashboardLink("ok", "https://restaurant.example/rider/activate/secret")
    monkeypatch.setattr(dashboard,"issue_link",issue)
    return calls


async def feed(bot,payload):
    await build_rider_dispatcher(SETTINGS).feed_update(bot,Update.model_validate(payload,context={"bot":bot}))


async def test_private_link_is_not_in_message_text(recording_bot,issued):
    bot,session=recording_bot
    await feed(bot,message_update('/my_jobs 447700900999'))
    assert issued==[111]  # arguments never select the principal
    msg=[call for call in session.calls if isinstance(call,SendMessage)][-1]
    assert 'secret' not in msg.text and msg.link_preview_options.is_disabled
    assert msg.reply_markup.inline_keyboard[0][0].url.endswith('/secret')


async def test_groups_cannot_mint(recording_bot,issued):
    bot,session=recording_bot; payload=message_update('/my_jobs')
    payload['message']['chat']={'id':-100,'type':'supergroup','title':'Group'}
    await feed(bot,payload)
    assert issued==[] and session.sent_texts==['Please message me in a private chat.']


async def test_not_linked_and_failure_are_actionable(recording_bot,monkeypatch):
    async def unlinked(actor): return rider_dashboard.DashboardLink('not_linked')
    monkeypatch.setattr(dashboard,'issue_link',unlinked)
    bot,session=recording_bot
    await feed(bot,message_update('/my_jobs'))
    assert '/start' in session.sent_texts[-1]
    async def failed(actor): raise RuntimeError('secret URL must not be logged')
    monkeypatch.setattr(dashboard,'issue_link',failed)
    await feed(bot,message_update('/my_jobs',update_id=2))
    assert 'try /my_jobs again' in session.sent_texts[-1]


def test_available_even_during_delivery():
    assert all('my_jobs' in [c.command for c in menu] for menu in (RIDER_COMMANDS,INFLIGHT_COMMANDS))
    assert '/my_jobs' in HELP_TEXT


@pytest.mark.parametrize('result',['ok','not_linked'])
async def test_mint_wrapper_uses_hash_and_actor_only(monkeypatch,result):
    calls=[]
    async def base(role): return 'https://restaurant.example'
    def rpc(name,args):
        calls.append((name,args))
        return SimpleNamespace(execute=lambda:SimpleNamespace(data={'result':result}))
    monkeypatch.setattr(rider_dashboard,'get_dashboard_app_url_async',base)
    monkeypatch.setattr(rider_dashboard,'client_ordelo_service',SimpleNamespace(rpc=rpc))
    out=await rider_dashboard.issue_link(111)
    assert out.result==result
    assert calls[0][0]=='rider_dashboard_mint' and calls[0][1]['p_tuid']==111
    assert len(calls[0][1]['p_token_hash'])==64
    assert bool(out.url)==(result=='ok')
    if out.url: assert calls[0][1]['p_token_hash'] not in out.url


async def test_no_insecure_or_unexpected_mint_fallback(monkeypatch):
    async def base(role): return 'http://localhost:3000'
    monkeypatch.setattr(rider_dashboard,'get_dashboard_app_url_async',base)
    with pytest.raises(ValueError): await rider_dashboard.issue_link(111)
