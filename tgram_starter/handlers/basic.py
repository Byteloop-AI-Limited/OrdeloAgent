"""Plain chat: commands, formatting, typing indicator, location receipt, echo fallback.
Register this router LAST - the generic text handler would swallow everything else."""
import asyncio
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

router = Router(name="basic")

HELP = """<b>Commands</b>
/start - greet (or claim an invite via link)
/menu - inline buttons demo
/whoami - show user id / chat id / link status
/format - HTML formatting sample
/typing - 'typing...' indicator then a reply
/invite &lt;phone&gt; - admin: create invite link
/invites - admin: list invites

Or just send text, a location, a photo, or a voice note."""


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@router.message(Command("format"))
async def cmd_format(message: Message):
    await message.answer(
        "<b>bold</b> <i>italic</i> <u>underline</u> <s>strike</s> <code>code</code>\n"
        '<a href="https://core.telegram.org/bots/api">link</a> <tg-spoiler>spoiler</tg-spoiler>\n'
        "<blockquote>quote</blockquote>\n"
        "User text must be escaped: " + escape("<script>&</script>")
    )


@router.message(Command("typing"))
async def cmd_typing(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await asyncio.sleep(2)
    # reply_to links the response to the user's message
    await message.reply("Done thinking 🤔")


@router.message(F.location)
async def on_location(message: Message):
    loc = message.location
    await message.answer(
        f"📍 Got it: <code>{loc.latitude:.5f}, {loc.longitude:.5f}</code>"
        + (f" (±{loc.horizontal_accuracy:.0f}m)" if loc.horizontal_accuracy else "")
        + "\nShare a <i>live</i> location (📎 > Location > Share Live) and I'll log every update.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.edited_message(F.location)
async def on_live_location_update(message: Message):
    """Live-location updates arrive as EDITED messages, not new ones. No reply (would spam)."""
    loc = message.location
    print(f"[live] user={message.from_user.id} {loc.latitude:.5f},{loc.longitude:.5f}")


@router.message(F.photo | F.voice | F.document)
async def on_media(message: Message):
    kind = "photo" if message.photo else "voice" if message.voice else "document"
    # Files are fetched later with bot.download(...) using file_id; here we only acknowledge.
    await message.answer(f"Received a {kind}. (file_id is in the update; use bot.download to fetch it)")


@router.message(F.text & ~F.text.startswith("/"))
async def echo(message: Message):
    await message.answer(f"You said: <i>{escape(message.text)}</i>\nTry /menu or /help")
