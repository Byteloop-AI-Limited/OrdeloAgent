# Ordelo — Telegram Operational Messaging Migration
## Implementation-agent handoff | Updated 15 October 2026

> **Purpose:** Complete context and actionable implementation guidance for migrating **rider and restaurant operational coordination** from WhatsApp Business Platform (PyWA) and/or Raspberry Pi thermal printers toward **Telegram Bot API + aiogram 3**, while keeping the existing customer-facing WhatsApp and web ordering journeys intact. This is a handoff of discussion, proposed design, sample patterns, constraints, and decisions. It is **not** a claim that the target functionality has been implemented in the codebase.

> **Session review — 14 October 2026:** Read [proposed ADR 0011](adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) for the consolidated repository recommendation and ownership rules. **Two bots are now decided:** a restaurant-admin bot for deterministic order actions and delivery notifications (no agent), and a rider bot using the existing LangGraph agent. Give each its own commands, handlers, token, webhook secret and Dispatcher while sharing Ordelo's domain modules. `tgram_starter/` is a learning reference, not the production implementation.
>
> **Sequencing decision — 15 October 2026:** Implement the **restaurant-admin bot first**, including deterministic order actions and restaurant-facing delivery notifications. Rider migration, graph refactoring and thread changes are deferred. [ADR 0012](adr/0012-rider-threads-follow-dispatch-assignments.md) records the selected later thread design: `ordelo:rider:dispatch:<dispatch_id>`, one conversation per assigned dispatch. This is a design decision, not current behaviour. Phase one requires no rider thread/checkpoint migration.
>
> The discussion below includes later capabilities and historical examples. Multiple simultaneous rider deliveries, restaurant rejection, post-Accept pickup reminders, live-location storage and printer retirement remain separate decisions. Preserve accepted ADRs 0001–0010; do not infer a change to timeout, capture or print behaviour from examples below. Durable ingress and reminder recovery must follow ADR 0011.

## 0. Read first — goals, constraints, and status

### Business objective
- Ordelo is an early-stage UK restaurant ordering / last-mile delivery product. Customer ordering currently involves WhatsApp and an evolving Next.js web flow.
- The **high messaging volume being discussed is NOT customer messaging**. It is operational messaging with a **small, defined set of riders and restaurant administrators** bound by business agreements.
- Current coordination uses WhatsApp Cloud API, where one paid utility template can trigger a user's reply and a 24-hour customer-service window; subsequent operational messages were previously free. Meta's October 2026 price changes make the ongoing volume costlier.
- Raspberry Pi + thermal printer installations were explored to give restaurants physical notice of orders. The owner now specifically wants to **avoid their purchase, accessories, shipping, setup and support cost**, and investigate Telegram instead, with **repeat order alerts until restaurant acknowledgement**.
- **Most restaurant administrators use Android.** This increases flexibility for a possible future native alarm app, but does NOT make Telegram push notifications equivalent to a guaranteed repeating alarm.
- Riders number around 20 initially. The operator already maintains their **mobile numbers and internal rider references**, but **not their Telegram user IDs**.
- The user already knows PyWA and decorator-based webhook handlers; design should be idiomatic aiogram, concise and production-oriented.

### Explicit architectural preference
- **Existing FastAPI + Supabase + LangGraph stays the system of record and orchestration layer**. Telegram is a messaging/interaction transport. Reuse existing services, job assignments, authorisation, sessions and agent graph rather than clone them.
- Preserve customer WhatsApp/web ordering. Telegram addresses **rider dispatch + restaurant operational communication**, not a forced customer migration.
- **First implementation phase: restaurant admins only.** Cover onboarding, commands, acceptance, pickup-time/ready actions, delivery notices and durable acknowledgement reminders. Preserve fulfilment events that notify the existing assigned-rider graph; the restaurant bot itself has no agent.
- **Later rider phase:** index each offer's root Telegram message; initialize one LangGraph thread per **confirmed assigned dispatch**, using ADR 0012. Replies belong to that conversation, separate from Telegram's persistent private chat. An unaccepted offer needs no graph.
- Human operator takeover of a rider/job conversation remains a later requested capability; its surface and implementation are outside the restaurant-admin phase.

### Essential caveats / unresolved choices
1. **Notification reliability is the biggest risk.** Bot messages can be repeated; Telegram, Android and user settings can still mute, batch or suppress audible alerts. A Telegram Mini App can loop audio while visible/active but is **not a reliable background/locked-screen alarm**.
2. **Two bots confirmed in the session:** `Ordelo Rider Bot` and `Ordelo Restaurant Bot`, with separate commands, tokens, webhook secrets and dispatchers in the same backend. The restaurant bot has no LangGraph agent.
3. **One bot token has one active Telegram webhook URL at a time.** For everyday local tests use a separate dev bot rather than temporarily stealing live production updates.
4. **Verify product- and provider-specific WhatsApp prices with the live Meta rate card and invoices.** Numbers below are illustrative analysis, not a guaranteed ROI calculation.
5. Whether restaurants can keep Telegram audible and responsive during peak hours must be tested in live conditions before committing to remove printers.

---

## 1. Source discussion: WhatsApp pricing, costs and decision

