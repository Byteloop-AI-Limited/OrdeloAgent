"""/start (with and without invite code), contact verification, admin /invite."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from .. import invites
from ..config import Settings
from ..keyboards import contact_request_kb

router = Router(name="onboarding")

CLAIM_ERRORS = {
    "unknown": "That invite link isn't valid. Ask for a new one.",
    "used": "That invite has already been used by another account.",
    "expired": "That invite has expired. Ask for a new one.",
    "revoked": "That invite was cancelled. Ask for a new one.",
}


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    """`t.me/<bot>?start=<code>` arrives here as '/start <code>' -> command.args == '<code>'."""
    user = message.from_user
    code = command.args

    if code:
        result, row = invites.claim_invite(
            code, user_id=user.id, chat_id=message.chat.id, username=user.username,
            first_name=user.first_name, language_code=user.language_code,
        )
        if result != "ok":
            await message.answer(CLAIM_ERRORS[result])
            return
        await message.answer(
            f"✅ Linked! Hi <b>{escape(user.first_name)}</b>.\n"
            f"Invite for <code>+{row['phone_number']}</code> claimed.\n\n"
            "Optional: tap below to prove this phone is yours (Telegram sends your own number "
            "and we compare it to the invite).",
            reply_markup=contact_request_kb(),
        )
        return

    linked = invites.find_by_telegram_user(user.id)
    if linked:
        await message.answer(f"Welcome back, {escape(user.first_name)}. Try /menu", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("Hi! This is a private test bot. Ask for an invite link, or try /help.")


@router.message(F.contact)
async def on_contact(message: Message):
    contact = message.contact
    # SECURITY: users can forward anyone's contact card. Only trust it if it is THEIR OWN.
    if contact.user_id != message.from_user.id:
        await message.answer("That's someone else's contact. Please use the button to share your own.")
        return
    if invites.mark_phone_verified(message.from_user.id, contact.phone_number):
        await message.answer("📞 Phone verified and matches the invite. Try /menu", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(
            "Your phone doesn't match the number the invite was created for (or you haven't claimed one).",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message):
    """Shows the three different IDs people confuse: user id, chat id, and the Ordelo identity."""
    u, linked = message.from_user, invites.find_by_telegram_user(message.from_user.id)
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        f"Ordelo link: {'+' + linked['phone_number'] + (' ✔ verified' if linked['phone_verified'] else ' (unverified)') if linked else 'not linked'}",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


@router.message(Command("invite"))
async def cmd_invite(message: Message, command: CommandObject, settings: Settings):
    """Admin only: /invite 447700900123  -> creates an invite and replies with the link."""
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorised.")
        return
    if not command.args:
        await message.answer("Usage: /invite &lt;phone number&gt;")
        return
    row = invites.create_invite(command.args, settings.invite_ttl_hours)
    link = invites.invite_link(settings.bot_username, row["invite_code"])
    await message.answer(
        f"Invite for <code>+{row['phone_number']}</code> (valid {settings.invite_ttl_hours}h):\n{link}\n\n"
        "Send this link to them via WhatsApp/SMS."
    )


@router.message(Command("invites"))
async def cmd_invites(message: Message, settings: Settings):
    if message.from_user.id not in settings.admin_ids:
        await message.answer("Not authorised.")
        return
    if not invites.TGRAM_INVITES:
        await message.answer("No invites yet.")
        return
    lines = [
        f"{r['invite_code']} +{r['phone_number']} {r['status']} user={r['telegram_user_id']} chat={r['telegram_chat_id']}"
        for r in invites.TGRAM_INVITES.values()
    ]
    await message.answer("<pre>" + escape("\n".join(lines)) + "</pre>")
