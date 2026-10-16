# Telegram restaurant-admin bot — plan

**Repository:** `OrdeloAgent`. **Last updated:** 15 October 2026 (second grilling session).
**Living overview of what exists:** [`docs/telegram-layer.md`](../docs/telegram-layer.md) (+ [interactive companion](../docs/telegram-layer.html)).
**Related requirements:** project doc `claude/restaurant-admin-attention-requirements.md` (R1–R3, WhatsApp side).
This plan implements R1-a (terminal decline) and a Telegram channel for order confirmation; it does **not**
implement R1 auto-decline, R2 or R3.

| Phase | What | Status |
|---|---|---|
| 1 | Scaffold: settings, registry, webhook, restaurant-admin bot, invite onboarding (`t_invites`) | ✅ **Done** (commit `8d26ed3` on `dev`; verified live by the owner on 15 Oct: `/start`, claim, DB, deployed pod) |
| 2 | Durable inbox (`t_inbox`), dedupe Telegram retries | ✅ Implemented 15 Oct; verified offline + isolated DB; **awaiting operator: run `create_t_inbox.sql`** |
| 3 | Shared restaurant decision functions + R1-a terminal decline for delivery; WhatsApp switched to them | ✅ Implemented 15 Oct; verified offline + isolated DB; **awaiting operator: run `restaurant_order_decision.sql`** (changes the live status CHECK) |
| 4 | Telegram order cards: `OrderCards.remind` / `refresh` (0/15/30/45 s, one copy per chat, cards follow the order), ledger, housekeeping | ✅ Implemented 15 Oct; verified offline + isolated DB; **awaiting operator: run `create_t_order_alerts.sql`, deploy, then `cron.schedule`** |
| 5 | Telegram actions: `OrderCards.tap` (Accept, Decline, pickup time) | ✅ Implemented 15 Oct; verified offline + isolated DB; **awaiting operator: re-run `restaurant_order_decision.sql`** |
| 6 | Verification loop (`telegram-vertification-loop` skill) after each phase and at the end | 🟡 Offline + isolated-DB layers done for phases 2–5; **live Telegram evidence not collected** (needs the operator steps and a real tap) |
| — | Restaurant group chat (D27) | Later; designed not to be blocked |
| — | Rider bot | Later (not in this plan) |

---

## Resume here (next session)

You are implementing phases 2 → 5 in order, running the Phase 6 verification loop at the end of each. Each phase
is shippable on its own; **run each phase's migration before deploying its code**.

