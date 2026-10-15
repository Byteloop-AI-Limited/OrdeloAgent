"""Restaurant order card: ONE Telegram message per admin that shows an order and is edited as it moves.

Reference shape for the real Ordelo implementation. The rule that keeps it simple:

    the card is a pure function of the order's CURRENT state, never of the event that just happened.

Every code path that changes an order (delivery hooks, button taps, cron jobs) does the same two things:

    1. update the order state (state.py; real code: the DB)
    2. await refresh_order_card(bot, order_ref)        (service.py: load -> render -> edit every copy)

Nobody outside render.py builds card text, so hooks spread across files never touch HTML.

    state.py    OrderCardState + allowed transitions (restaurant actions, delivery events). ORDERS = fake DB.
    render.py   render_text / render_buttons: pure, no I/O, snapshot-testable. CardAction callback data.
    service.py  send_order_card / refresh_order_card: the only code that calls Telegram. Message-id store.
    handlers.py aiogram router for card button taps (an example "hook" that changes state).
    demo_api.py FastAPI endpoints that stand in for delivery hooks (rider assigned, picked up, ...).
"""