### WhatsApp message categories and the previous pattern
- **Utility template:** approved message, usable outside a customer's 24-hour service window; rider/restaurant clicks a quick reply to reopen a window.
- **Service/free-form message:** non-template bot or operator reply inside the 24-hour user-initiated window; includes supported text, media and interactions.
- **Marketing template:** separate category for promotions, not the central operational use case.
- **Free entry point:** qualifying Click-to-WhatsApp Meta ad or eligible Facebook Page entry, not a normal `wa.me` hyperlink from Ordelo's own website. Sending a utility template containing a URL that leads to `wa.me` **does not** manufacture a free-entry attribution. Qualifying window duration/terms are subject to Meta's current documentation; previously discussed as 72h, with reports of later changes; do not hard-code either without verification.

### Historical observed dashboard values (1–12 October 2026)
The screenshot and conversation indicated approximately:

| Indicator | Value |
|---|---:|
| Messages sent | 1,058 |
| Delivered | 1,030 |
| Utility delivered | ~343 |
| Service delivered | ~687 |
| Free customer-service messages | ~688 |
| Charged utility | ~342 |
| Charges shown | £5.44 |
| Free-entry-point messages | 0 |

Counts vary slightly by dashboard aggregation/rounding. The implied billed utility rate was about `£5.44 / 342 ≈ £0.0159` per delivered message. UK list prices discussed: utility and service (after free allowance) approximately £0.0159, marketing approximately £0.0458. As understood from October 2026 pricing updates, first 1,000 service messages **per business phone number per month** are free, additional service messages billed; in-window utility templates are billed. Confirm directly from Meta billing and pricing webhooks. Recipient-country mix, currency, tiering, taxes and provider fees can change totals.

### Extrapolation already discussed
For a **31-day** month, using 12-day observed counts:
- Baseline utility: `343 × 31 / 12 ≈ 886` delivered.
- Baseline service: `687 × 31 / 12 ≈ 1,775` delivered.
- With user's **new scenario** (`utility 3×`, `service 2×`): about **2,658 utility** and **3,550 service** messages/month.
- Assuming 1,000 free service messages and £0.0159 for each chargeable utility/service message: **(2,658 + 3,550 − 1,000) × £0.0159 ≈ £82.81/month excl. VAT**; approximate annual £994, with static volume and prices. Source discussions used rounded quantities, so use this as a scenario only.
- Migration economics also include onboarding friction, alert failures, Telegram operational maintenance, any fallback messaging, and potentially the cost of a native application. Standard Telegram Bot API calls are generally free within applicable rate limits; do not assume unlimited throughput.

**Reference:** https://business.whatsapp.com/products/platform-pricing

---

## 2. Telegram adoption and rollout positioning

- Telegram is **unusual but not inherently inappropriate** for UK restaurant operations. A fixed, contracted network is far easier to onboard than arbitrary customers.
- **Riders:** relatively good candidates for Telegram: offers, accept/decline, pickup and delivery codes, location-sharing, coordination.
- **Restaurants:** more hesitant because of existing Deliveroo/Just Eat/POS workflows, shift handovers and notifications; usability and missed-order rate matter more than whether Telegram looks unconventional.
- Do **not** tell the implementation agent to build a new customer Telegram checkout. Existing WhatsApp/Next.js journeys remain.
- First-phase pilot recommendation: 2–3 Android-heavy restaurants for 1–2 weeks. Test locked screens, backgrounded app, muted/battery-saver/DND conditions, peak loads, multiple staff, internet outages. Monitor `ack latency`, `% ack ≤30/60/120s`, misses, escalation count, stale offline delivery, satisfaction and manual fallback use. Plan a separate rider pilot when the deferred rider work is ready.
- Suggested success target from discussion: **95% acknowledged within 60s**, explicitly a *proposed internal target*, not an industry guarantee.
- Two separate bots are decided; build the restaurant-admin bot first and the rider bot later.

---

## 3. Target platform architecture

This is the eventual architecture. The first phase implements the restaurant
branch and preserves its fulfilment events into the existing rider workflow.
The rider Telegram branch and graph changes are deferred.

```text
Customer WhatsApp (PyWA) ───┐
Customer Next.js web UI ────┼──── Existing FastAPI domain services ── Supabase
                            │          │  order / dispatch / auth
Rider Telegram Bot ─ aiogram┤          ├── LangGraph delivery agents/checkpoints
Restaurant Telegram ───────┘          ├── notification scheduling/escalation
                                       └── manual operator control

Telegram API  ── webhook HTTPS ── FastAPI ── aiogram Dispatcher/Router
Telegram Bot  ── outbound bot.send_message / edit_message / answer_callback_query
Admin Telegram group or forum topics ── same bot ── human relay
Next.js Telegram Mini App (optional, active-screen restaurant UI)
```

Historical illustrative modules (not the repository layout to implement):

```text
app/
  main.py
  api/orders.py
  api/telegram_webhooks.py
  domain/orders.py
  domain/dispatch.py
  domain/conversation_router.py
  notifications/outbox.py
  notifications/escalation_worker.py
  messaging/telegram/
    bot_registry.py
    router_rider.py
    router_restaurant.py
    router_admin.py
    callbacks.py
    keyboards.py
    onboarding.py
    message_index.py
    sender.py
  messaging/whatsapp/pywa_adapter.py
  agents/delivery_graph.py
  persistence/supabase.py
scripts/telegram_webhook.py
```

