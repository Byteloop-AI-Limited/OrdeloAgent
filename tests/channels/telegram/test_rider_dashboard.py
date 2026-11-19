"""/my_jobs and /portal routing through the real rider dispatcher, without Bot API/network calls.

Issuance itself (rider_dashboard_mint, hash and HTTPS origin rules) is covered in tests/ordelo/test_dashboard_links.py.
"""
import pytest
from aiogram.methods import SendMessage
from aiogram.types import Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.rider import dashboard
from channels.telegram.rider.commands import RIDER_COMMANDS, INFLIGHT_COMMANDS, HELP_TEXT
from config.tgram_setting import TgramBotSettings
from ordelo.dashboard_links import Issued, PortalLink

from .conftest import message_update

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token":"654321:TEST-token","tgram_rider_webhook_secret":"abc"})


@pytest.fixture
def issued(monkeypatch):
    calls=[]
    async def issue(portal, actor):
        calls.append((portal, actor.tuid))
        return Issued("ok", (PortalLink("Open my jobs", "https://restaurant.example/rider/activate/secret"),))
    monkeypatch.setattr(dashboard,"issue",issue)
    return calls


async def feed(bot,payload):
    await build_rider_dispatcher(SETTINGS).feed_update(bot,Update.model_validate(payload,context={"bot":bot}))


@pytest.mark.parametrize("command", ["/my_jobs", "/portal"])
async def test_private_link_is_not_in_message_text(recording_bot,issued,command):
    bot,session=recording_bot
    await feed(bot,message_update(f'{command} 447700900999'))
    assert issued==[("rider", 111)]  # arguments never select the principal
    msg=[call for call in session.calls if isinstance(call,SendMessage)][-1]
    assert 'secret' not in msg.text and msg.link_preview_options.is_disabled
    assert msg.reply_markup.inline_keyboard[0][0].url.endswith('/secret')


async def test_groups_cannot_mint(recording_bot,issued):
    bot,session=recording_bot; payload=message_update('/portal')
    payload['message']['chat']={'id':-100,'type':'supergroup','title':'Group'}
    await feed(bot,payload)
    assert issued==[] and session.sent_texts==['Please message me in a private chat.']


async def test_not_linked_and_failure_are_actionable(recording_bot,monkeypatch):
    async def unlinked(portal, actor): return Issued('not_linked')
    monkeypatch.setattr(dashboard,'issue',unlinked)
    bot,session=recording_bot
    await feed(bot,message_update('/my_jobs'))
    assert '/start' in session.sent_texts[-1]
    async def failed(portal, actor): raise RuntimeError('secret URL must not be logged')
    monkeypatch.setattr(dashboard,'issue',failed)
    await feed(bot,message_update('/portal',update_id=2))
    assert 'try /portal again' in session.sent_texts[-1]


def test_available_even_during_delivery():
    for name in ('my_jobs', 'portal'):
        assert all(name in [c.command for c in menu] for menu in (RIDER_COMMANDS,INFLIGHT_COMMANDS))
        assert f'/{name}' in HELP_TEXT
