"""Card button taps. Same shape as any other hook: change state, then refresh_order_card()."""
from aiogram import Router
from aiogram.types import CallbackQuery

from .render import STATUS_LINE, CardAction
from .service import refresh_order_card
from .state import apply_action, load_order, save_order

router = Router(name="order_card")


@router.callback_query(CardAction.filter())
async def on_card_action(query: CallbackQuery, callback_data: CardAction):
    state = await load_order(callback_data.ref)
    if state is None:
        await query.answer("Order not found.", show_alert=True)
        return
    new = apply_action(state, callback_data.act, actor=query.from_user.first_name)
    if new is None:
        # Stale tap (another admin acted first, or a hook moved the order on). Re-render so the
        # outdated buttons disappear from this copy too.
        status = STATUS_LINE[state.status].replace("<b>", "").replace("</b>", "")
        await query.answer(f"Already updated: {status}", show_alert=True)
        await refresh_order_card(query.bot, state.ref)
        return
    await save_order(new)
    await query.answer("Done")  # stops the spinner; the card edit below is the real confirmation
    notify = "⚠️ Problem reported - Ordelo support will call you." if callback_data.act == "iss" else None
    await refresh_order_card(query.bot, new.ref, notify=notify)