Use **ADR 0011's repository layout** for implementation: thin routes under
`watomation/routers/`, the Telegram adapter under `channels/telegram/`, and
domain modules under `ordelo/`. Build only the restaurant-admin portion in
phase one. **Do not duplicate Supabase schema unnecessarily**; adapt mappings
to real tables and identifiers. Retain domain services as the authority for
state changes.

---

## 4. aiogram core implementation patterns

These are API illustrations, not production scaffolding. Rider examples are
for the deferred rider phase. Production ingress follows ADR 0011's durable
receipt/recovery contract and existing repository conventions.

Install (sample):

```bash
uv add aiogram fastapi 'uvicorn[standard]' pydantic-settings
```

### A. FastAPI webhook

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
# dp.include_router(restaurant_router)  # first phase

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await bot.session.close()  # do NOT register/clear webhook on every restart

app = FastAPI(lifespan=lifespan)

@app.post('/telegram/restaurant/webhook')
async def tg_update(payload: dict,
                    x_telegram_bot_api_secret_token: str | None = Header(None)):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(403, 'Invalid Telegram webhook secret')
    update = Update.model_validate(payload, context={'bot': bot})
    await dp.feed_update(bot, update)
    return {'ok': True}
```

This is a compact example, **not** the final design for two bots. In production, implement per-bot token, secret, dispatcher and route, delivery idempotency, short webhook turnaround and background durable processing. `feed_update` may execute long-running handlers inline; queue substantive work and acknowledge quickly where appropriate. Protect against replays and duplicate updates (`update_id`/logical event id).

### B. Typed callback data — PyWA equivalent

```python
from enum import Enum
from aiogram.filters.callback_data import CallbackData
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

class Decision(str, Enum):
    ACCEPT = 'accept'
    DECLINE = 'decline'

class JobAction(CallbackData, prefix='job'):
    job_ref: str
    action: Decision

def offer_keyboard(job_ref: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='✅ Accept',
            callback_data=JobAction(job_ref=job_ref, action=Decision.ACCEPT).pack()),
        InlineKeyboardButton(text='❌ Decline',
            callback_data=JobAction(job_ref=job_ref, action=Decision.DECLINE).pack()),
    ]])

router = Router()

@router.callback_query(JobAction.filter())
async def on_job_action(query: CallbackQuery, callback_data: JobAction):
    await query.answer()  # clear client's spinner promptly
    # verify query.from_user.id maps to invited, authorised rider
    # validate offer is currently active and belongs to this rider
    # atomically accept/decline via dispatch service, never solely by callback string
    ...
```

- `CallbackData.filter()` automatically unpacks typed fields. Callback payload limit **64 bytes**; store opaque short refs/tokens if needed.
- `query.message.edit_text` can update state, but account for inaccessible/deleted messages.
- On Telegram, inline buttons produce `callback_query`; **request_location** is a **reply keyboard** and produces a `Message`, not a callback query.

### C. One-off GPS request

```python
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

kb = ReplyKeyboardMarkup(keyboard=[[
    KeyboardButton(text='📍 Share my location', request_location=True)
]], resize_keyboard=True, one_time_keyboard=True)
await message.answer('Share your collection location', reply_markup=kb)

@router.message(F.location)
async def location_received(message):
    loc = message.location
    # bind to authorised rider and correct active delivery context
    # persist lat/lon/timestamp and strip the reply keyboard
    await message.answer('Location received', reply_markup=ReplyKeyboardRemove())
```

### D. Telegram live location

```python
@router.message(F.location)
async def initial_location(message):
    await save_location(message.from_user.id, message.location,
                        source_message_id=message.message_id)

@router.edited_message(F.location)
async def updated_live_location(message):
    await save_location(message.from_user.id, message.location,
                        source_message_id=message.message_id)
```

Use one consolidated router/handler per update type (above snippets are alternatives, don't register duplicate overlapping `F.location` handlers). Bot can request one-off location via a keyboard, but **cannot force the user to start sharing live GPS**. Rider must explicitly use Telegram's Share Live Location control; edited-message updates, if delivered, are routed to current active job. Location frequency is not guaranteed, especially in background. Account for expiry, consent, stale locations and multiple job ambiguity. Obtain appropriate location privacy policy/retention rules.

### E. Sending outbound jobs

```python
sent = await bot.send_message(
    chat_id=rider_telegram_chat_id,
    text=f'🚴 Delivery {job_ref}: collect from {restaurant_name}',
    reply_markup=offer_keyboard(dispatch_id),
)
await save_job_root(chat_id=sent.chat.id, message_id=sent.message_id,
                    dispatch_id=dispatch_id, job_ref=job_ref, rider_ref=rider_ref,
                    langgraph_thread_id=None)  # initialized only after assignment
```

Use `chat_id` for **delivery destination**, `from_user.id` for **identity**, `message_id` for **in-chat reference**, and your own `langgraph_thread_id` for agent state. Don't store only a `message_id`: it is scoped to a chat.

Docs: https://docs.aiogram.dev/ , https://core.telegram.org/bots/api

---

## 5. Rider onboarding, Telegram identity and chat persistence

### How riders discover bot
- WhatsApp WABA is represented by a phone number; Telegram bot by its **username** (`@OrdeloRiderBot` is illustrative, availability not checked) and `https://t.me/<username>` link; QR optional.
- Bot cannot infer a user's Telegram user ID from a known phone number and **cannot initiate a private chat until the rider starts the bot**.
- Operators already have rider phone numbers: send individual, short-lived **one-time deep links** via existing WhatsApp/SMS/email:
  `https://t.me/<rider_bot_username>?start=<opaque_invite_token>`.
