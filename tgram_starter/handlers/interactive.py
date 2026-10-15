"""Inline-keyboard callbacks: the equivalent of WhatsApp reply buttons."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..config import Settings
from ..keyboards import Counter, DemoOrder, contact_request_kb, counter_kb, location_request_kb, main_menu, order_offer

router = Router(name="interactive")

# Fake domain state so stale/duplicate taps can be demonstrated. Real code reloads from the DB.
ORDER_STATE: dict[int, str] = {}  # order_id -> offered | accepted | declined


@router.message(Command("menu"))
async def cmd_menu(message: Message, settings: Settings):
    await message.answer("<b>Demo menu</b>\nPick a feature:", reply_markup=main_menu(settings.miniapp_url))


@router.callback_query(F.data == "demo:menu")
async def cb_menu(query: CallbackQuery, settings: Settings):
    await query.answer()
    await query.message.edit_text("<b>Demo menu</b>\nPick a feature:", reply_markup=main_menu(settings.miniapp_url))


@router.callback_query(F.data == "demo:order")
async def cb_order(query: CallbackQuery):
    await query.answer()
    order_id = 1000 + len(ORDER_STATE)
    ORDER_STATE[order_id] = "offered"
    await query.message.answer(
        f"🛵 <b>New delivery #{order_id}</b>\nPickup: Demo Kitchen\nDrop: 1 Test Street", reply_markup=order_offer(order_id)
    )


@router.callback_query(DemoOrder.filter())
async def cb_order_action(query: CallbackQuery, callback_data: DemoOrder):
    state = ORDER_STATE.get(callback_data.order_id)
    # ALWAYS answer the callback, even for stale taps, or the button spinner hangs.
    if state != "offered":
        await query.answer(f"Already {state or 'unknown'} - ignoring.", show_alert=True)
        return
    ORDER_STATE[callback_data.order_id] = "accepted" if callback_data.action == "a" else "declined"
    await query.answer("Recorded")  # spinner off; this is NOT the business confirmation
    verdict = "✅ Accepted" if callback_data.action == "a" else "❌ Declined"
    # Edit the original message: removes the buttons so they can't be tapped twice.
    await query.message.edit_text(f"{query.message.html_text}\n\n<b>{verdict}</b> by {query.from_user.first_name}", reply_markup=None)


@router.callback_query(Counter.filter())
async def cb_counter(query: CallbackQuery, callback_data: Counter):
    value = callback_data.value + callback_data.delta
    await query.answer()
    if callback_data.delta == 0 and query.message.reply_markup and callback_data.value != 0:
        return  # tapping the number does nothing
    await query.message.edit_text(f"Counter: <b>{value}</b>\n(this message is edited in place)", reply_markup=counter_kb(value))


@router.callback_query(F.data == "demo:location")
async def cb_location(query: CallbackQuery):
    await query.answer()
    await query.message.answer("Tap the button to share your location.", reply_markup=location_request_kb())


@router.callback_query(F.data == "demo:contact")
async def cb_contact(query: CallbackQuery):
    await query.answer()
    await query.message.answer("Tap the button to share your phone number.", reply_markup=contact_request_kb())


@router.callback_query(F.data == "demo:photo")
async def cb_photo(query: CallbackQuery):
    await query.answer("Sending...")
    # Minimal valid 1x1 PNG so the demo needs no files; use FSInputFile(path) or a URL/file_id normally.
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    await query.message.answer_photo(BufferedInputFile(png, "demo.png"), caption="A <b>photo</b> with a caption")
    await query.message.answer_document(BufferedInputFile(b"hello from the bot\n", "hello.txt"), caption="...and a document")