**Current state (15 Oct 2026, 14:45 BST)**
- Branch `dev`, HEAD `883dac1` (merge of PR #73) includes commit `8d26ed3` with all of phase 1. Working tree:
  this plan file modified; untracked `.claude/settings.local.json` (not ours; never commit it).
- Live database: `t_invites`, `t_invites_shareable`, `t_invite_preview`, `t_claim_invite`,
  `t_linked_restaurants` exist. `ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME = OrdeloRestaurantBot`.
  The owner has a claimed ELAS invite.
- Live bot: `@OrdeloRestaurantBot`, AWS keys `tgram_rest_admin_*` set; the service refuses to start without
  token and webhook secret (`config/tgram_setting.py`).
- Live pg_cron (verified 15 Oct): `process_restaurant_confirmation` every **10 seconds**, `process_delivery`,
  `job_create_dispatch`, `job_assign_dispatch` every 5 seconds, `job_rider_pickup_alert` every 5 minutes.
  Extensions `pg_cron`, `pg_net`, `http` are installed (sub-minute schedules like `'5 seconds'` work).
- Full test suite: 686 passed, **1 pre-existing failure** (`tests/ordelo_datamodels/test_master_pymodels.py::
  test_restaurant_master_get_admins_fetches_live_column`, fails on a clean checkout too; not ours).

**Done since the scaffold (all on `dev`, all verified)**
- [x] Invite onboarding (`t_invites`, three RPCs, `channels/telegram/invites.py`), claimed live by the owner.
- [x] `client_ordelo_service` for service-only RPCs (`config/pg_setting.py`); anon key denied by design.
- [x] Fail-fast Telegram settings; dedicated bot `@OrdeloRestaurantBot`; `ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME` updated.
- [x] `tgram_` → `t_` rename of the invite objects (cleanup script was run, then removed from the repo).
- [x] Webhook timing log (`delivery_lag`, `handled_ms`) in `watomation/routers/telegram_webhook.py`.
- [x] `docs/telegram-layer.md` + `.html`; RPC cross-reference rule in `CLAUDE.md` and `agents.md`.
- [x] database-operations skill: invite SOP, anon-first client rule, no deletes without approval.
- [ ] Phases 2–5 below: nothing started (verified 15 Oct 14:40: no inbox, decision or order-card code or SQL in the repo).

**Read first (in this order)**
1. This file, sections "Agreed decisions" and "Architecture" (especially "The order card").
2. `CLAUDE.md` → "Database-backed logic: RPC pattern and cross-references" (rules you must follow) and the
   `asyncio.to_thread` rule for the synchronous Supabase client.
3. `docs/telegram-layer.md` (what exists, file map, cross-reference table).
4. Reference implementation of the pattern: `ordelo_datamodels/migrations/create_t_invites.sql` +
   `channels/telegram/invites.py` + `tests/channels/telegram/conftest.py` (`FakeInviteDb`).
5. Reference for the sweep pattern: `ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql`
   (header lines 1–100, POST + mark-on-2xx lines 340–470).
6. Reference for order-card edits: `notebooks/telegram/tgram_scratchpad.py` cells 5c (live edit with
   `edit_with_backoff`, lines 77–117) and 5d (restaurant order card, lines 121–209).

**Commands (owner's Mac)**
- Tests: `source .venv/bin/activate && pytest -q` (focused: `pytest tests/channels tests/watomation/routers/test_telegram_webhook.py -q`).
- Lint: `ruff check .` (F rules only).
- SQL syntax check without a database: `python -c "import pglast; pglast.parse_sql(open(F).read())"`.

**Rules that bite**
- Every new RPC: defined in the migration next to its table, `REVOKE ALL ... FROM PUBLIC, anon, authenticated`,
  called with `client_ordelo_service`, wrapped by one Python module whose docstring names the SQL file and maps
  each function → RPC; the SQL header names the Python callers. Update `docs/telegram-layer.md` §6 + change log
  and the `XREF`/`FILES`/`CHANGELOG` arrays in `docs/telegram-layer.html` in the same change.
- The app never calls `set_webhook`/`delete_webhook`. `allowed_updates` stays `['callback_query', 'message']`.
- Agents must not run `DELETE` without explicit approval (database-operations skill). The housekeeping job is the
  owner-scheduled exception.
- Gunicorn runs up to 3 workers: no in-process state; every "first one wins" is decided in SQL.
- **Verify every phase** with the `telegram-vertification-loop` skill (Phase 6): label evidence offline / isolated
  database / live Telegram; never test SQL against the shared database.
- **Group-ready (D27):** authorise by `from_user.id` only, address by `tcid`, no private-chat assumptions in order code.

---

## Agreed decisions (grilling session 2, 15 Oct 2026)

| # | Decision |
|---|---|
| D11 | **Parallel channels.** Linked admins get Telegram alerts **and** the existing single WhatsApp message (`_handle_restaurant_unconfirmed`, `watomation/routers/delivery_hooks.py:1253`; takeaway `takeaway_hooks.py:151`). The first decision on either channel wins. WhatsApp behaviour is unchanged apart from D17/D18. |
| D12 | **Reminders only.** Telegram alerts at **0, 15, 30, 45 s** after order creation (`*_summary.dtts`), then stop. No answer → the existing timeout auto-accept (`process_restaurant_confirmation()`, `_handle_restaurant_timedout`) still decides. R1 auto-decline is out of scope. |
| D13 | **Database schedules the reminders**: a pg_cron sweep every 5 s with checkpoint rows (`pending`/`sent`/`superseded`), the `rider_pickup_alert` pattern. |
| D14 | **Who may receive and act:** a `claimed` `t_invites` row for that `rest_ref` (bot `rest_admin`) **and** that invite's `phone_number` in `restaurant_master.admins`. Checked at every send and every tap, in SQL. Formats already match (12 digits, no `+`, verified 15 Oct). |
| D15 | **Buttons: Accept and Decline** on Telegram. **R1-a is fixed here**: a delivery decline sets `delivery_summary.status = 'declined'` atomically with the decision (the live CHECK `delivery_summary_status_check` lacks `'declined'`; the migration adds it), cancels payment, and tells the customer. |
| D16 | **Customer on delivery decline: mirror takeaway** (`takeaway_hooks._handle_restaurant_decline`, `takeaway_hooks.py:213-262`): `cancel_payment` unless `pay_at_rest`; web: `queue_release` fallback + `restaurant_declined` customer event; WhatsApp customer: direct text from Ordelo's number. ADR-0006 routing stays an R1 follow-up. |
| D17 | **WhatsApp Decline button stays commented out** (`utils_common/waba_utils/wa_senders.py`, `send_restaurant_order_confirmation`). Decline is Telegram-only. |
| D18 | **One SQL function decides**: `restaurant_order_decide(...)`, used by WhatsApp and Telegram. Losing taps are handled gracefully in Python as today (reply naming who decided). |
| D19 | **"by X"** = the Telegram first name of that phone's claimed invite, else `…` + last 4 digits. Resolved in SQL (`restaurant_admin_label`). |
| D20 | **Pickup time on Telegram:** the accepter's own alert is edited in place into the pickup buttons (order time + 5/15/25 min, WhatsApp parity). Shared SQL function `restaurant_order_set_pickup(...)`. WhatsApp pickup buttons still go to all WhatsApp admins (`_handle_restaurant_accept`, `delivery_hooks.py:1305`). |
| D21 | **Inbox = claim first, skip duplicates** (at-most-once). Row states `processing → done | failed`. |
| D22 | **Housekeeping:** daily `t_housekeeping()` deletes inbox rows older than 7 days and ledger/checkpoint rows closed more than 30 days ago. Periods in `ordelo_config` (`TGRAM_INBOX_RETENTION_DAYS`, `TGRAM_LEDGER_RETENTION_DAYS`). `t_invites` is never purged. |
| D23 | **Scope:** delivery **and** takeaway orders starting as `restaurant_unconfirmed`. No per-restaurant switch: a restaurant gets Telegram alerts once it has ≥1 admin satisfying D14. Configured auto-accept orders never alert. |
| D24 | **Repeat = new message, then delete the previous one** in that chat (so the phone notifies). The **database is authoritative and is checked before every send**; the ledger is **only for cleanup**. When the order is decided (any channel, timeout, manual SQL) every open alert is **edited** to the final state ("✅ Accepted by X · pickup 12:15", "❌ Declined by X", "⏱ Auto-accepted …"), never deleted. A late tap on any alert shows the same final text. |
| D25 | **Identifiers.** `tuid` = Telegram user id (the person; same in every chat; arrives as `from_user.id`) is used to **authorise**. `tcid` = Telegram chat id (the conversation; `send/edit/deleteMessage` need it with `message_id`) is used to **address** messages. In a private chat with the bot they are the same number; in a group they differ (the group's id is negative). New tables name the columns `tuid` / `tcid`. `t_invites` keeps `telegram_user_id` / `telegram_chat_id` (live, working); renaming them is optional later. |
| D26 | **The order card is one deep module** (`channels/telegram/rest_admin/order_cards/`): an immutable `Card` changed only by **events** (`Reminded`, `Accepted`, `Declined`, `PickupChosen`, `AutoAccepted`, `Vanished`); every text, button and toast is composed in `model.py`; callers use three methods (`remind`, `refresh`, `tap`). Every visible change goes through `refresh`, which rebuilds the card from the DB snapshot. The SQL side may have many functions; the Python surface stays small. |
| D27 | **Group-ready, not group-built.** The owner may later put a restaurant's admins in one Telegram group and send cards there. Nothing built now may block that: (1) authorisation is always by the tapper's `tuid` (D14), never by the chat a button was pressed in; (2) cards go to **destinations** (`tcid` + optional admin), returned by one SQL function, so a group is a new row source, not a new code path; (3) ledger copies may have no owning admin (`tuid` NULL = shared chat); (4) the card has a **shared viewer** (third-person text, buttons for any authorised tapper); (5) order handlers must work in any chat type (only invite onboarding is private-only). See "Future: restaurant group chat". |

Design choices (agreed): A. the same sweep also finds open alerts for decided orders and asks the app to edit them
(covers WhatsApp accepts, timeouts and manual SQL; the tapping admin's own card changes immediately, others within
~5 s). B. Telegram taps go through `t_order_decide` / `t_order_set_pickup`, which check D14 and call the shared
functions in one transaction. C. Two tables: `t_order_alerts` (schedule) and `t_sent_messages` (ledger, generic so
the rider bot can reuse it). Copies of a card follow the order until final (other admins also see the pickup time
once chosen). D. The inbox check is an aiogram outer middleware. E. The sweep endpoint is
unauthenticated, like `/delivery-hooks/*` (recorded risk). F. SQL files below. G. Build order 2 → 3 → 4 → 5.

---

## Architecture (phases 2–5)

```
                 ┌──────────── Postgres (authoritative) ───────────────────────────────────────────────┐
 order created → │ delivery_summary / takeaway_summary  (restaurant_confirmation_status, status,        │
                 │                                       restaurant_admin, pickup_time, dtts)          │
                 │   ▲ restaurant_order_decide / restaurant_order_set_pickup        (phase 3, shared)  │
                 │   │      ▲ t_order_decide / t_order_set_pickup   (phase 5: D14 auth + call)          │
                 │ t_order_alerts (schedule)   t_sent_messages (ledger: where each card lives)  (ph. 4)│
                 │ job_t_order_alerts()  every 5 s: seed → cancel → due reminders → stale cards → POST │
                 │ t_inbox (phase 2)        t_housekeeping() daily                                     │
                 └────────┬────────────────────────────────────────────────────────▲─────────────────┘
                          │ http_post /telegram/rest-admin/order-alerts             │ RPCs (service key)
                          ▼                                                         │
   watomation/routers/telegram_order_alerts.py ──► OrderCards.remind(order) / .refresh(order)
   Telegram tap ─► webhook ─► Dispatcher ─► InboxMiddleware ─► orders router ─► OrderCards.tap(query, action)
                                                 OrderCards = channels/telegram/rest_admin/order_cards/  (deep module)
                                                   model.py  pure Card + events + views + toasts (ALL composition)
                                                   store.py  every RPC above (private adapter)
                                                   io.py     send / edit / delete + Telegram error mapping (private)
   WhatsApp tap ─► on_callback_wa_handler.py ─► utils_common/order_management/restaurant_decision.py (phase 3)
```

**Depth (codebase-design).** The database side has many functions; that is fine. What callers learn is small:

| Module | Interface (everything a caller must know) | Hides |
|---|---|---|
| `utils_common/order_management/restaurant_decision.py` | `decide(order_number, order_type, decision, admin_phone, channel)`, `set_pickup(...)`, `describe(state, decided_by)` | RPC names, race handling, table choice |
| `channels/telegram/inbox.py` | `InboxMiddleware(bot_key)` (registered once in `bots.py`) | claim/finish RPCs, fail-open policy |
| `channels/telegram/rest_admin/order_cards/` | `OrderCards(bot, bot_key, store=None)` with **three** methods: `remind(order, n, of)`, `refresh(order)`, `tap(query, action)`; value type `OrderRef(order_number, order_type)` | destination and authorisation lookups, DB re-checks, send→record→delete ordering, ledger states, card composition per viewer, events, toasts, Telegram error mapping, retries |

Deletion test: without `OrderCards`, the sweep endpoint and the callback handler would each need the destination rules,
the ledger protocol, the rendering and the Telegram error mapping. With it, the endpoint is a loop of `remind`/`refresh`
calls and the handler is one line. Seams for tests: `store` is injected (an in-memory `FakeCardStore` mimicking the
RPC contract, like `FakeInviteDb`), and Telegram is the existing `RecordingSession`
(`tests/channels/telegram/conftest.py:12`), extended to record `deleteMessage`/`editMessageText` and return
incrementing `message_id`s. `model.py` is pure and tested without either.

### The order card (D26): one immutable value, changed only by events, composed in one place

`channels/telegram/rest_admin/order_cards/model.py` owns every word and button an admin ever sees about an order.

```python
@dataclass(frozen=True)
class Facts:                       # never change after creation
    order_number: str
    order_type: Literal["delivery", "takeaway"]
    rest_name: str
    total: str                     # "£23.50", formatted once by the snapshot
    items: tuple[str, ...]         # ("2x Biryani", "1x Naan")
    ordered_at: datetime           # summary.dtts (aware, UK display via fmt_uk_time)

@dataclass(frozen=True)
class Actor:                       # who decided; label per D19
    label: str                     # "Ada" | "…0754"
    phone: str | None              # matched against the viewer to say "You"

Status = Literal["awaiting", "accepted", "pickup_set", "declined", "auto_accepted", "gone"]
TERMINAL: frozenset[Status] = frozenset({"pickup_set", "declined", "auto_accepted", "gone"})
# Same keys as SQL t_order_card_status() (create_t_order_alerts.sql). Change both together.

# ---- events: the ONLY way a card changes -------------------------------------------------
@dataclass(frozen=True)
class Reminded:                    # a fresh copy is being sent (reminder n of `of`)
    n: int
    of: int

@dataclass(frozen=True)
class Accepted:
    by: Actor

@dataclass(frozen=True)
class Declined:
    by: Actor

@dataclass(frozen=True)
class PickupChosen:
    at: datetime
    by: Actor | None

@dataclass(frozen=True)
class AutoAccepted:                # the timeout path set a default pickup
    at: datetime

@dataclass(frozen=True)
class Vanished:                    # order row not found
    pass

Event = Reminded | Accepted | Declined | PickupChosen | AutoAccepted | Vanished

@dataclass(frozen=True)
class Viewer:                      # who will read this copy
    phone: str | None              # the admin's phone for a private chat; None for a shared (group) chat
    authorised: bool = True        # False once the destination is no longer valid (D14 revoked / group unlinked)
    shared: bool = False           # D27: a group chat -> third-person text only, buttons for any authorised tapper

@dataclass(frozen=True)
class View:
    text: str                      # HTML, every DB/user string escaped (router.escape)
    keyboard: InlineKeyboardMarkup | None
    terminal: bool                 # True -> the ledger row closes after this edit

@dataclass(frozen=True)
class Card:
    facts: Facts
    status: Status = "awaiting"
    reminder: tuple[int, int] | None = None
    decided_by: Actor | None = None
    pickup_at: datetime | None = None

    def apply(self, event: Event) -> "Card": ...      # transition table below; illegal -> self (and log)
    def view(self, viewer: Viewer) -> View: ...       # render table below; the only place text/buttons are built
    @classmethod
    def from_snapshot(cls, snap: "Snapshot") -> "Card": ...   # replays the events implied by the DB row

def toast(outcome: "TapOutcome") -> tuple[str, bool]: ...   # callback answer text + show_alert; also composed here
```

**Transitions** (`Card.apply`; anything not listed returns the card unchanged and logs at debug — e.g. a late
`Accepted` after `Declined` cannot happen in the DB, so it must not happen on screen either):

| From | Event | To |
|---|---|---|
| awaiting | `Reminded(n, of)` | awaiting (reminder = n of `of`) |
| awaiting | `Accepted(by)` | accepted |
| awaiting | `Declined(by)` | declined |
| awaiting, accepted | `AutoAccepted(at)` | auto_accepted (pickup_at = at) |
| accepted | `PickupChosen(at, by)` | pickup_set |
| any | `Vanished()` | gone |

**`from_snapshot`** — the DB snapshot carries the SQL status key; the card is rebuilt by replaying events, so a card
can never show a state the database is not in:

| `snap.status` | Events replayed after `Card(facts)` |
|---|---|
| awaiting | — |
| accepted | `Accepted(snap.decided_by)` |
| pickup_set | `Accepted(snap.decided_by)`, `PickupChosen(snap.pickup_at, snap.decided_by)` |
| declined | `Declined(snap.decided_by)` |
| auto_accepted | `AutoAccepted(snap.pickup_at)` |
| gone | `Vanished()` |

**Views** (`Card.view(viewer)`; "You" when `viewer.phone == decided_by.phone`). Layout follows the order card in
`notebooks/telegram/tgram_scratchpad.py:121-209` (cell 5d): status line first, then
`<b>{order_number}</b> · {total} · 🚚 Delivery | 🥡 Takeaway`, items, `Ordered {HH:MM}`.

| Status | Status line (decider sees) | Status line (other admins see) | Buttons | terminal |
|---|---|---|---|---|
| awaiting | `🔔 New order — accept or decline` (+ ` · reminder 2 of 4` when n > 1) | same | `✅ Accept` `❌ Decline` | no |
| accepted | `✅ You accepted — choose a pickup time` | `✅ Accepted by Ada — waiting for pickup time` | decider only: pickup times = ordered_at + 5/15/25 min (parity with `wa_senders.send_restaurant_pickup_time`, `wa_senders.py:88-140`) | no |
| pickup_set | `✅ You accepted · pickup 12:15` | `✅ Accepted by Ada · pickup 12:15` | — | yes |
| declined | `❌ You declined this order` | `❌ Declined by Ada` | — | yes |
| auto_accepted | `⏱ Auto-accepted (no answer in time) · pickup 12:30` | same | — | yes |
| gone | `This order is no longer available.` | same | — | yes |
| any, `viewer.authorised=False` | `🔒 You no longer have access to this restaurant's orders.` | same | — | yes |
| *(D27, later)* any, `viewer.shared=True` | — | always the "other admins" wording (never "You") | as the other-admins column, except `accepted` also shows the pickup buttons; the RPC checks whoever taps | as above |

Buttons use `OrderAction` (`channels/telegram/callbacks.py`): `prefix="ord"`, fields `o: str` (order number),
`t: Literal["d", "t"]`, `a: Literal["acc", "dec", "pk"]`, `m: int = 0` → e.g. `ord:ELAS-CEKT-22:d:pk:15` (order
numbers are 12 chars live; column is varchar(100)). If `fits_callback_limit` fails, the view drops the buttons and
logs an error; it never raises.

**Toasts** (`toast(outcome)`, shown as the callback answer): `ok` accept → "Accepted — pick a time"; `ok` decline →
"Declined"; `ok` pickup → "Pickup 12:15"; `already_decided` → "Already accepted by Ada" (or declined / auto-accepted);
`already_set` → "Pickup already set to 12:15"; `not_authorised` → "You're not an admin for this restaurant any more."
(`show_alert=True`); `not_found` → "This order is no longer available."

### `OrderCards` behaviour (the three methods)

```python
class OrderCards:
    def __init__(self, bot: Bot, bot_key: str, store: CardStore | None = None): ...

    async def remind(self, order: OrderRef, n: int, of: int) -> None:
        snap = await self._store.snapshot(order)                 # D24: authoritative check BEFORE sending
        if snap is None or snap.status != "awaiting":
            return await self.refresh(order)                     # decided meanwhile: tidy up instead
        card = Card.from_snapshot(snap).apply(Reminded(n, of))
        for dest in snap.destinations:                           # D14/D27: chats to send to, resolved in SQL
            viewer = Viewer(dest.phone, shared=dest.tuid is None)
            sent = await self._io.send(dest.tcid, card.view(viewer))   # None if bot blocked / removed from group
            if sent is None:
                continue
            rec = await self._store.card_sent(order, dest, sent.message_id, card.status)
            for prev in rec.previous:                            # older copies in THIS chat -> delete (D24)
                await self._store.mark(prev.id, await self._io.delete(prev), card_status=None, close=True)
            if rec.order_status != "awaiting":                   # D24: re-checked AFTER sending; decided mid-send
                return await self.refresh(order)

    async def refresh(self, order: OrderRef) -> None:
        snap = await self._store.snapshot(order)
        card = Card.from_snapshot(snap) if snap else None        # None -> Vanished
        for row in await self._store.take_for_refresh(order):    # stale copies, revoked viewers, retries
            if row.taken_for == "delete":
                await self._store.mark(row.id, await self._io.delete(row), card_status=None, close=True)
                continue
            viewer = Viewer(row.viewer_phone, row.authorised, shared=row.tuid is None)
            view = (card or Card.vanished(row)).view(viewer)
            outcome = await self._io.edit(row, view)             # 'edited' | 'gone' | 'retry'
            if outcome != "retry":
                await self._store.mark(row.id, outcome, card_status=snap.status if snap else "gone",
                                       close=view.terminal or outcome == "gone")

    async def tap(self, query: CallbackQuery, action: OrderAction) -> None:
        order = OrderRef(action.o, "delivery" if action.t == "d" else "takeaway")
        if action.a == "pk":
            outcome = await self._store.set_pickup(query.from_user.id, order, minutes=action.m)
        else:
            outcome = await self._store.decide(query.from_user.id, order, "accept" if action.a == "acc" else "decline")
        text, alert = toast(outcome)
        await query.answer(text, show_alert=alert)
        await self.refresh(order)          # every outcome, including not_authorised, is shown by refreshing from the DB
```

Rules that keep it correct:
- **One rendering path.** Every visible change — a tap here, a WhatsApp accept, the timeout auto-accept, a manual SQL
  fix, a revoked invite — reaches the screen through `refresh`, which rebuilds the card from the database. The tapper
  sees their own change immediately because `tap` refreshes right after the RPC; other admins see it in the same call.
  The sweep is the safety net for changes made outside Telegram.
- **Ledger is cleanup only.** It records where each copy lives and what status it currently shows (`card_status`); it
  never decides anything. A copy is re-rendered when its `card_status` differs from the order's current status or its
  viewer is no longer authorised.
- **Telegram error mapping** (`io.py`): `TelegramBadRequest` "message is not modified" → `edited`; "message to
  delete/edit not found", "message can't be deleted/edited", `TelegramForbiddenError` → `gone`; `TelegramRetryAfter`
  → sleep `retry_after` once and retry (as `edit_with_backoff`, `tgram_scratchpad.py:91-104`); anything else →
  `retry` (row stays `taken`; the sweep re-offers it after 30 seconds).
- **Concurrency.** `take_for_refresh` and `card_sent` take rows atomically (`live → taken`), so the sweep and a tap
  refreshing the same order never edit or delete the same copy twice.

**Ledger row states (`t_sent_messages.state`)**
```
live ──(newer copy sent in the same chat)──────────────────► taken(delete) ──► closed(deleted|gone)
live ──(card_status ≠ order status, or viewer revoked)─────► taken(edit) ──► live (non-terminal view, card_status updated)
                                                                         └─► closed(edited|gone) (terminal view)
taken for more than 30 seconds (worker died, RetryAfter) is offered again by take_for_refresh.
```

---

## Phase 2 — Durable inbox ⬜

**Goal:** a Telegram update is handled at most once per `(bot_key, update_id)`, with a visible record of each.

**Files**
```
NEW   ordelo_datamodels/migrations/create_t_inbox.sql      table t_inbox + t_inbox_claim + t_inbox_finish
NEW   channels/telegram/inbox.py                           claim(), finish(), InboxMiddleware
EDIT  channels/telegram/bots.py:39-44                      build_rest_admin_dispatcher: dp.update.outer_middleware(InboxMiddleware(settings.bot_key))
EDIT  tests/channels/telegram/conftest.py                  FakeInboxDb + inbox_db fixture; ALSO fix FakeInviteDb docstring (line 100 still says "tgram_*")
NEW   tests/channels/telegram/test_inbox.py
EDIT  tests/channels/telegram/test_rest_admin_router.py, test_bots.py, tests/watomation/routers/test_telegram_webhook.py   use the inbox_db fixture where a dispatcher is fed
EDIT  docs/telegram-layer.md (+ .html), CONTEXT.md ("Telegram inbox"), docs/adr/0011-...md (amendment 2, see Docs)
```

**SQL (`create_t_inbox.sql`)** — header in the style of `create_t_invites.sql` (what it adds, how it fits, security,
callers: `channels/telegram/inbox.py`). Column naming per D25: `tuid` = the sender's Telegram user id.
```sql
CREATE TABLE IF NOT EXISTS public.t_inbox (
    bot_key      text        NOT NULL,
    update_id    bigint      NOT NULL,
    kind         text        NOT NULL,                  -- Update.event_type: 'message' | 'callback_query' | ...
    tuid         bigint,                                -- sender (from_user.id); NULL for updates without a user
    status       text        NOT NULL DEFAULT 'processing'
                 CHECK (status IN ('processing', 'done', 'failed')),
    error        text,
    received_at  timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    PRIMARY KEY (bot_key, update_id)
);
CREATE INDEX IF NOT EXISTS t_inbox_received_at ON public.t_inbox (received_at);   -- housekeeping
ALTER TABLE public.t_inbox ENABLE ROW LEVEL SECURITY;                            -- no policies

CREATE OR REPLACE FUNCTION public.t_inbox_claim(p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.t_inbox (bot_key, update_id, kind, tuid)
    VALUES (p_bot_key, p_update_id, p_kind, p_tuid)
    ON CONFLICT (bot_key, update_id) DO NOTHING;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'new');
    END IF;
    RETURN jsonb_build_object('result', 'duplicate', 'status',
        (SELECT status FROM public.t_inbox WHERE bot_key = p_bot_key AND update_id = p_update_id));
END $$;

CREATE OR REPLACE FUNCTION public.t_inbox_finish(p_bot_key text, p_update_id bigint, p_status text, p_error text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    IF p_status NOT IN ('done', 'failed') THEN RAISE EXCEPTION 't_inbox_finish: bad status %', p_status; END IF;
    UPDATE public.t_inbox SET status = p_status, error = left(p_error, 2000), finished_at = now()
     WHERE bot_key = p_bot_key AND update_id = p_update_id AND status = 'processing';
    RETURN jsonb_build_object('result', CASE WHEN FOUND THEN 'ok' ELSE 'not_processing' END);
END $$;

REVOKE ALL ON FUNCTION public.t_inbox_claim(text, bigint, text, bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_inbox_finish(text, bigint, text, text) FROM PUBLIC, anon, authenticated;
```

**Python (`channels/telegram/inbox.py`)** — copy the `_rpc` helper shape from `channels/telegram/invites.py:63-66`.
```python
class InboxMiddleware(BaseMiddleware):
    """Outer middleware on dp.update: claim (bot_key, update_id) before any handler; skip duplicates."""
    def __init__(self, bot_key: str):
        self.bot_key = bot_key

    async def __call__(self, handler, event: Update, data: dict):
        user = data.get("event_from_user")            # set by aiogram's UserContextMiddleware (registered before ours)
        try:
            fresh = await claim(self.bot_key, event.update_id, event.event_type, user.id if user else None)
        except Exception:                              # inbox DB down: fail OPEN; state-changing RPCs are still atomic
            logger.exception(f"telegram[{self.bot_key}]: inbox claim failed for {event.update_id}; processing anyway")
            return await handler(event, data)
        if not fresh:
            logger.info(f"telegram[{self.bot_key}]: duplicate update {event.update_id} skipped")
            return None
        try:
            result = await handler(event, data)
        except BaseException as exc:                   # includes CancelledError from the route's wait_for timeout
            await _finish_quietly(self.bot_key, event.update_id, "failed", repr(exc))
            raise
        await _finish_quietly(self.bot_key, event.update_id, "done")
        return result
```
Notes: aiogram's `Dispatcher.__init__` registers its errors and user-context middlewares on `dp.update` first, so
ours runs inside them and sees handler exceptions before `errors.py` handlers do (verify on aiogram 3.31; the
`Update.event_type` property gives `'message'` / `'callback_query'`). `_finish_quietly` logs and swallows its own
errors. The route (`watomation/routers/telegram_webhook.py`) needs **no change**.

**Tests (`test_inbox.py`)**
- same update fed twice through a real Dispatcher → handler runs once (count `RecordingSession.sent_texts`);
- handler raises → finish called with `failed` and the exception still propagates;
- claim raises → handler still runs (fail open), warning logged;
- unmatched update (no handler) → row finishes `done`.

**Acceptance:** suite green; live: send `/help` → one `t_inbox` row `done`; replay the same JSON body with curl to
the webhook (correct secret) → 200, no second reply, still one row.

---

## Phase 3 — Shared decision functions + R1-a ⬜

**Goal:** one atomic rule for accept/decline/pickup used by both channels; a delivery decline is terminal.

**Files**
```
NEW   ordelo_datamodels/migrations/restaurant_order_decision.sql   CHECK change + restaurant_admin_label + restaurant_order_decide + restaurant_order_set_pickup
EDIT  ordelo_datamodels/summary.sql:21                             add 'declined' to the status CHECK list (schema file must match live)
NEW   utils_common/order_management/restaurant_decision.py         decide(), set_pickup(), describe(), DecisionOutcome, PickupOutcome
EDIT  watomation/on_callback_wa_handler.py:241-286                 _update_restaurant_order_status → restaurant_decision.decide(...); reply on loss
EDIT  watomation/on_callback_wa_handler.py:321-380                 handle_pickup_time_selection → restaurant_decision.set_pickup(...); replies unchanged
EDIT  watomation/routers/delivery_hooks.py:1353-1380               _handle_restaurant_decline: mirror takeaway (D16)
NEW   tests/utils_common/order_management/test_restaurant_decision.py
EDIT  tests/watomation/test_on_callback_wa_handler.py:139-200      test_update_restaurant_order_status_success_and_stale_tap, test_handle_pickup_time_selection_success_and_already_updated
EDIT  tests/watomation/routers/test_delivery_hooks.py              new tests for the delivery decline handler
EDIT  docs/alerts-and-notifications.md                             "New order awaiting restaurant confirmation" row: Telegram channel + decline
```

**SQL (`restaurant_order_decision.sql`)** — header must say: tables are defined in `ordelo_datamodels/summary.sql`
and `takeaway_summary.sql`; callers are `utils_common/order_management/restaurant_decision.py` (WhatsApp) and, from
phase 5, `t_order_decide` / `t_order_set_pickup` (Telegram); the trigger `trigger_restaurant_updates` /
`trigger_takeaway_restaurant_updates` still fires `/delivery-hooks|/takeaway-hooks .../restaurant-confirmation-request`
on every `restaurant_confirmation_status` change, so payment, customer messages and WhatsApp pickup prompts keep
working unchanged.
```sql
-- 1. R1-a: delivery orders can be terminally declined (live constraint name verified 15 Oct).
ALTER TABLE public.delivery_summary DROP CONSTRAINT IF EXISTS delivery_summary_status_check;
ALTER TABLE public.delivery_summary ADD CONSTRAINT delivery_summary_status_check
    CHECK (status IN ('restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed', 'declined'));

-- 2. Display label for "by X" (D19). Reads t_invites (create_t_invites.sql).
CREATE OR REPLACE FUNCTION public.restaurant_admin_label(p_phone text)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT COALESCE(
        (SELECT i.telegram_first_name FROM public.t_invites i
          WHERE i.phone_number = p_phone AND i.status = 'claimed' AND i.telegram_first_name IS NOT NULL
          ORDER BY i.claimed_at DESC LIMIT 1),
        CASE WHEN coalesce(p_phone, '') = '' THEN NULL ELSE '…' || right(p_phone, 4) END)
$$;

-- 3. First decision wins (D18). p_order_type: 'delivery' | 'takeaway' (food_order.action values, verified).
CREATE OR REPLACE FUNCTION public.restaurant_order_decide(
    p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
    v_rcs text := CASE p_decision WHEN 'accept' THEN 'restaurant_accept' WHEN 'decline' THEN 'restaurant_decline' END;
    v_cur record;
BEGIN
    IF v_rcs IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') THEN
        RAISE EXCEPTION 'restaurant_order_decide: bad decision % or order type %', p_decision, p_order_type;
    END IF;
    IF p_order_type = 'delivery' THEN
        UPDATE public.delivery_summary
           SET restaurant_confirmation_status = v_rcs,
               status = CASE WHEN p_decision = 'decline' THEN 'declined' ELSE status END,   -- R1-a: never dispatchable
               restaurant_admin = p_admin_phone, restaurant_update_dtts = now()
         WHERE order_number = p_order_number AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    ELSE
        UPDATE public.takeaway_summary
           SET restaurant_confirmation_status = v_rcs,
               status = CASE WHEN p_decision = 'decline' THEN 'declined' ELSE status END,
               restaurant_admin = p_admin_phone, restaurant_update_dtts = now()
         WHERE order_number = p_order_number AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    END IF;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'ok', 'decision', p_decision, 'channel', p_channel,
                                  'decided_by', public.restaurant_admin_label(p_admin_phone),
                                  'decided_by_phone', p_admin_phone);
    END IF;
    -- Lost the race or already decided: report the authoritative state.
    IF p_order_type = 'delivery' THEN
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin, restaurant_update_dtts, pickup_time
          INTO v_cur FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSE
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin, restaurant_update_dtts, pickup_time
          INTO v_cur FROM public.takeaway_summary WHERE order_number = p_order_number;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    RETURN jsonb_build_object('result', 'already_decided', 'state', v_cur.rcs,
        'decided_by', public.restaurant_admin_label(v_cur.restaurant_admin),
        'decided_by_phone', v_cur.restaurant_admin, 'decided_at', v_cur.restaurant_update_dtts, 'pickup_time', v_cur.pickup_time);
END $$;

-- 4. Pickup selection: same conditions and writes as handle_pickup_time_selection today
--    (on_callback_wa_handler.py:330-345): status -> 'unassigned' (delivery) / 'pickup_confirmed' (takeaway).
CREATE OR REPLACE FUNCTION public.restaurant_order_set_pickup(
    p_order_number text, p_order_type text, p_pickup_time timestamptz, p_admin_phone text, p_channel text)
RETURNS jsonb  -- {result: ok | already_set | not_accepted | not_found, state, pickup_time, decided_by}
-- UPDATE ... SET pickup_time, status, restaurant_admin, restaurant_update_dtts
--  WHERE order_number = p AND restaurant_confirmation_status = 'restaurant_accept' AND pickup_time IS NULL
-- else: pickup_time IS NOT NULL -> 'already_set'; other state (timedout/auto_accept/...) -> 'not_accepted'.

REVOKE ALL ON FUNCTION public.restaurant_order_decide(text, text, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restaurant_order_set_pickup(text, text, timestamptz, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restaurant_admin_label(text) FROM PUBLIC, anon, authenticated;
```
Why `status='declined'` is set in the decide function and not in the Python handler: the decline and "not
dispatchable" must commit together (R1 constraint 4); today's handler sets `'unassigned'` after the fact, which is the
R1-a bug.

**Python (`restaurant_decision.py`)**
```python
@dataclass(frozen=True)
class DecisionOutcome:
    result: Literal["ok", "already_decided", "not_found", "not_authorised"]   # not_authorised only from phase 5
    decision: str | None = None        # 'accept' | 'decline' when ok
    state: str | None = None           # restaurant_confirmation_status when already_decided
    decided_by: str | None = None      # label (D19)
    decided_by_phone: str | None = None   # lets the order card say "You" to the decider
    pickup_time: str | None = None

async def decide(order_number, order_type, decision, admin_phone, channel) -> DecisionOutcome: ...
async def set_pickup(order_number, order_type, pickup_time, admin_phone, channel) -> PickupOutcome: ...
def describe(state: str, decided_by: str | None) -> str:
    # 'restaurant_accept'/'restaurant_pickuptime_adjusted' -> "accepted by X"; 'restaurant_decline' -> "declined by X";
    # 'restaurant_timedout'/'auto_accept' -> "auto-accepted (no answer in time)"; 'auto_decline' -> "auto-declined"
    ...
```
Module docstring per the CLAUDE.md rule: name `restaurant_order_decision.sql`, map functions → RPCs, list callers.

**WhatsApp switch (`on_callback_wa_handler.py:241`)**: keep the function name and signature (tests and
`restaurant_order_accept_decline_handler` at line 289 call it). Map `status` (`restaurant_accept|restaurant_decline`)
→ `decision`; call `decide(order_number, order_type, decision, msg.sender, "whatsapp")`; on `ok` log as today; on
`already_decided` reply `f"Order already {describe(o.state, o.decided_by)}"` (today: "Order Already Accepted");
on `not_found` log an error. `handle_pickup_time_selection` (line 321) calls `set_pickup(...)` with the same
`pickup_time` from the button; replies stay "Pickup time updated" / "Pickup time already updated".

**Delivery decline handler (`delivery_hooks.py:1353`)**, rewritten after `takeaway_hooks.py:213-262`:
1. idempotent guard update: `status='declined'` where `restaurant_confirmation_status='restaurant_decline'` (covers
   manual SQL declines; the RPC already set it);
2. `cancel_payment(order_number)` (`delivery_hooks.py:229`) unless `food_order.payment_status == "pay_at_rest"`,
   exceptions logged;
3. web customer (`is_web_customer_key(delivery_summary.customer_id)`): `queue_release(order_number,
   "restaurant_declined")` (`utils_common/web_ordering/lifecycle.py`) if the cancel failed, then
   `customer_notifier.publish(order_number, CustomerOrderEvent("restaurant_declined", "restaurant_declined",
   "web-restaurant-declined", {"payment_cancelled": ...}))`;
4. WhatsApp customer: `_async_wa_client.send_message(to=customer_id, text=...)` with the takeaway wording.
Verified: dispatch only selects `status='unassigned'`; `customer_order_view.py:67` already maps `status ==
'declined'`; `restaurant-frontend/app/rest-admin/orders/_lib/types.ts:13` already has `'declined'`.

**Tests:** decide ok/already_decided/not_found (fake client); WhatsApp stale tap reply names X; delivery decline
handler: payment cancelled, web event published, `queue_release` on cancel failure, WhatsApp text sent, status never
`'unassigned'`.

**Acceptance:** suite green; on test: WhatsApp Accept still works end to end; a second Accept from another admin
gets "Order already accepted by …". A decline via SQL `SELECT restaurant_order_decide('<test order>','delivery',
'decline','<admin phone>','manual')` leaves `status='declined'`, cancels the test payment, and the order never
reaches dispatch.

---

## Phase 4 — Order alerts: `OrderCards.remind` / `refresh` + ledger ⬜

**Goal:** linked admins (D14) get the order card at 0/15/30/45 s; each new copy replaces the previous one in that
chat; every copy follows the order's state until it is final; old rows are purged. Build `model.py` first, test-first
(it is pure), then `store.py`/`io.py`, then `OrderCards`.

**Files**
```
NEW   ordelo_datamodels/migrations/create_t_order_alerts.sql            tables, functions, job, housekeeping, config rows
NEW   channels/telegram/rest_admin/order_cards/__init__.py              OrderCards, OrderRef (the ONLY public names)
NEW   channels/telegram/rest_admin/order_cards/model.py                 Facts, Actor, Viewer, View, Card, events, toast, Status/TERMINAL
NEW   channels/telegram/rest_admin/order_cards/store.py                 CardStore: snapshot, card_sent, take_for_refresh, mark (+ decide/set_pickup in phase 5)
NEW   channels/telegram/rest_admin/order_cards/io.py                    TelegramIO: send, edit, delete with error mapping
EDIT  channels/telegram/callbacks.py                                    OrderAction(CallbackData, prefix="ord")
EDIT  channels/telegram/bots.py:28-61                                   TelegramBot gains `cards: OrderCards`; build_registry builds it for rest_admin; dp["order_cards"] = cards
NEW   watomation/routers/telegram_order_alerts.py                       POST /telegram/rest-admin/order-alerts
EDIT  watomation/fapp_ordelo_agent.py                                   include_router(telegram_order_alerts.router) next to telegram_webhook
EDIT  tests/channels/telegram/conftest.py                               RecordingSession records deleteMessage/editMessageText, returns incrementing message_id; FakeCardStore
NEW   tests/channels/telegram/test_order_card_model.py                  table-driven transitions + golden views per viewer
NEW   tests/channels/telegram/test_order_cards.py                       remind/refresh with FakeCardStore + RecordingSession
NEW   tests/watomation/routers/test_telegram_order_alerts.py
EDIT  tests/test_smoke_imports.py                                       new modules
```

**Tables** (D25 naming: `tcid` = chat the copy lives in, `tuid` = admin it belongs to)
```sql
CREATE TABLE IF NOT EXISTS public.t_order_alerts (            -- the schedule: one row per order x offset
    id           bigserial PRIMARY KEY,
    bot_key      text        NOT NULL DEFAULT 'rest_admin',
    order_number text        NOT NULL,
    order_type   text        NOT NULL CHECK (order_type IN ('delivery', 'takeaway')),
    rest_ref     text        NOT NULL,
    offset_secs  int         NOT NULL,
    n            int         NOT NULL,                        -- 1-based position in the offset list ("reminder n of `of`")
    of_n         int         NOT NULL,
    due_at       timestamptz NOT NULL,                        -- summary.dtts + offset
    status       text        NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'sent', 'superseded', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    swept_at     timestamptz,
    UNIQUE (bot_key, order_number, offset_secs)
);
CREATE INDEX IF NOT EXISTS t_order_alerts_due ON public.t_order_alerts (due_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS public.t_sent_messages (           -- the ledger: where each copy lives; cleanup only
    id            bigserial PRIMARY KEY,
    bot_key       text        NOT NULL,
    tcid          bigint      NOT NULL,                       -- chat holding the message (send/edit/delete target)
    message_id    bigint      NOT NULL,
    tuid          bigint,                                     -- admin the copy was sent to; NULL = shared (group) chat (D27)
    subject_type  text        NOT NULL,                       -- 'order' (the rider bot may add others)
    subject_ref   text        NOT NULL,                       -- order_number
    order_type    text,                                       -- 'delivery' | 'takeaway' when subject_type = 'order'
    kind          text        NOT NULL,                       -- 'order_card'
    rest_ref      text,
    card_status   text,                                       -- status key the copy currently shows
    state         text        NOT NULL DEFAULT 'live' CHECK (state IN ('live', 'taken', 'closed')),
    taken_for     text        CHECK (taken_for IN ('delete', 'edit')),
    taken_at      timestamptz,
    close_reason  text,                                       -- 'deleted' | 'edited' | 'gone'
    sent_at       timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    closed_at     timestamptz,
    UNIQUE (bot_key, tcid, message_id)
);
CREATE INDEX IF NOT EXISTS t_sent_messages_subject ON public.t_sent_messages (subject_type, subject_ref) WHERE state <> 'closed';
CREATE INDEX IF NOT EXISTS t_sent_messages_closed  ON public.t_sent_messages (closed_at) WHERE state = 'closed';
-- RLS on both, no policies.
```

**Functions** (all `REVOKE ... FROM PUBLIC, anon, authenticated`; called only through `order_cards/store.py`)

| Function | Returns | Python (`CardStore`) | Notes |
|---|---|---|---|
| `t_order_card_status(p_rcs text, p_pickup timestamptz)` | text, IMMUTABLE | — (used by the others) | `restaurant_unconfirmed`→`awaiting`; `restaurant_accept`+no pickup→`accepted`; `restaurant_accept`/`restaurant_pickuptime_adjusted`+pickup→`pickup_set`; `restaurant_decline`/`auto_decline`→`declined`; `auto_accept`/`restaurant_timedout`+pickup→`auto_accepted`; `restaurant_timedout` without pickup→`awaiting` (the timeout handler sets the pickup within seconds). Same keys as `model.Status` |
| `t_order_card_destinations(p_bot_key, p_rest_ref)` | table(tcid, tuid, phone, label) | — (inside snapshot) | **The one place that says where cards go.** Today: one private chat per admin satisfying D14 (`t_invites` claimed + `phone_number = ANY(restaurant_master.admins)`), `DISTINCT ON (telegram_chat_id)`. Later (D27): `UNION ALL` linked group chats with `tuid`/`phone` NULL |
| `t_order_card_snapshot(p_bot_key, p_order_number, p_order_type)` | jsonb or NULL | `snapshot(order)` | **The DB check before sending.** Facts (rest_ref, rest_name, order_type, dtts, `food_order.total_price`, items from `order_item` as in `summary.sql:243-256`), `status` key, `decided_by {label, phone}` (`restaurant_admin_label`, phase 3), `pickup_at`, `destinations` array |
| `t_order_card_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_order_number, p_order_type, p_rest_ref, p_card_status)` | jsonb `{previous:[{id, tcid, message_id}], order_status}` | `card_sent(...)` | One transaction: insert the copy `live`; take this chat's older `live` copies of the order (`taken_for='delete'`); return the order's current status (**the DB check after sending**) |
| `t_order_cards_take(p_bot_key, p_order_number, p_order_type)` | jsonb `{rows:[{id, tcid, message_id, tuid, viewer_phone, authorised, taken_for}]}` | `take_for_refresh(order)` | Takes `live` copies whose `card_status` ≠ current status **or** whose `tcid` is no longer among the destinations (revoked / unlinked); plus `taken` copies older than 2 min (keep their `taken_for`) |
| `t_order_card_mark(p_id, p_outcome, p_card_status, p_close)` | void | `mark(...)` | `edited` + not close → back to `live` with new `card_status`; close → `closed` with `close_reason` |
| `job_t_order_alerts()` | boolean | — | pg_cron every 5 s, below |
| `t_housekeeping()` | jsonb counts | — | D22: deletes old rows from `t_inbox` (phase 2), `t_sent_messages`, `t_order_alerts` |

**The sweep `job_t_order_alerts()`** (structure and comments copied from `job_rider_pickup_alerts.sql`):
1. Offsets: `COALESCE(parse_alert_offsets(rest_ref || '_TGRAM_ORDER_ALERT_OFFSETS_SECS'),
   parse_alert_offsets('TGRAM_ORDER_ALERT_OFFSETS_SECS'))` — `parse_alert_offsets(p_config_key text) RETURNS int[]`
   is defined in `job_rider_pickup_alerts.sql:186` (reads `ordelo_config`; blank key → NULL → off). Seed config row
   `TGRAM_ORDER_ALERT_OFFSETS_SECS = '0,15,30,45'`.
2. **SEED**: `delivery_summary` ∪ `takeaway_summary` rows with `restaurant_confirmation_status =
   'restaurant_unconfirmed'`, `dtts > now() - interval '15 minutes'` and at least one destination → one checkpoint per
   offset (`n`, `of_n` from the array position), `due_at = dtts + offset`, `ON CONFLICT DO NOTHING`.
3. **CANCEL**: `pending` checkpoints whose order is no longer unconfirmed → `cancelled`.
4. **DUE**: `pending` checkpoints with `due_at <= now()`, one winner per order (largest offset; collapse after an
   outage), the rest to be superseded.
5. **STALE**: up to 50 distinct `(order_number, order_type)` with copies `t_order_cards_take` would take (same
   conditions, read-only here). This is what updates cards after a WhatsApp accept, a timeout, manual SQL or a revoke.
6. **POST** only if 4 or 5 is non-empty: `http_post(ORDELO_APP_URL || '/telegram/rest-admin/order-alerts',
   {"event_type": "t_order_alerts", "reminders": [{order_number, order_type, n, of}], "refreshes":
   [{order_number, order_type}]})` — URL building as in `job_rider_pickup_alerts.sql:380-392`.
7. **MARK only on 2xx**: supersede first, then winners `sent` (ordering note at `job_rider_pickup_alerts.sql:402-412`).

Schedules (operator): `SELECT cron.schedule('job_t_order_alerts', '5 seconds', $$SELECT job_t_order_alerts()$$);`
and `SELECT cron.schedule('t_housekeeping', '20 3 * * *', $$SELECT t_housekeeping()$$);`. Config rows
`TGRAM_INBOX_RETENTION_DAYS='7'`, `TGRAM_LEDGER_RETENTION_DAYS='30'` (`ordelo_config(config_key, config_value,
description)`, `ON CONFLICT (config_key) DO NOTHING`).

**Endpoint (`watomation/routers/telegram_order_alerts.py`)** — thin, like `telegram_webhook.py`:
```python
@router.post("/telegram/rest-admin/order-alerts", include_in_schema=False)
async def order_alerts(payload: OrderAlertsPayload, request: Request, background_tasks: BackgroundTasks):
    tg = request.app.state.telegram_bots.get(REST_ADMIN_BOT_KEY)
    if tg is None:
        raise HTTPException(503, "bot not configured")      # non-2xx: checkpoints stay pending
    for r in payload.reminders:
        background_tasks.add_task(tg.cards.remind, OrderRef(r.order_number, r.order_type), r.n, r.of)
    for r in payload.refreshes:
        background_tasks.add_task(tg.cards.refresh, OrderRef(r.order_number, r.order_type))
    return {"status": "accepted", "reminders": len(payload.reminders), "refreshes": len(payload.refreshes)}
```

**Tests**
- `test_order_card_model.py` (pure, no fakes): every transition in the table, every illegal one is a no-op;
  `from_snapshot` for each status; golden `view()` text and buttons for decider vs other admin vs unauthorised viewer;
  callback data fits 64 bytes for a 40-char order number; HTML escaping of item names; `toast()` for every outcome.
- `test_order_cards.py`: `remind` sends one copy per destination, deletes that chat's previous copy, skips when
  the order is decided, refreshes when `card_sent` reports a changed status, survives a blocked admin; `refresh`
  edits copies to the right per-viewer view, closes terminal ones, maps "not modified"/"not found"/Forbidden, leaves
  unknown errors `taken`; a revoked viewer gets the 🔒 view.
- Endpoint: 503 without bot; 200 and background calls with bot.
- SQL: parse with pglast; the live acceptance below is the real test.

**Acceptance (test env):** with the owner's claimed ELAS invite, create a test order (skill
`ordelo-local-automatic-orders`): copies arrive at ~0/15/30/45 s with "reminder n of 4", one visible at a time;
Accept on WhatsApp → the Telegram card shows "✅ Accepted by …" within ~5 s, then "· pickup HH:MM" once a pickup is
chosen; no answer → after the timeout it shows "⏱ Auto-accepted … · pickup HH:MM". `t_sent_messages` rows end
`closed`; `t_order_alerts` rows end `sent` / `superseded` / `cancelled`.

---

## Phase 5 — Telegram actions: `OrderCards.tap` ⬜

**Goal:** Accept / Decline / pickup from the card, authorised per D14, race-safe with WhatsApp and other admins.

**Files**
```
EDIT  ordelo_datamodels/migrations/restaurant_order_decision.sql   append t_order_decide + t_order_set_pickup (Telegram auth wrappers)
EDIT  channels/telegram/rest_admin/order_cards/store.py           decide(tuid, order, decision), set_pickup(tuid, order, minutes)
EDIT  channels/telegram/rest_admin/order_cards/__init__.py        OrderCards.tap
NEW   channels/telegram/rest_admin/orders.py                      build_orders_router(): ONE handler, OrderAction.filter() -> order_cards.tap(query, callback_data)
EDIT  channels/telegram/rest_admin/router.py:153                  build_router(): include build_orders_router() BEFORE the text fallback
EDIT  tests/channels/telegram/test_order_cards.py, test_rest_admin_router.py
```

**SQL**
```sql
CREATE OR REPLACE FUNCTION public.t_order_decide(
    p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_rest_ref text; v_phone text;
BEGIN
    IF p_order_type = 'delivery' THEN
        SELECT rest_ref INTO v_rest_ref FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSE
        SELECT rest_ref INTO v_rest_ref FROM public.takeaway_summary WHERE order_number = p_order_number;
    END IF;
    IF v_rest_ref IS NULL THEN RETURN jsonb_build_object('result', 'not_found'); END IF;
    SELECT i.phone_number INTO v_phone
      FROM public.t_invites i JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
     WHERE i.bot_key = p_bot_key AND i.telegram_user_id = p_tuid AND i.rest_ref = v_rest_ref
       AND i.status = 'claimed' AND i.phone_number = ANY (rm.admins)
     LIMIT 1;
    IF v_phone IS NULL THEN RETURN jsonb_build_object('result', 'not_authorised'); END IF;   -- D14
    RETURN public.restaurant_order_decide(p_order_number, p_order_type, p_decision, v_phone, 'telegram');
END $$;
-- t_order_set_pickup(p_bot_key, p_tuid, p_order_number, p_order_type, p_minutes int): same auth; pickup time
-- computed in SQL as summary.dtts + p_minutes (parity with the WhatsApp buttons); then restaurant_order_set_pickup(...).
```
Add both to the SQL header's caller list (`channels/telegram/rest_admin/order_cards/store.py`) and to
`docs/telegram-layer.md` §6.

**Handler (`rest_admin/orders.py`)** — the whole file is a router factory with one handler:
```python
def build_orders_router() -> Router:
    router = Router(name="rest_admin_orders")

    @router.callback_query(OrderAction.filter())
    async def on_order_action(query: CallbackQuery, callback_data: OrderAction, order_cards: OrderCards):
        await order_cards.tap(query, callback_data)          # toast + refresh; never raises to the user

    return router
```
`order_cards` is injected from `dp["order_cards"]` (set in `bots.py`, like `tgram_settings`). `tap` catches
unexpected errors, answers with `router.TROUBLE` and logs (like `on_invite_decision`, `router.py:97-120`).

**Tests:** accept → toast "Accepted — pick a time", tapper's copy shows pickup buttons, another admin's copy shows
"Accepted by Ada — waiting for pickup time"; second admin taps Accept → toast "Already accepted by Ada" and their
copy shows the same; decline → "❌ You declined" / "❌ Declined by Ada"; non-admin tap → alert toast and the 🔒 view;
pickup 15 → both copies show "· pickup HH:MM" and close; the same callback update delivered twice → handled once
(phase 2 inbox).

**Acceptance (test env):** two linked admin chats: one taps Accept → their card shows pickup buttons and the other's
card shows "✅ Accepted by …" straight away; a WhatsApp admin who taps after gets "Order already accepted by …";
picking 15 min sets `pickup_time` and both cards show it; Decline on a delivery order → status `declined`, payment
cancelled, customer told, order never dispatched; removing the phone from `restaurant_master.admins` stops both
alerts and taps and turns that admin's live card into the 🔒 view.

---

## Future: restaurant group chat (D27 — not built; how it plugs in)

Idea (owner, 15 Oct): add a restaurant's admins to one Telegram group and send order cards there instead of (or as
well as) private chats. Nothing in phases 2–5 blocks it; this is the checklist for when it is built.

| Need | Where it plugs in | Already prepared by |
|---|---|---|
| Link a group to a restaurant | New table (e.g. `t_chat_links(bot_key, tcid, rest_ref, linked_by_tuid, status)`), filled by a `/link <invite>` command run in the group by an authorised admin; `my_chat_member` updates to notice the bot being removed (adds to `allowed_updates`) | Invite RPC pattern (`create_t_invites.sql`) |
| Send cards to the group | `t_order_card_destinations` gains `UNION ALL` of linked groups with `tuid`/`phone` NULL | D27 (2): destinations come from one SQL function |
| Ledger copies without an owner | `t_sent_messages.tuid` NULL | D27 (3) |
| Group wording and buttons | `Viewer(shared=True)` row of the view table | D27 (4) |
| Who may tap in the group | Unchanged: `t_order_decide` / `t_order_set_pickup` check the tapper's `tuid` against D14, whatever chat the button is in | D14, D25 |
| Unlink / bot removed | Destination disappears → `t_order_cards_take` re-renders the copy as 🔒 or marks it `gone` | `take_for_refresh` revocation rule |
| Group privacy mode | Callback queries reach the bot in groups regardless of privacy mode; commands need `/cmd@BotName` | — |
| Avoid double notifications | Decide later whether admins in a linked group still get private copies | — |

Rules for phases 2–5 so this stays true: never authorise from `chat.id`; never assume `message.chat.type ==
"private"` outside invite onboarding (`cmd_start` keeps its private-only check); never key the ledger or a
card by `tuid` alone.

---

## Phase 6 — Verification loop (after each phase, and once at the end) ⬜

Run the project skill **`telegram-vertification-loop`** (`.claude/skills/telegram-vertification-loop/SKILL.md`; the
name is spelled that way) for every phase before calling it done, and once more across phases 2–5 at the end. Its
loop, applied here:

1. **Set the boundary.** For each phase, trace update/domain event → webhook → dispatcher → inbox middleware →
   handler → `OrderCards`/wrapper → SQL RPC → outgoing Bot API call. Name the observable result and the durable
   state change for each actor (tapping admin, other admins, WhatsApp admins, customer, ops).
2. **Test first** where practical: write the focused failing test, see it fail for the right reason, implement, rerun.
3. **Dispatcher boundary** (offline): real aiogram `Dispatcher` + `RecordingSession` + update builders
   (`tests/channels/telegram/conftest.py`). Assert Bot API method, destination `tcid`, text, keyboard, callback answer
   and number of sends. Check callback byte limits and HTML escaping whenever card text or callback data changes.
4. **Webhook boundary** (offline): `tests/watomation/routers/test_telegram_webhook.py` and
   `test_telegram_order_alerts.py`: bot selection, bad secret, malformed update, handler error, timeout; with the inbox,
   persistence, dedupe and what a retry does. HTTP 200 is not proof of processing; assert the `t_inbox` outcome.
5. **Isolated database** (SQL truth): run every new migration against a **throwaway Postgres** (Docker `postgres:16`
   or `supabase start`) seeded with the minimal schema (`ordelo_datamodels/summary.sql`, `takeaway_summary.sql`,
   `restaurant_master`, `food_order`, `order_item`, `ordelo_config`, `create_t_invites.sql`). Stub `http_post` there to
   return 200 so `job_t_order_alerts()` can be called directly. Put these tests in `tests/sql/` behind an env var
   (`ORDELO_TEST_DB_URI`; skipped when unset). Never run them against the shared test/prod database; preparing SQL does
   not authorise applying it (database-operations skill). If no isolated database is available, say so and label the
   SQL as unverified.
6. **Live Telegram** (only with the owner's go-ahead, test bot and test environment): a real user taps buttons in the
   Telegram app; check the visible card and the database rows. Bot-side sends cannot simulate a user tap. A successful
   Bot API call is API acceptance, not proof a human saw it.
7. **Rerun** the focused tests and the whole Telegram suite (`pytest tests/channels tests/watomation/routers -q`), keep
   the known unrelated failure explicit, and update `docs/telegram-layer.md` + change log.

**Scenario matrix** (from the skill's case list; implement the rows relevant to each phase):

| Case | Phase 2 (inbox) | Phase 3 (decision) | Phase 4 (cards) | Phase 5 (taps) |
|---|---|---|---|---|
| Allowed actor | `/help` handled once, row `done` | WhatsApp admin accepts → `restaurant_accept`, `restaurant_admin` set | each D14 admin gets one copy | linked admin accepts → pickup buttons for them, "Accepted by …" for others |
| Wrong actor | — | — | non-admin with a claimed invite (phone not in `admins`) gets no copy | same person taps an old copy → `not_authorised` alert, 🔒 view, order unchanged |
| Revoked / expired identity | — | — | invite revoked mid-campaign → no new copies, live copy → 🔒 | revoked admin taps → `not_authorised` |
| Stale button | — | second WhatsApp accept → "Order already accepted by …" | copy from reminder 1 still visible? must be deleted when reminder 2 lands | tap on a card whose order was decided on WhatsApp → "Already accepted by …", card refreshed |
| Repeated update | same `update_id` twice → handler once | — | sweep posts the same reminder twice → still one live copy per chat | same callback delivered twice → one decision, one toast |
| Competing requests | — | two concurrent `restaurant_order_decide` calls (isolated DB, two connections) → exactly one `ok` | sweep refresh and a tap refresh at the same time → no double edit/delete | Telegram Accept vs WhatsApp Accept at once → one winner, the other told who |
| Downstream failure | claim RPC down → fail open, logged | payment cancel fails on decline → `queue_release` (web) / logged | bot blocked by an admin, "message not found", RetryAfter | edit fails → fallback message, ledger stays consistent |
| `from_user.id` vs `chat.id` | `tuid` recorded from the sender | — | copy addressed by `tcid` | authorisation uses `from_user.id`; a test feeds a callback whose `chat.id` ≠ `from_user.id` (group-shaped) and expects the same outcome (D27) |

**Evidence report** (one block per phase, in the PR description or session summary):

```
Phase N — <scenario>
  boundary:  dispatcher | webhook | isolated database | live Telegram
  command / action:  pytest tests/channels/telegram/test_order_cards.py::test_... | "tapped Accept in chat with @OrdeloRestaurantBot"
  observed:  <what was seen: Bot API calls, rows, visible card text>
  label:     offline | isolated database | live Telegram
  not verified:  <next boundary not covered, e.g. "SQL concurrency not run on isolated DB">
```
Never claim SQL behaviour, webhook durability, user-visible delivery, payment or fulfilment from mocked Bot API
calls or an HTTP 200 alone.

**Files**
```
NEW   tests/sql/conftest.py                 skip unless ORDELO_TEST_DB_URI; apply minimal schema + migrations; stub http_post
NEW   tests/sql/test_restaurant_decision_sql.py   decide/set_pickup results + two-connection race
NEW   tests/sql/test_t_inbox_sql.py               claim/finish, duplicate
NEW   tests/sql/test_order_cards_sql.py           destinations (D14), snapshot status keys, card_sent previous/order_status, take conditions, sweep seed/due/collapse
```

---

## Docs to update (per phase, same change)

- `docs/telegram-layer.md`: §2 flow (inbox step; order alert flow), §3 file map, §6 cross-reference rows for every new
  table/function, §9 not-done list, change log line. `docs/telegram-layer.html`: `FLOWS` (add "order alert" and
  "tap Accept on an order" scenarios), `FILES`, `XREF`, `TODO`, `CHANGELOG`.
- `CONTEXT.md`: "Telegram inbox", "Order card (Telegram)" (one card per admin chat, follows the order until final), "Sent-message ledger", "Restaurant decision", and the `tuid` / `tcid` terms (D25).
- `docs/adr/0011-...md`: "Amendment 2 — 15 Oct 2026": parallel channel (D11), at-most-once inbox (D21), shared
  decision functions (D18), authorisation rule (D14), unauthenticated sweep endpoint (risk).
- `docs/alerts-and-notifications.md`: restaurant-admin rows for Telegram alerts, decline and final-state edits.
- `.claude/skills/database-operations/SKILL.md`: Tables Reference rows for `t_inbox`, `t_order_alerts`,
  `t_sent_messages`; note that `t_housekeeping()` is the only scheduled delete.
- `docs/local-testing-runbook.md`: the sweep posts to `ordelo_config.ORDELO_APP_URL`; local tests through the tunnel
  need that row pointed at the tunnel (it is shared with the test deployment).

## Operator steps (owner; the implementing agent must not do these)

| Phase | Steps |
|---|---|
| 2 | Run `create_t_inbox.sql` in Supabase; deploy; send `/help`; check one `t_inbox` row is `done`. |
| 3 | Run `restaurant_order_decision.sql` (changes the live CHECK constraint); deploy; WhatsApp accept smoke test. |
| 4 | Run `create_t_order_alerts.sql`; check the config rows; deploy; then `cron.schedule` the two jobs (above). To switch alerts off: blank `TGRAM_ORDER_ALERT_OFFSETS_SECS` or `cron.unschedule('job_t_order_alerts')`. |
| 5 | Re-run `restaurant_order_decision.sql` (adds the two functions); deploy; two-admin test. |

## Risks and open items

- **Unauthenticated sweep endpoint** (`/telegram/rest-admin/order-alerts`), like `/delivery-hooks/*`. Worst case: someone
  triggers reminders or final-state edits for real orders; it cannot change an order. Revisit with the other hooks.
- **Fail-open inbox:** if `t_inbox_claim` errors the update is processed without dedupe; decisions are still atomic.
- **Pickup times in the past:** parity with WhatsApp (order time + 5/15/25) can offer past times for slow taps. R1
  notes a filter; not in scope.
- **Shared `ORDELO_APP_URL`:** one database serves test and local runs; the sweep calls whichever URL is set.
- **Takeaway customer messaging and delivery decline use Ordelo's number**, not the restaurant app (ADR-0006 follow-up, R1).
- **Mixed column names:** `t_invites` uses `telegram_user_id` / `telegram_chat_id`; new tables use `tuid` / `tcid` (D25).
- **R2/R3 and R1 auto-decline** remain separate work (`claude/restaurant-admin-attention-requirements.md`).

---

## Appendix A — Phase 1 scaffold plan ✅ DONE (historical record)

> Everything below was implemented and verified on 15 October 2026 (commit `8d26ed3`). Deviations from
> the text are listed here; the original wording is kept for history.
> - **Linking** was built as invites (`t_invites`, `/start <code>` + confirmation tap), not contact share (§A9).
> - **Keys are required** (D6 superseded): missing token/secret stops the service at import; step 6 below now
>   means "the app refuses to start and names the missing keys".
> - Database objects use the **`t_` prefix** (`create_t_invites.sql`; a one-off `drop_tgram_invites.sql` removed the old `tgram_` names and was then deleted).
> - `invites.py` calls the RPCs with **`client_ordelo_service`** (service role); the anon client is denied.
> - The production bot is **`@OrdeloRestaurantBot`** (D8's shared starter bot was replaced).
> - Added later the same day: delivery-lag/handled-ms logging in the webhook route, `docs/telegram-layer.md`
>   (+ HTML), the RPC cross-reference rule in `CLAUDE.md`/`agents.md`, and the invite SOP in the database-operations skill.

**Status:** ✅ Implemented and verified 15 October 2026.
**Repository:** `OrdeloAgent` (this repo). `tgram_starter/` is **not modified**.
**Sources:** [`docs/ordelo_telegram_implementation_handoff.md`](../docs/ordelo_telegram_implementation_handoff.md),
[ADR 0011](../docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md),
[ADR 0012](../docs/adr/0012-rider-threads-follow-dispatch-assignments.md) (rider work, deferred),
`tgram_starter/` (reference only), project skill `.claude/skills/telegram-api/`.

---

### A0. What this step delivers

Mount a **restaurant-admin Telegram bot** (`bot_key = "rest_admin"`) on the existing FastAPI app
(`watomation/fapp_ordelo_agent.py`). This step adds the plumbing only: settings from AWS Secrets Manager, a bot
registry that builds a separate Bot and Dispatcher for each bot, a thin webhook route, three read-only commands,
two notebooks and tests. The rider bot comes later and plugs into the same registry.

#### Decisions (grilling session, 15 Oct 2026)

| # | Decision |
|---|---|
| D1 | Copy the starter's patterns into the ADR 0011 layout (`channels/telegram/`). **Never import `tgram_starter`** from production code (its README promises "Nothing outside this folder imports it"). The starter stays unchanged. |
| D2 | **Plumbing only.** No invites, order card, Mini App, echo or `/send` endpoints. Nothing keeps state in process memory, because gunicorn runs up to 3 workers (`gunicorn_conf.py:9`, `max_workers_str = "3"`). |
| D3 | One `TgramBotSettings` (pydantic-settings) class, built once per bot from prefixed `agent_env` keys `tgram_<bot_key>_*`. File: `config/tgram_setting.py`, singular to match `waba_setting.py`. |
| D3a | **No admin ID list in the settings.** Restaurant admins come from `restaurant_master.admins` (phone numbers; see `ordelo_datamodels/restaurant_master_pymodel.py:33`, `RestaurantMaster.get_admins_for`). |
| D4 | **Linking is not in this step.** `/start` replies "not linked yet". The next step links accounts by shared contact (see §9). |
| D5 | The webhook handles updates **inline**: secret check, time limit, log failures, always reply 200. A durable inbox (`telegram_inbox`, keyed `(bot_key, update_id)`) is a **hard gate before the first action that changes state** (order acceptance and so on). |
| D6 | **Superseded 15 Oct 2026: token and webhook secret are now required; startup fails if missing.** Original: Telegram keys are **optional**. The bot is enabled only when the token and webhook secret are both present. A disabled bot is not built, and its route returns 404. WhatsApp startup must never depend on Telegram. |
| D7 | Notebooks go in `notebooks/telegram/` and run from the main project `.venv`. Mini App and rider demo cells are dropped. |
| D8 | **Reuse the starter's existing dev bot** (its token is in `tgram_starter/.env`) as the restaurant-admin **test** bot. The rider bot gets created later. |
| D9 | `config/__init__.py` exports `tgram_rest_admin_settings` and `rest_admin_bot: Bot \| None`, so `from config import rest_admin_bot` works the way `_async_wa_client` does. The Bot is built at import (no connection opens until the first API call). The **Dispatcher stays out of `config`** to avoid circular imports. |
| D9a | Use `rest_admin` everywhere: `bot_key="rest_admin"`, secret keys `tgram_rest_admin_*`, route `/telegram/rest-admin/webhook`. |
| D10 | Focused contract tests in `tests/config/` and `tests/channels/telegram/`, plus the smoke-import list and `ruff`. |

#### Out of scope (do not build)

Invites and `/start <token>`; contact-share linking; the `telegram_identities`, `telegram_inbox` and message-index
tables; order acceptance and pickup-time actions; reminders and acknowledgement; the operations-messaging port
(`ordelo/ops_messaging/`); the rider bot; the Mini App; `scripts/telegram_webhook.py`; setting the webhook on startup
(**never** do this; see handoff §9).

---

### A1. Target file map

```text
NEW   config/tgram_setting.py                         TgramBotSettings, build_bot, tgram_rest_admin_settings, rest_admin_bot
EDIT  config/__init__.py                              re-export the two values + TgramBotSettings
NEW   channels/__init__.py                            empty
NEW   channels/telegram/__init__.py                   short docstring only
NEW   channels/telegram/bots.py                       TelegramBot dataclass, registry builder, dispatcher factory, close
NEW   channels/telegram/errors.py                     stale-callback error handler (from tgram_starter/bot_factory.py:40-47)
NEW   channels/telegram/keyboards.py                  contact_request_kb (from tgram_starter/keyboards.py:60-64), for step 2
NEW   channels/telegram/callbacks.py                  64-byte callback convention + fits_callback_limit()
NEW   channels/telegram/rest_admin/__init__.py        empty
NEW   channels/telegram/rest_admin/commands.py        REST_ADMIN_COMMANDS (BotCommand list) + HELP_TEXT
NEW   channels/telegram/rest_admin/router.py          build_router() factory: /start, /help, /whoami, fallback
NEW   watomation/routers/telegram_webhook.py          POST /telegram/{bot_slug}/webhook
EDIT  watomation/fapp_ordelo_agent.py                 lifespan builds/closes registry; include router
EDIT  pyproject.toml                                  aiogram==3.31.0; add "channels" to wheel packages
EDIT  uv.lock                                         `uv lock` (do not hand-edit)
EDIT  requirements.txt                                add aiogram==3.31.0 if this file is still used for any deploy path
NEW   notebooks/telegram/tgram_setup_bot.py           from tgram_starter/notebook_setup_bot.py
NEW   notebooks/telegram/tgram_scratchpad.py          from tgram_starter/notebook.py
EDIT  tests/conftest.py                               stub tgram_rest_admin_* keys in _STUB_AGENT_ENV
EDIT  tests/test_smoke_imports.py                     add new modules
NEW   tests/config/test_tgram_setting.py
NEW   tests/channels/__init__.py, tests/channels/telegram/__init__.py
NEW   tests/channels/telegram/conftest.py             RecordingSession + update payload builders
NEW   tests/channels/telegram/test_bots.py
NEW   tests/channels/telegram/test_rest_admin_router.py
NEW   tests/watomation/routers/test_telegram_webhook.py
EDIT  docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md   amendments (§8)
EDIT  CONTEXT.md                                      two new terms (§8)
EDIT  docs/local-testing-runbook.md                   short "Telegram restaurant-admin bot" section (§8)
```

Untouched: everything under `tgram_starter/`, including its `.env`, `pyproject.toml` and `.venv`.

---

### A2. Dependencies

`pyproject.toml` (currently lines 4–40 for dependencies and line 66 for the wheel packages):

```toml
dependencies = [
    ...
    # WhatsApp
    "pywa==3.6.1",
    # Telegram (restaurant-admin bot; rider bot later)
    "aiogram==3.31.0",
    ...
]

[tool.hatch.build.targets.wheel]
packages = ["ordelo", "ordelo_datamodels", "watomation", "utils_common", "utils", "config", "channels"]
```

Then run `uv lock && uv sync`. Use the same pin as `tgram_starter/pyproject.toml` (`aiogram==3.31.0`, sdist uploaded
2026-08-26 per `tgram_starter/uv.lock`). Check that `uv lock` doesn't force downgrades of `pydantic`, `aiohttp` or
`fastapi`. aiogram brings in `aiohttp`, `magic-filter` and `aiofiles`. The Dockerfile runs `uv sync --frozen`
(Dockerfile lines 21–28), so the lockfile must be committed.

---

### A3. Settings — `config/tgram_setting.py`

Follow the conventions in `config/waba_setting.py`: module docstring in the house format, `# %%` cells, settings
built from `aws_setting.agent_env`, and a module-level instance. The differences are that the namespace includes the
bot key, the fields are optional, and secrets are `SecretStr`.

#### Secret keys (in the AWS secret loaded at `aws_setting.py:108`, `get_agent_env(secret_name="ordelo-agent-env")`)

| Key | Example | Notes |
|---|---|---|
| `tgram_rest_admin_bot_token` | `123456789:AA…` | From BotFather. For test, use the starter bot's token (`TGRAM_BOT_TOKEN` in `tgram_starter/.env`) (D8). |
| `tgram_rest_admin_bot_username` | `my_ordelo_test_bot` | Without the `@`. Used for deep links later and by the notebook's username check. |
| `tgram_rest_admin_webhook_secret` | `secrets.token_urlsafe(32)` | Must match `[A-Za-z0-9_-]{1,256}`. Use a **new** value, not the starter's, so the starter's secret can't drive the service. |
| `tgram_rest_admin_webhook_base_url` | `https://rider-agent-test.ordelo.app` | No trailing slash. Used only by the notebooks and the `webhook_url` property. |

Local fallback: when a key is missing from the secret, environment variables `TGRAM_REST_ADMIN_BOT_TOKEN` and the
others are read through pydantic-settings' `_env_prefix`. Values from the secret win.

#### Code

```python
"""
Telegram bot settings for OrdeloAgent.
    . Defines TgramBotSettings: per-bot settings read from agent_env keys `tgram_<bot_key>_*`
    . Keys are optional; a bot is enabled only when its token and webhook secret are present
    . Builds aiogram Bot objects at import (no network until first API call)
    . Exposes the restaurant-admin bot used by channels/telegram and notebooks/telegram
    . Depends on: pydantic_settings, aiogram, loguru, aws_setting
  Classes/Functions:
    . TgramBotSettings
    . build_bot
  Module values:
    . REST_ADMIN_BOT_KEY
    . tgram_rest_admin_settings
    . rest_admin_bot
"""

# %%
import re
from typing import Any, Mapping

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.token import TokenValidationError
from loguru import logger
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aws_setting import agent_env

REST_ADMIN_BOT_KEY = "rest_admin"
_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")  # Telegram setWebhook secret_token rule


# %%
class TgramBotSettings(BaseSettings):
    bot_key: str
    bot_token: SecretStr | None = None
    bot_username: str = ""
    webhook_secret: SecretStr | None = None
    webhook_base_url: str = ""

    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("bot_username")
    @classmethod
    def _strip_at(cls, v: str) -> str:
        return v.strip().lstrip("@")

    @field_validator("webhook_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("webhook_secret")
    @classmethod
    def _check_secret(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and not _WEBHOOK_SECRET_RE.match(v.get_secret_value()):
            raise ValueError("webhook_secret must match [A-Za-z0-9_-]{1,256}")
        return v

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.webhook_secret)

    @property
    def path_slug(self) -> str:
        return self.bot_key.replace("_", "-")  # rest_admin -> rest-admin

    @property
    def webhook_path(self) -> str:
        return f"/telegram/{self.path_slug}/webhook"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}" if self.webhook_base_url else ""

    @classmethod
    def for_bot(cls, bot_key: str, env: Mapping[str, Any]) -> "TgramBotSettings":
        """Read `tgram_<bot_key>_*` keys from env (agent_env); empty values count as missing."""
        prefix = f"tgram_{bot_key}_"
        values = {
            k[len(prefix):]: v
            for k, v in env.items()
            if k.startswith(prefix) and v not in (None, "")
        }
        # _env_prefix lets local env vars (TGRAM_REST_ADMIN_BOT_TOKEN, ...) fill gaps; init kwargs win.
        return cls(_env_prefix=prefix.upper(), bot_key=bot_key, **values)


def build_bot(settings: TgramBotSettings) -> Bot | None:
    """Bot for an enabled settings object; None (and one log line) otherwise. Never raises."""
    if not settings.enabled:
        logger.info(f"telegram[{settings.bot_key}]: disabled (token or webhook secret missing)")
        return None
    try:
        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    except TokenValidationError:
        logger.error(f"telegram[{settings.bot_key}]: disabled (malformed bot token)")
        return None
    logger.info(f"telegram[{settings.bot_key}]: enabled -> {settings.webhook_path}")
    return bot


# %%
tgram_rest_admin_settings = TgramBotSettings.for_bot(REST_ADMIN_BOT_KEY, agent_env)
rest_admin_bot: Bot | None = build_bot(tgram_rest_admin_settings)
```

Notes for the implementer:
- `_env_prefix` is a supported pydantic-settings init argument. Check that it works with the pinned
  `pydantic-settings` version. If it doesn't, build a subclass on the fly with `model_config = SettingsConfigDict(env_prefix=...)`.
- Never log `bot_token` or `webhook_secret`. `SecretStr` keeps them out of `repr()`.
- `Bot(...)` validates the token format only. `get_me` is never called at import.
- The rider bot later adds one line: `tgram_rider_settings = TgramBotSettings.for_bot("rider", agent_env)`.

#### `config/__init__.py`

Add the following to `__all__` (lines 2–19) and to the imports (after line 41, `from .wa_location_setting import …`):

```python
__all__ = [
    ...
    "wa_location_settings",
    "TgramBotSettings",
    "tgram_rest_admin_settings",
    "rest_admin_bot",
]
...
from .tgram_setting import TgramBotSettings, tgram_rest_admin_settings, rest_admin_bot
```

---

### A4. Channel adapter — `channels/telegram/`

Composition rule from ADR 0011: each bot gets a **new Dispatcher and a new router tree**. The starter's
module-level `_dp` singleton (`tgram_starter/bot_factory.py:21-35`) and module-level `router = Router(...)`
objects are exactly what we must not copy. aiogram lets a router belong to only one parent, which is why the starter's
tests have to reset `router._parent_router` (`tgram_starter/tests/test_starter.py:265-271`).

#### A4.1 `channels/telegram/errors.py`

This comes from `tgram_starter/bot_factory.py:40-47`:

```python
"""Shared Dispatcher error handlers for every Ordelo Telegram bot."""
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent
from loguru import logger


async def ignore_stale_callback(event: ErrorEvent):
    # A button tap must be answered within ~15s; late/redelivered taps can't be answered any more.
    if "query is too old" not in event.exception.message:
        raise event.exception
    logger.warning(f"telegram: ignoring stale callback query (update {event.update.update_id})")


def register_error_handlers(dp: Dispatcher) -> None:
    dp.errors.register(ignore_stale_callback, ExceptionTypeFilter(TelegramBadRequest))
```

#### A4.2 `channels/telegram/keyboards.py` and `callbacks.py`

- `keyboards.py`: copy `contact_request_kb()` from `tgram_starter/keyboards.py:60-64` without changes. Step 2's
  contact-share linking uses it. Do not copy `main_menu`, `order_offer`, `counter_kb` or the demo `CallbackData`
  classes.
- `callbacks.py`: a docstring stating the convention (one `CallbackData` subclass per action family, a short
  `prefix`, opaque short refs, **64 bytes maximum** after `.pack()`, and authorisation never trusting the packed value),
  plus:

```python
from aiogram.filters.callback_data import CallbackData

CALLBACK_DATA_MAX_BYTES = 64


def fits_callback_limit(data: CallbackData) -> bool:
    return 1 <= len(data.pack().encode()) <= CALLBACK_DATA_MAX_BYTES
```

The first real `CallbackData` class (order accept and the like) arrives with the order actions, not in this step.

#### A4.3 `channels/telegram/rest_admin/commands.py`

```python
"""Restaurant-admin bot command menu (published by notebooks/telegram/tgram_setup_bot.py)."""
from aiogram.types import BotCommand

REST_ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Start / link this chat to your restaurant"),
    BotCommand(command="help", description="What this bot can do"),
    BotCommand(command="whoami", description="Show your Telegram ids and link status"),
]

HELP_TEXT = "<b>Ordelo restaurant bot</b>\n" + "\n".join(
    f"/{c.command} - {c.description}" for c in REST_ADMIN_COMMANDS
)
```

Keep only restaurant commands here. The rider bot later gets its own `rider/commands.py` (ADR 0011: "An unknown
restaurant command must not fall through to a rider graph").

#### A4.4 `channels/telegram/rest_admin/router.py`

Handlers are module-level functions, and `build_router()` registers them on a **new** `Router` each time it's called.
The wording comes from `tgram_starter/handlers/onboarding.py:21-48` and `:67-77` with the invite logic removed.

```python
"""Restaurant-admin bot router factory: deterministic commands only, never a LangGraph agent."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .commands import HELP_TEXT

NOT_LINKED = (
    "Hi! This is the Ordelo restaurant bot.\n"
    "This chat isn't linked to a restaurant yet. Linking is coming soon; "
    "your Ordelo contact will tell you when to press /start again."
)


async def cmd_start(message: Message):
    # Step 2: offer contact_request_kb() and link via restaurant_master.admins.
    await message.answer(NOT_LINKED)


async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


async def cmd_whoami(message: Message):
    u = message.from_user
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        "Ordelo link: not linked",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


async def fallback(message: Message):
    await message.answer("I don't understand that yet. Try /help.")


def build_router() -> Router:
    router = Router(name="rest_admin")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(fallback, F.text)  # last: swallows any other text
    return router
```

Watch out for HTML escaping: `<pre>` content above holds only integers and an escaped username. Any
user-supplied text added later must go through `html.escape` because the Bot defaults to `ParseMode.HTML`.

#### A4.5 `channels/telegram/bots.py`

```python
"""
Telegram bot registry for OrdeloAgent.
    . One TelegramBot (settings + Bot + Dispatcher) per enabled bot_key
    . Fresh Dispatcher and router tree per bot (never shared, never module-level)
    . Built in the FastAPI lifespan; closed on shutdown
  Classes/Functions:
    . TelegramBot
    . build_rest_admin_dispatcher
    . build_registry
    . default_registry
    . find_by_slug
    . close_registry
"""
from dataclasses import dataclass
from typing import Callable, Iterable

from aiogram import Bot, Dispatcher
from loguru import logger

from config.tgram_setting import REST_ADMIN_BOT_KEY, TgramBotSettings

from .errors import register_error_handlers
from .rest_admin.router import build_router as build_rest_admin_router


@dataclass(frozen=True)
class TelegramBot:
    settings: TgramBotSettings
    bot: Bot
    dp: Dispatcher

    @property
    def key(self) -> str:
        return self.settings.bot_key


def build_rest_admin_dispatcher(settings: TgramBotSettings) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_rest_admin_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings  # injected into handlers that declare `tgram_settings`
    return dp


DISPATCHER_FACTORIES: dict[str, Callable[[TgramBotSettings], Dispatcher]] = {
    REST_ADMIN_BOT_KEY: build_rest_admin_dispatcher,
    # "rider": build_rider_dispatcher,  # later phase
}


def build_registry(entries: Iterable[tuple[TgramBotSettings, Bot | None]]) -> dict[str, TelegramBot]:
    registry: dict[str, TelegramBot] = {}
    for settings, bot in entries:
        if bot is None:
            continue
        registry[settings.bot_key] = TelegramBot(
            settings=settings, bot=bot, dp=DISPATCHER_FACTORIES[settings.bot_key](settings)
        )
    logger.info(f"telegram: registry built for {sorted(registry) or 'no bots'}")
    return registry


def default_registry() -> dict[str, TelegramBot]:
    from config import rest_admin_bot, tgram_rest_admin_settings

    return build_registry([(tgram_rest_admin_settings, rest_admin_bot)])


def find_by_slug(registry: dict[str, TelegramBot], slug: str) -> TelegramBot | None:
    return next((b for b in registry.values() if b.settings.path_slug == slug), None)


async def close_registry(registry: dict[str, TelegramBot]) -> None:
    for tg in registry.values():
        await tg.bot.session.close()  # never delete/set the webhook here (handoff §9)
```

Why the Dispatcher isn't in `config` (D9): the handlers will soon import domain modules (`ordelo.*`, `utils_common.*`)
that import `config`. If `config` imported the handlers, that would create a circular import.

---

### A5. Webhook route — `watomation/routers/telegram_webhook.py`

This follows `tgram_starter/app.py:57-74` with these changes: the bot is looked up from the trusted registry by the
path slug, the secret comparison uses bytes, there's a time limit, raw payloads are never printed, and a malformed
update doesn't trigger retries.

```python
"""
Telegram webhook ingress for OrdeloAgent (thin route; logic lives in channels/telegram).
    . POST /telegram/{bot_slug}/webhook, e.g. /telegram/rest-admin/webhook
    . 404 for unknown/disabled bots, 403 for a wrong X-Telegram-Bot-Api-Secret-Token
    . Feeds the update to that bot's own Dispatcher inline with a timeout
    . Always 200 after the secret check: Telegram retries non-2xx and a failing update would loop
    . STEP-1 ONLY: no durable inbox. Must add telegram_inbox before any state-changing handler (ADR 0011).
"""
import asyncio
import secrets

from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from channels.telegram.bots import find_by_slug

router = APIRouter(tags=["telegram"])

HANDLER_TIMEOUT_SECS = 25


@router.post("/telegram/{bot_slug}/webhook", include_in_schema=False)
async def telegram_webhook(
    bot_slug: str,
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    tg = find_by_slug(getattr(request.app.state, "telegram_bots", {}), bot_slug)
    if tg is None:
        raise HTTPException(404, "unknown bot")
    expected = tg.settings.webhook_secret.get_secret_value().encode()
    if not secrets.compare_digest(x_telegram_bot_api_secret_token.encode(), expected):
        raise HTTPException(403, "bad secret")

    payload = await request.json()
    try:
        update = Update.model_validate(payload, context={"bot": tg.bot})
    except ValidationError:
        logger.warning(f"telegram[{tg.key}]: invalid update {payload.get('update_id')}")
        return {"ok": True}

    try:
        await asyncio.wait_for(tg.dp.feed_update(tg.bot, update), timeout=HANDLER_TIMEOUT_SECS)
    except Exception:  # includes TimeoutError
        logger.exception(f"telegram[{tg.key}]: handler failed for update {update.update_id}")
    return {"ok": True}
```

#### `watomation/fapp_ordelo_agent.py` edits

1. Imports (near lines 37–58):
   ```python
   from channels.telegram.bots import close_registry, default_registry
   from watomation.routers import telegram_webhook
   ```
2. Lifespan (currently lines 124–132):
   ```python
   @asynccontextmanager
   async def lifespan(app):
       app.state.telegram_bots = default_registry()
       task = asyncio.create_task(run_sweeper())
       try:
           yield
       finally:
           task.cancel()
           with suppress(asyncio.CancelledError):
               await task
           await close_registry(app.state.telegram_bots)
   ```
3. Router (after line 162, `app.include_router(web_hooks.router, prefix="/web")`):
   ```python
   app.include_router(telegram_webhook.router)
   ```
4. Update the module docstring bullet list ("Serves Telegram webhooks for the restaurant-admin bot").

Do **not** call `set_webhook` or `delete_webhook` in the lifespan. Local and production restarts would fight over
which server owns the webhook (handoff §9; starter `app.py:42`).

---

### A6. Notebooks — `notebooks/telegram/`

Both notebooks use `# %%` cells with top-level `await` (the repo's ruff config already ignores `F704`). Run them from
the repo root with the main `.venv`, `PYTHONPATH="$PWD"` and `.env` loaded with `envLoad`, as in
`docs/local-testing-runbook.md` §1. Importing `config` loads **every** setting, including the WABA clients and
Supabase (see `config/__init__.py`), so `AWS_SETTINGS_*` must be set.

Shared first cell:

```python
# %% 1. Setup
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "channels" / "telegram").is_dir())
sys.path.insert(0, str(ROOT))

from config import rest_admin_bot as bot, tgram_rest_admin_settings as settings  # noqa: E402

assert bot is not None, "rest_admin bot disabled: add tgram_rest_admin_bot_token + _webhook_secret to the secret"
print("bot_key:", settings.bot_key, "| username:", settings.bot_username, "| webhook:", settings.webhook_url or "(base url not set)")
```

#### A6.1 `tgram_setup_bot.py` (from `tgram_starter/notebook_setup_bot.py`)

Header markdown: "Run once per environment or URL change. This hits the REAL Bot API. **The dev bot is shared with
`tgram_starter`** (D8): whichever webhook you set last receives every update."

| Cell | Source in starter | Change |
|---|---|---|
| 1 Setup | cell 1 (lines 15–28) | Use the shared cell above. Optionally `BOT_KEY = "rest_admin"` for when the rider bot exists. |
| 2 Validate token | cell 2 (lines 30–34) | Same. Compare `me.username` with `settings.bot_username`. |
| 3 Current webhook (read-only) | cell 3 (lines 36–40) | Same. |
| 4 **Set webhook** | cell 4 (lines 42–55) | `dp = build_rest_admin_dispatcher(settings)` from `channels.telegram.bots`. `url = settings.webhook_url` (assert it starts with `https://`). `secret_token=settings.webhook_secret.get_secret_value()`. `allowed_updates=dp.resolve_used_update_types()`. `drop_pending_updates=False`. Drop the hard-coded URL. |
| 5 Verify | cell 5 (lines 57–63) | Same; assert `info.url == settings.webhook_url`. |
| 6 Command menu | cell 6 (lines 65–77) | `await bot.set_my_commands(REST_ADMIN_COMMANDS)` from `channels.telegram.rest_admin.commands`. |
| 7 Smoke test | cell 7 (lines 125–131) | `GET {base}/docs` or an existing health route, then `POST settings.webhook_url` with a wrong secret and expect **403**. (OrdeloAgent has no `/health`; pick an existing GET or accept any 2xx/404 for the first call.) |
| 8 **Hand the bot back to the starter** | new | Commented out by default: `await bot.set_webhook(url=STARTER_URL + "/telegram/webhook", secret_token=<starter secret from tgram_starter/.env>, ...)`. Explain that this stops the service receiving updates. |
| 9 Delete webhook | cell 8 (lines 133–135) | Same; stays commented. |
| 10 Cleanup | cell 9 (line 138) | `await bot.session.close()`. |

Drop the starter's cells 6a, 6b and 6c (Mini App preflight, menu button and launch button).

#### A6.2 `tgram_scratchpad.py` (from `tgram_starter/notebook.py`)

Keep, adapted to the shared setup cell:
- Who am I (`bot.get_me()`).
- `CHAT_ID = None  # set your numeric Telegram id (send /whoami to the bot)` followed by an assert. There's no
  admin-ID fallback (D3a).
- Plain and formatted send, reply, edit and delete (starter cells 4, 5 and 5a).
- Draft streaming with `send_message_draft` (starter cell 5b).
- Live tracker edited in place, with `TelegramRetryAfter` backoff (starter cell 5c).
- Any later starter cells that only use `bot` and `CHAT_ID`.

Drop the `order_offer` import and cell, anything calling the starter's HTTP endpoints (`/invites` and `/send`), and
anything Mini App related. Fix the starter's leftover bugs while copying: cell 5a prints `ok` while the delete line is
commented out, and the hard-coded `CHAT_ID = -1004443870717` overrides the default.

---

### A7. Tests

The global `tests/conftest.py` fakes `aws_setting` before any import (`_install_fake_aws_setting`, lines 100–129) using
`_STUB_AGENT_ENV` (lines 53–98). Add:

```python
    # Telegram (restaurant-admin bot)
    "tgram_rest_admin_bot_token": "123456:TEST-token",
    "tgram_rest_admin_bot_username": "test_rest_admin_bot",
    "tgram_rest_admin_webhook_secret": "test-tgram-secret",
    "tgram_rest_admin_webhook_base_url": "https://test.example.com",
```

These keys make `rest_admin_bot` a real `Bot` in tests. No network is used because nothing calls the API during import.

#### A7.1 `tests/channels/telegram/conftest.py`: offline Bot API recorder

```python
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Message


class RecordingSession(BaseSession):
    """Captures outgoing Bot API calls; returns minimal valid results. No network."""

    def __init__(self):
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message.model_validate(
                {"message_id": len(self.calls), "date": 0,
                 "chat": {"id": method.chat_id, "type": "private"}, "text": method.text},
                context={"bot": bot},
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        if False:
            yield b""


@pytest.fixture
def recording_bot():
    session = RecordingSession()
    return Bot(token="123456:TEST-token", session=session), session


def message_update(text: str, user_id: int = 111, update_id: int = 1) -> dict:
    cmd_len = len(text.split()[0]) if text.startswith("/") else 0
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10, "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": "ada"},
            "text": text,
            **({"entities": [{"type": "bot_command", "offset": 0, "length": cmd_len}]} if cmd_len else {}),
        },
    }
```

#### A7.2 Test cases

`tests/config/test_tgram_setting.py`
- `for_bot("rest_admin", env)` reads the prefixed keys, ignores `tgram_rider_*` and unrelated keys, strips `@` from
  the username and `/` from the base URL.
- `enabled` is false when the token or secret is missing or `""`. `build_bot` then returns `None` without raising.
- A malformed token (`"not-a-token"`) gives `build_bot` → `None`.
- An invalid webhook secret (`"has space"`) raises `ValidationError`.
- `webhook_path == "/telegram/rest-admin/webhook"`. `webhook_url` is `""` when no base URL is set.
- `repr(settings)` doesn't contain the token or secret.

`tests/channels/telegram/test_bots.py`
- `build_rest_admin_dispatcher` called twice gives **two different routers**, and building both Dispatchers raises
  nothing. This is the regression guard for the starter's `_dp` singleton problem.
- `build_registry([(settings, None)]) == {}`. With a bot, the key is `"rest_admin"`.
  `find_by_slug(registry, "rest-admin")` finds it, and `find_by_slug(registry, "rider")` is `None`.
- `close_registry` closes each session (use a `RecordingSession` or a mock and assert the call).

`tests/channels/telegram/test_rest_admin_router.py` (feed updates with `await dp.feed_update(bot, Update.model_validate(...))`)
- `/start` → one `SendMessage` whose text contains "isn't linked".
- `/help` → text lists `/start`, `/help` and `/whoami`, and **no** starter commands (`/menu`, `/invite`, `/app`).
- `/whoami` → contains `from_user.id` `111` and "not linked". A username with `<b>` is escaped.
- Free text → the fallback reply.

`tests/watomation/routers/test_telegram_webhook.py`: build a **small** FastAPI app containing only
`telegram_webhook.router`, and set `app.state.telegram_bots` to a registry built from a `recording_bot`. Don't
import `fapp_ordelo_agent` here; it pulls in the whole app.
- Unknown slug → 404. An empty registry (bot disabled) → 404.
- Missing or wrong secret → 403. A non-ASCII header doesn't raise.
- Valid secret with `/start` → 200, and the session recorded one `SendMessage`.
- Valid secret with `{"update_id": 5, "message": "garbage"}` → 200 and a warning logged.
- A handler that raises (monkeypatch `tg.dp.feed_update` to raise) → 200 and an exception logged.
- `HANDLER_TIMEOUT_SECS` reached (monkeypatch it to `0.01` and use a slow `feed_update`) → 200.

`tests/test_smoke_imports.py`: add `"config.tgram_setting"`, `"channels.telegram.bots"`,
`"channels.telegram.rest_admin.router"` and `"watomation.routers.telegram_webhook"` to the parametrised list
(around lines 22–60).

Commands: `pytest tests/config tests/channels tests/watomation/routers/test_telegram_webhook.py tests/test_smoke_imports.py`,
then `pytest` and `ruff check .`. The starter's own tests (`tgram_starter/tests/`) aren't part of the main run.
`[tool.pytest.ini_options].testpaths = ["tests"]` already excludes them.

---

### A8. Documentation edits (in the same change)

**ADR 0011** (`docs/adr/0011-...md`). Add a dated "Amendment — 15 Oct 2026 (step-1 scaffold)" section rather
than rewriting the text:
1. The settings file is `config/tgram_setting.py` (not `telegram_setting.py`). Keys are `tgram_<bot_key>_*`, optional,
   and a bot is enabled only when its token and secret are present.
2. The restaurant-admin bot key is `rest_admin` and its route is `/telegram/rest-admin/webhook`.
3. "Startup construction must become explicit": aiogram `Bot` objects are built when `config` is imported, because
   building one opens no connection and the pattern matches `_async_wa_client`. Dispatchers and routers are built in
   the FastAPI lifespan through `channels/telegram/bots.py`, and sessions close on shutdown.
4. Restaurant-admin identity: link by shared contact (`contact.user_id == from_user.id`), with the phone checked
   against `restaurant_master.admins`. Restaurant-admin onboarding doesn't use invites.
5. Step 1 handles updates inline without an inbox. The inbox stays a gate before any action that changes state.
6. Test environment: the starter's dev bot doubles as the restaurant-admin test bot until a dedicated bot is created.

**CONTEXT.md**: add two short entries in the existing style:
- **Restaurant-admin bot**: the Telegram bot (`bot_key=rest_admin`) that restaurant admins use for order actions
  and notifications. It is deterministic and never runs a LangGraph agent. It sits alongside WhatsApp; it is not a
  customer channel.
- **Telegram identity**: the link from a Telegram account (`telegram_user_id`, `chat_id`) to an Ordelo principal. For
  restaurant admins that principal is a phone number in `restaurant_master.admins`. A Telegram identity only
  authenticates; restaurant membership is still checked on every action.

**docs/local-testing-runbook.md**: add a short "Telegram restaurant-admin bot" section after §4 (tunnel):
point the dev bot's webhook at `<tunnel>/telegram/rest-admin/webhook` with `notebooks/telegram/tgram_setup_bot.py`
cell 4, restore it with the same cell using the test or prod base URL, and warn that the bot is shared with
`tgram_starter`.

---

### A9. Next step: restaurant-admin linking

> **Superseded 15 Oct 2026.** Linking was built as an invite flow (`t_invites`, `/start <code>` with a
> confirmation tap) and the contact-share design below was dropped. See the "Restaurant-admin identity (revised)"
> bullet in the ADR 0011 amendment, `ordelo_datamodels/migrations/create_t_invites.sql` and
> `channels/telegram/invites.py`. The text below is kept for history.

This is here so the scaffold doesn't paint itself into a corner:
1. `/start` (not linked) → reply with `contact_request_kb()` (already in `channels/telegram/keyboards.py`).
2. `F.contact` handler: reject if `contact.user_id != from_user.id` (same check as
   `tgram_starter/handlers/onboarding.py:52-58`). Normalise the phone to digits only, which is how `rider_id` and
   admins are stored today.
3. Look for that phone in `restaurant_master.admins` across restaurants. Supabase REST is **synchronous**, so wrap it
   in `asyncio.to_thread()` (CLAUDE.md rule). If there's no match → "Number not registered with any restaurant".
4. Upsert `telegram_identities(bot_key, telegram_user_id, telegram_chat_id, phone, username_snapshot, linked_at,
   revoked_at)` with a unique `(bot_key, telegram_user_id)` constraint. New migration in
   `ordelo_datamodels/migrations/`.
5. Authorise every action by re-checking `restaurant_master.admins` (removing the phone revokes access) and never
   trusting `chat_id` or callback data alone (ADR 0011 decision 5).
6. Before the **first action that changes state** (order accept, pickup time, ready): build `telegram_inbox`
   (persist and deduplicate `(bot_key, update_id)` before replying 200, then claim and complete through a recoverable
   worker) per ADR 0011 "Acknowledgement and durable work".

---

### A10. Operator steps (manual; the implementing agent must not do these)

1. Generate a new webhook secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Add the four `tgram_rest_admin_*` keys (§3) to the AWS secret that the **test** deployment loads, using
   `upload_secrets.sh` or the `aws secretsmanager update-secret` recipe in the `aws_setting.py` docstring. Use the
   starter bot's token and username (D8).
   - **Open check:** `aws_setting.py:108` hard-codes `ordelo-agent-env`. If test and prod read the same secret, prod
     also gets the dev bot token. That's harmless while the webhook points at the test URL, but decide before the
     production bot exists. A separate secret or a deploy-time `secret_name` may be needed.
3. Deploy to test, then run `notebooks/telegram/tgram_setup_bot.py` cells 1–7.
4. In Telegram, send `/start`, `/help` and `/whoami` to the bot and check the replies.
5. To use the starter again, run cell 8 (hand the bot back) and reverse it afterwards.

---

### A11. Implementation order and acceptance checklist

1. [x] `pyproject.toml` + `uv lock` + `uv sync`. Confirm `python -c "import aiogram; print(aiogram.__version__)"` prints `3.31.0`.
2. [x] `config/tgram_setting.py` and the `config/__init__.py` exports. Write `tests/config/test_tgram_setting.py` first (TDD).
3. [x] `tests/conftest.py` stub keys, then add the smoke-import entries.
4. [x] `channels/telegram/{errors,keyboards,callbacks}.py`, `rest_admin/{commands,router}.py`, `bots.py`, with the router and bots tests.
5. [x] `watomation/routers/telegram_webhook.py` and its tests. Then edit `fapp_ordelo_agent.py` (lifespan + `include_router`).
6. [x] `uv run watomation/fapp_ordelo_agent.py` locally with **no** Telegram keys: the app starts, logs
       `telegram[rest_admin]: disabled`, and `POST /telegram/rest-admin/webhook` returns 404. WhatsApp routes work as before.
7. [x] Same run with the keys exported as `TGRAM_REST_ADMIN_*` env vars: a curl with the wrong secret gets 403, and a
       curl with the right secret and a `/help` update gets 200 (send it to your own chat id, or check that the
       handler ran and failed on the network with the error logged).
8. [x] The two notebooks; run cells 1–3 against the dev bot (read-only).
9. [x] Doc edits (§8).
10. [x] `pytest`, then `ruff check .`, then `git diff --stat -- tgram_starter/` shows **no changes**.

**Done when:** all tests pass, the app starts with and without Telegram keys, the dev bot answers `/start`, `/help`
and `/whoami` through the test deployment, `tgram_starter/` is byte-for-byte unchanged, and nothing in production
code imports `tgram_starter`.