- `start` deep-link payload has Telegram syntax/length constraints; use short base64url-safe random token, stored hashed if possible. Bind to internal rider ref; one-time atomic claim with expiry; reject wrong/used invitations; optionally require `request_contact=True` and verify `contact.user_id == from_user.id` if verifying the rider's own mobile number.
- Rider must press Start; parse with `CommandStart()` and `CommandObject.args`.

```python
from aiogram.filters import CommandStart, CommandObject

@router.message(CommandStart())
async def start(message, command: CommandObject):
    invite_token = command.args
    if not invite_token:
        # existing verified rider: greet / menu; unknown rider: request invite
        return
    await claim_invite_atomically(
        token=invite_token,
        telegram_user_id=message.from_user.id,
        telegram_chat_id=message.chat.id,
    )
```

### Persistence semantics

| Field | Meaning | Stability |
|---|---|---|
| `rider_ref` | Ordelo internal rider key | Stable per internal record |
| `telegram_user_id` | Telegram account identifier | Stable for same Telegram account; may differ if account deleted/recreated |
| `telegram_chat_id` | Where the bot messages rider | Stable for same private bot chat; typically equals user ID |
| `telegram_username` | Optional public handle | Mutable; not authoritative identity |
| `telegram_message_id` | Specific job/message | Distinct per sent message; scoped to chat |
| `langgraph_thread_id` | Later rider graph's assigned-dispatch conversation | `ordelo:rider:dispatch:<dispatch_id>` (ADR 0012) |

- `/start` again **does not reset** Telegram chat ID or user ID for the same account. Don't create new rider record or discard active threads when it is used again.
- Replacing phone number on the **same Telegram account** normally retains Telegram IDs; deleting account/re-registering can change them. Blocking the bot causes sending errors, not a fresh chat ID.
- Group IDs and topic IDs have different semantics; group→supergroup migrations can change chat ID. Store chat IDs as BIGINT or text safe for large Telegram IDs; JS should avoid numeric precision issues if values ever grow beyond safe range.
- In one-to-one conversation, `telegram_chat_id` is the target for `bot.send_message` and `telegram_user_id` is the actor for authorization checks.

---

## 6. Dispatch conversations, reply chains, and LangGraph — deferred rider phase

**Selected design, not implemented:** use `ordelo:rider:dispatch:<dispatch_id>`,
for example `ordelo:rider:dispatch:84217`. [ADR 0012](adr/0012-rider-threads-follow-dispatch-assignments.md)
contains the full lifecycle, concurrency, debug and source-impact review.
One rider private chat can contain histories from several assignments, each
with its own root message and distinct graph thread. This does not enable
multiple simultaneous deliveries. The restaurant-admin phase needs no graph.

Telegram `from_user.id` identifies the actor and `chat.id` the destination;
both map through the adapter to the existing internal rider identity. The
dispatch binds that rider to an order/assignment attempt. A compact callback
such as `rd1:84217:accept` carries the action and dispatch reference; after
authorization/state validation, derive the stable thread ID. Do not use the
whole packed callback as the thread ID: other actions must share the history.

```text
rider private chat (chat_id=123456789)
  message 501: assigned job A instructions   ↔ graph thread A
  message 502: reply to message 501          ↔ graph thread A
  message 503: bot reply to message 501      ↔ graph thread A
  message 524: assigned job B instructions   ↔ graph thread B
  message 525: rider reply to message 524    ↔ graph thread B
```

- For bot replies use `ReplyParameters(message_id=root_message_id)` along with `chat_id`.
- For inbound `Message`, `message.reply_to_message.message_id` points to **the immediate message being replied to**, which may not be the root. Therefore index **every job-related sent and received `(chat_id, message_id)` to the job/thread**. A rider replying to message 503 must still resolve thread A.
- For callbacks, use short offer/job ID in `callback_data`, validate that original user owns the offered action, then derive thread id from DB.
- For inbound text **without a reply**, route only if there is one unambiguous eligible conversation; otherwise ask the rider to choose. Cancellation-reason capture for an old dispatch can overlap a new job's conversation without allowing two active deliveries. Never silently choose the latest thread.
- Chat ID persists across jobs; **never** equate Telegram chat to LangGraph thread.
- For initial broadcast offers, index each rider's dispatch/message independently, with no graph required yet. Resolve acceptance/assignment atomically, then initialize only the confirmed winner's thread. Duplicate initialization must not repeat instructions or effects. Respond gracefully to stale callbacks and edited/deleted messages.
- Persist inbound/outbound messages in the conversational record as needed (human takeover and agent re-entry). Do not rely on Telegram as the durable store of agent history.
- Pass the exact thread through graph updates, invocation, alert cleanup and closure; never re-resolve by recipient midway. Serialize work per thread. Debug reads must select the exact thread without creating or touching it. Preserve historical IDs and customer/WEB thread lifecycles.

Example reply:

```python
from aiogram.types import ReplyParameters
await bot.send_message(
    chat_id=job['telegram_chat_id'],
    text='Please confirm collection.',
    reply_parameters=ReplyParameters(message_id=job['root_message_id']),
)
```

Keep a mapping from the newly returned outbound `sent.message_id` to the same LangGraph thread. `reply_to_message` may not always be available (e.g. removed/restricted messages), hence fallback context selection.

---

## 7. Human-in-the-loop: operator takeover without changing rider chat

**Later rider capability; outside phase one.** The control surface and delivery
scope require their own implementation planning.

- User needs an operator to **take control of a specific delivery conversation**, reply directly to the rider, then hand back to LangGraph.
- Bot can't impersonate a personal human Telegram account. Operator types in **private Ordelo Operations group/forum topic** or Next.js support dashboard; backend **sends through the same Rider Bot**. Rider's `chat_id` and bot identity stay unchanged.
- Maintain control **per rider-job LangGraph thread**, not per private Telegram chat. States: `AGENT`, `HUMAN`, `RESOLVED`; optional `PENDING_HANDOFF` / `ESCALATED`.
- Operator takeover: authorise operator, atomically change state and `assigned_operator_id`, store version/generation. Block/suppress already-running agent results from publishing after takeover (read state immediately before send; use per-thread leases/fencing if required).
- In HUMAN mode, relay rider messages into operations group with job/rider context. Operator replies in group are mapped to job. Send through bot using original root message as `ReplyParameters`, add all new messages to mapping and LangGraph-accessible history.
- Release: explicitly return mode to AGENT; restore graph with latest human/rider dialogue in context; ensure no duplicate next-step execution.

### Group versus forum topics
- **Simple group:** bot publishes incoming rider messages to an operations group and maps `(ops_chat_id, ops_message_id)` → delivery thread. Operator **replies** to relayed message; handler verifies `from_user.id` belongs to the operators allow-list. Telegram bot privacy mode and group permissions must be configured so reply messages reach bot.
- **Forum topics:** optional supergroup with one topic per active delivery thread. Store group `chat_id` + topic `message_thread_id` → LangGraph thread. Group topics can improve operator UX; consider topic creation/archival limits, staff visibility and sensitive customer addresses.
- Avoid blindly forwarding/copying PII to a broadly accessible group. Least privilege, redaction, retention, audit logs.

Pseudo handler:

```python
@router.message(F.chat.id == OPS_CHAT_ID, F.reply_to_message)
async def ops_reply(message, bot: Bot):
    await assert_authorised_operator(message.from_user.id)
    thread = await resolve_ops_message(
        ops_chat_id=message.chat.id,
        replied_to_message_id=message.reply_to_message.message_id,
    )
    if thread and thread['mode'] == 'HUMAN':
        sent = await bot.send_message(
            chat_id=thread['rider_chat_id'],
            text=message.text,
            reply_parameters=ReplyParameters(message_id=thread['root_message_id']),
        )
        await index_outbound(sent, thread)
```

Note: this is an illustrative partial handler; production must handle non-text/media, correct privacy settings, operator conflict, outgoing failures, idempotency and audit.

---

## 8. Restaurant order notifications: repeated pings until acknowledgement

**The reason for considering Telegram in place of the Raspberry Pi printer is to get staff attention for new orders with repeated pings.** This is a major requirement, not a nice-to-have.

Suggested lifecycle:

```text
Order becomes eligible for manual acknowledgement → durable pending record
→ Bot sends initial order with supported acknowledgement actions
→ after 20–30s without ACK: reminder notification
→ repeat at configured interval (e.g. 30s), limited to avoid spam/rate limits
→ escalate after ~90s to owner / additional staff / ops
→ authorized acknowledgement or terminal order state → atomic transition
→ stop initial-acknowledgement reminders / update original messages
```

Use ADR 0011's stage-specific stop rules: acknowledging the order and providing
a missing pickup time are distinct. Post-Accept pickup reminders are a separate
policy decision. This example does not add a Reject button, alter timeouts or
override configured-auto suppression. Reminder timings below are proposals.

- Important difference: `disable_notification=False` asks for normal notification only. It **does not force an alarm** or override mute, DND, battery settings or notification batching.
- Implement retries with **durable schedule/outbox**, not per-request `asyncio.create_task` or in-memory `pending_orders` for production; application/server restarts must not lose alerts, duplicate them, or keep pinging an already-accepted order.
- Multiple staff should receive the notification; first valid acknowledgement wins and other staff notifications are updated/marked resolved. Authorize staff by restaurant; avoid duplicate acceptance across devices.
- Consider precise stop rule: *received*, *opened/read* and *accepted* differ. Telegram bots do not expose dependable read receipts for arbitrary private chat messages. **Acceptance callback in backend** is definitive.
- Consider status after rejection, unreachable/blocked bot, staff not on shift, connectivity loss, TTL, shift handover, owner escalation, auto-cancel/ops alert and eventual fallback channel.
- Keep configurable reminder intervals and maximum attempts (e.g., 20s first, subsequent 30s, escalation 90s) as *pilot settings*, not hard-coded platform guarantees.

### Android onboarding checklist
- Telegram notifications allowed; high/alerting priority where OS and app allow.
- Distinct sound for Ordelo Restaurant Bot; test volume and notification channels.
- Disable aggressive battery optimisation for Telegram where possible; allow appropriate background activity.
- Lock-screen notifications enabled.
- DND exceptions only if user explicitly agrees and OS supports it.
- Test muted chat, app swiped away, locked screen, battery saver, background, offline/reconnection, multiple notifications in short succession and different manufacturer devices.

### Telegram Mini App experiment
- Next.js webview opened from Telegram bot, with an order list, supported restaurant actions and Supabase Realtime/WebSocket subscriptions; no new Reject policy is implied.
- `new Audio(...).loop = true` (or Web Audio) can provide a **continuous alarm while Mini App is open/active** following an explicit user gesture to unlock audio/autoplay.
- **Cannot guarantee background/locked-screen playback.** Home-screen shortcut does not grant native Android foreground-service capability. Don't treat this as equivalent to printer or dedicated order terminal.
- If unacceptable pilot miss rate: consider small **Android native/Capacitor companion**, FCM notification channels + permissible foreground service / full-screen flows subject to Android's modern OS restrictions and permissions. Still no unconditional guarantee through mute/DND. A conventional PWA has similar background audio limitations.

---

## 9. Local Telegram webhook testing and switching

- Telegram bot supports exactly **one active webhook per bot token**. `setWebhook` replaces current endpoint **immediately**; `getWebhookInfo` inspects it.
- Use the [local testing runbook](local-testing-runbook.md) for the actual FastAPI port and tunnel. Phase-one examples below target `<base>/telegram/restaurant/webhook` with a dedicated restaurant dev bot; rider webhook setup is deferred.
- Do **not** automatically call `set_webhook` in FastAPI lifespan/startup: local and production restarts will fight over ownership.
- `drop_pending_updates=False` avoids deliberately dropping queued updates, but webhook switch can still race with in-flight events. Proper idempotency required.
- For a live bot, **all** incoming updates go to local during test, including actual staff updates; use **separate test bot tokens** for development.

```bash
# Inspect current URL and errors (ensure BOT_TOKEN is securely populated)
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | jq

# Switch to local tunnel
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${TUNNEL_BASE}/telegram/restaurant/webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "drop_pending_updates=false"

# Restore production
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${PROD_BASE}/telegram/restaurant/webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "drop_pending_updates=false"
```

- Build `scripts/telegram_webhook.py {status,local,prod} --url ...`, using aiogram `Bot.get_webhook_info()` and `Bot.set_webhook()`. Restore exact production `allowed_updates`, secret and other relevant webhook options, not just URL. Store secret safely; avoid printing token in logs/CLI traces.
- For fast dev without public webhook, polling is another option **after deleting the dev bot's webhook**, never run webhook+polling concurrently for same token. Prefer tunnel to test the exact production request lifecycle.
- Webhook endpoint should verify `X-Telegram-Bot-Api-Secret-Token`; HTTPS, rate limiting, logging redaction and per-bot secret/token isolation.

Official: https://core.telegram.org/bots/api#setwebhook

---

## 10. Suggested Supabase entities (adapt to existing schema)

These are logical responsibilities, not a requirement to create every table
up front. **Phase one** needs restaurant identity/invites, durable ingress,
restaurant/order message correlation and acknowledgement/reminder recovery.
Reuse existing storage where suitable. Conversation, rider location and
operator-relay changes are later work; no rider schema change is required to
ship the restaurant-admin bot. ADR 0011 distinguishes inbox deduplication
from the alert ledger and outbound attempt state.

1. `telegram_identities`: internal actor ref/type (`rider` / `restaurant_staff` / `operator`), `bot_key`, `telegram_user_id`, `telegram_chat_id`, username snapshot, linked_at, revoked_at, verification state, unique indexes.
2. `telegram_invites`: invite token hash, actor ref, bot, expires_at, claimed_at, claim user ID, retries, revoke state. Claim atomically.
3. Later rider conversation metadata: `dispatch_id` (unique assignment identity), `order_number`, internal `rider_id`, `langgraph_thread_id`, lifecycle and message references; extend the existing thread model where appropriate. Operator control fields belong to later takeover work. Preserve audit metadata when offer rows are cleaned up.
4. `telegram_message_index`: `(bot_key, chat_id, message_id)` composite key → restaurant/order or rider dispatch, actor, direction, reply_to_id, timestamp, optional content pointer. Restaurant messages require no graph reference. Later rider offers may have no initialized graph; link the winning dispatch to its thread after assignment.
5. `telegram_ops_relay_index`: `(bot_key, ops_chat_id, ops_message_id)` → delivery thread, origin message, actor metadata.
6. `restaurant_order_alerts`: restaurant ref, order ref, status, created/acknowledged_at, ack actor, reminder policy, next_due_at, attempt count, escalation state.
7. `message_outbox`: recipient/bot, kind, payload/message refs, idempotency key, deliver_after, attempts, last error, status; worker claims due items with concurrency-safe leasing.
8. Later location integration: first reuse existing location demands, observations and assignment validation. A new `rider_locations` store and Telegram live-location ingestion are not decided or required for phase one.
9. `conversation_events`: immutable audit for agent outputs, callbacks, HITL transitions, human messages, race results.

Ensure DB unique constraints and transactional dispatch accept action. RLS/service role design should be reviewed against existing Supabase architecture. Treat Telegram payloads as untrusted; one rider must not access another rider's job simply by tampering with callback_data.

---

## 11. Tests and acceptance criteria

**Phase one:** restaurant onboarding/authorization, deterministic order actions,
all restaurant-facing senders, acknowledgement reliability, durable ingress
and deployment checks. Cover delivery and collection from web and WhatsApp
orders. Verify food-ready and pickup-time changes still reach the assigned
rider via the existing workflow, and preserve payment/timeout/auto-mode rules.
The rider routing, location and HITL gates below apply only to their later
implementation phases.

### Core onboarding
- Invite token valid/invalid/expired/reused; concurrent claim race; duplicate `/start`; re-link flow; blocked bot/unblocked bot; user's phone changes; old Telegram account lost.
- Bot cannot send before first `/start`; thereafter can send to chat id subject to permissions, blocks and rate limits.

### Conversation routing — later rider phase
- Offer to N riders → independently indexed dispatch/root messages; initialize a graph only for the confirmed assigned dispatch.
- Reply to root; reply to reply; callback; ambiguous message without a reply; cancellation aftercare for A while B starts; stale/deleted root; unsupported media; out-of-order and duplicate updates; duplicate initialization and concurrent graph events.
- Completing or cleaning up A must not change B. Debug reads must not create/touch threads. Multiple simultaneous deliveries require a separate product decision.
- A rider who presses `/start` mid-job must not lose context.
- First valid offer acceptance atomic, rest declined as stale.

### Location — later rider phase
- Requested one-off location; manually shared location; active live location edited updates; expired/stopped sharing; sender not authorised; location for wrong/multiple jobs; no updates due to background constraints.

### Restaurant alert reliability
- Original order + supported inline actions; repeat on configurable cadence while eligible/unacknowledged; stop reminders after authoritative ACK/terminal state; owner escalation; multiple staff; all phones locked; offline; mute/DND/battery saver; service restart and worker race; send failures; rate-limit flood. Preserve existing rejection semantics; a new Reject button is a separate decision.
- Track real observed sound/ack behaviour, not just Bot API success responses.

### HITL — later capability
- Operator takes over exactly one thread; other job for same rider remains AGENT; all messages relayed and mapped; only authorised operator can reply/release; in-flight agent response doesn't leak during HUMAN mode; operator replies are recorded for later graph context; release resumes without double reply.

### Deployment
- Local Cloudflare tunnel + dev bot; switch/restore webhook script; webhook secret verification; separate bot tokens/routes; monitoring for `pending_update_count`, `last_error_message`, Telegram errors, outbox backlog, unacknowledged order age.

---

## 12. Prioritised work plan for implementing agent

**Phase 1 — restaurant admins only (first implementation scope)**
1. Refresh the source inventory in ADR 0011 against current code. Trace every restaurant-facing send, including those in delivery/takeaway/location/customer hooks, rider tools and admin/overwatch producers. Extract the relevant restaurant actions into transport-neutral fulfilment handlers and the corresponding outbound intents into the messaging port.
2. Build the restaurant bot adapter in this repository and its thin route in `watomation/routers/`. Use a dedicated dev bot, a bot-specific command menu, secret verification, durable update receipt/deduplication and recoverable processing. Implement authorized staff onboarding, invite claim, revocation/relink and restaurant membership checks.
3. Implement existing order acceptance, pickup-time selection/adjustment and ready actions, plus restaurant-facing order/delivery notifications. Keep acknowledgement/stop/escalation rules in the shared restaurant acknowledgement module for both fulfilment modes. Preserve payment timing, timeout rules, configured-auto suppression and TEST3100 restrictions. Do not add a new Reject policy.
4. Verify the event bridge: restaurant actions update authoritative fulfilment state and resulting events still notify the existing assigned rider. No restaurant agent, rider bot or rider thread migration is required.
5. Complete durable reminder/recovery checks and the restaurant Android pilot. Set measurable acknowledgement targets, escalation ownership and operational runbooks before production rollout. Notification audibility and printer retirement remain separate decisions. Bot provisioning, live messages and deployment require their own operational authorization.

**Phase 2 — rider bot and graph/thread migration (deferred)**
- Implement rider onboarding and commands, shared dispatch rules, all rider outbound intents and graph transport decoupling.
- Implement ADR 0012 end to end: `ordelo:rider:dispatch:<dispatch_id>`, confirmed-assignment initialization, exact job routing, idempotency, serialized graph work, precise cleanup/closure, historical metadata and read-only debug. Keep existing persisted IDs intact; plan how already-active jobs finish before enabling the new design.
- Add dispatch/message reply indexing and deterministic location-request correlation. Verify stale taps, assignment races, cancellation aftercare and graph effects. This phase does not imply multiple simultaneous deliveries.

**Later capabilities — separately planned**
- Operator takeover/release and its group or dashboard surface, with per-thread history and protection against stale agent sends.
- Telegram live-location ingestion, if selected after reviewing the existing location lifecycle.
- Optional Mini App or Android companion experiments if the restaurant pilot establishes a need. Printer retirement requires an explicit decision across its owners.

---

## 13. External project references discussed

**Official docs**
- Telegram Bot API: https://core.telegram.org/bots/api
- Bot deep links: https://core.telegram.org/bots/features#deep-linking
- Webhooks: https://core.telegram.org/bots/webhooks
- aiogram 3: https://docs.aiogram.dev/
- aiogram callback data: https://docs.aiogram.dev/en/latest/filters/callback_data.html
- Telegram Mini Apps: https://core.telegram.org/bots/webapps
- Telegram live location: https://core.telegram.org/api/live-location
- Meta WhatsApp pricing: https://business.whatsapp.com/products/platform-pricing

**Community repositories identified in the discussion (review health, licenses and code before adoption; not independently audited):**
- https://github.com/hexfrost/fastapi-aiogram-template — light webhook/FastAPI example
- https://github.com/mamashin/tg-bot-fastapi-aiogram — FastAPI/aiogram integration
- https://github.com/BushlanovDev/aiogram-fastapi-bot-template — keyboards, callbacks, routers, states
- https://github.com/MrConsoleka/aiogram-bot-template — DI/middleware/persistence patterns
- https://github.com/wakaree/aiogram_bot_template — Dishka DI / layered approach
- https://github.com/Ralphcode-collab/aiogram3-bot-template — alternative production patterns

**Telegram MCP and agent skill candidates (mostly development/admin/test support, not a runtime substitute for aiogram):**
- https://github.com/Telegram-mcp/telegram-mcp — MTProto client-side test interactions (click buttons, inspect bot replies)
- https://github.com/guangxiangdebizi/telegram-mcp — Bot API-facing MCP
- https://github.com/mcp-telegram/mcp-telegram — larger Telegram MTProto MCP project
- https://github.com/hec-ovi/telegram-bot-skill — coding agent + Telegram skill/integration; Node focused, not aiogram-specific
- https://github.com/pavel-molyanov/telegram-ai-agent — Telegram agent setup skills

MCP servers that log in as a **user** may need Telegram API ID/hash and session credentials. Vet security and avoid production rider PII in agent testing. For automated tests, use test accounts/environments where possible. A custom Ordelo aiogram development SKILL.md may be more reliable than importing a generic Telegram coding-agent skill.

---

## 14. Decisions confirmed vs assumptions to validate

| Item | Status |
|---|---|
| Keep customer WhatsApp/web ordering | Agreed scope |
| Move restaurant admins first | Confirmed implementation sequence, 15 October 2026; pilot before production rollout |
| Rider Telegram migration and agent/thread refactor | Deferred implementation |
| Existing FastAPI + Supabase + LangGraph own logic/state | Strong architectural intent |
| User already knows PyWA handlers | Confirmed |
| ~20 riders, phone numbers known, Telegram IDs unknown | Confirmed contextual input |
| Restaurants mostly Android | Confirmed |
| Avoid Pi/printer capital/setup cost | Key business motivation |
| Telegram private chat ID stable across `/start` | Telegram behavior |
| Rider thread ID `ordelo:rider:dispatch:<dispatch_id>` | Selected later design in ADR 0012; initialized only after confirmed assignment |
| Multiple simultaneous rider deliveries | Separate, undecided capability |
| Support human takeover through same bot | Requested capability |
| Two bots with distinct commands and responsibilities | Confirmed target; restaurant-admin bot first, rider bot later |
| Dedicated admin group/forum for HITL | Recommendation, not final decision |
| Telegram repeated notifications will be audible/reliable | **Unproven: test** |
| Mini App will ring with screen locked | **No reliable guarantee** |
| WhatsApp £82.81 monthly scenario | **Estimate contingent on assumptions** |
| Repository/thread source review | Reviewed in ADRs 0011/0012; refresh before implementation; deployed database not verified by this documentation |

## 15. Remaining implementation decisions

### Restaurant-admin phase
1. Which existing restaurant membership records should Telegram staff bindings use, and how are multiple staff/phones revoked or transferred between shifts?
2. Which existing storage/workers can support durable ingress and reminder recovery? Define retry and escalation ownership without reusing the customer's at-most-once callback policy.
3. What acknowledgement target, escalation contact and tested Android/device setup will the restaurant pilot use? Preserve current acceptance/timeout/payment rules unless a separate change is approved.
4. What are actual invoices and measured costs/acknowledgement outcomes per restaurant for the migration comparison?

### Deferred rider work — does not block phase one
1. Verify the deployed thread schema/cleanup jobs against ADR 0012's source review and define the boundary for existing active jobs.
2. Decide whether simultaneous rider deliveries are needed; current scope does not enable them. Ambiguous no-reply messages require explicit selection even with cancellation aftercare alone.
3. Select the operator support surface, permissions and history/retention rules before implementing takeover.
4. Decide whether Telegram live location adds value beyond the existing location lifecycle.

---

## 16. Short agent directive

> Read this document and ADRs 0011/0012, then refresh the relevant source review. The **first implementation scope is the restaurant-admin Telegram bot only**, in the existing FastAPI repository. Securely link authorized staff, implement deterministic restaurant actions and all restaurant-facing notifications through domain intents, and provide durable acknowledgement/reminder recovery for delivery and collection. Preserve existing fulfilment/payment rules and restaurant events that notify the assigned rider through its current workflow. Validate Android notification behaviour in the restaurant pilot. **Defer the rider bot, graph refactor and dispatch-based thread implementation** to a later phase; preserve existing rider and customer threads now. Present concrete changes and acceptance evidence before production rollout. This documentation update is not authorization to implement, provision bots, send live messages or deploy.
