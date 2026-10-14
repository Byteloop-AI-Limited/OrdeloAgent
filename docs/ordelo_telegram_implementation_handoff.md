# Ordelo — Telegram Operational Messaging Migration
## Implementation-agent handoff | 14 October 2026

> **Purpose:** Complete context and actionable implementation guidance for migrating **rider and restaurant operational coordination** from WhatsApp Business Platform (PyWA) and/or Raspberry Pi thermal printers toward **Telegram Bot API + aiogram 3**, while keeping the existing customer-facing WhatsApp and web ordering journeys intact. This is a handoff of discussion, proposed design, sample patterns, constraints, and decisions. It is **not** a claim that the target functionality has been implemented in the codebase.

> **Session review — 14 October 2026:** Read [proposed ADR 0011](adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) for the consolidated repository recommendation and ownership rules. The discussion below is retained as source material. Its repeated prescriptions for one LangGraph thread per rider/job, including schema, implementation phases and acceptance criteria, are **superseded**: thread cardinality and concurrent rider jobs are separate, undecided choices. Telegram message-to-job/thread indexing is still required. One versus two bots is also open. Restaurant rejection, post-Accept pickup reminders, live-location storage and printer retirement are separate decisions, not consequences of choosing Telegram. Preserve accepted ADRs 0001–0010; do not infer a change to timeout, capture or print behaviour from examples below. Durable ingress and reminder recovery must follow the distinctions in ADR 0011.

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
- On a rider delivery offer, create an **initial/root Telegram message**; all related exchanges should be presented as replies to the original order message where possible. There is **one LangGraph thread per rider×delivery job**, separate from Telegram's persistent private chat.
- Human operator must be able to **take over one rider/job conversation**, manually reply **through the bot**, then return the job to the agent.

### Essential caveats / unresolved choices
1. **Notification reliability is the biggest risk.** Bot messages can be repeated; Telegram, Android and user settings can still mute, batch or suppress audible alerts. A Telegram Mini App can loop audio while visible/active but is **not a reliable background/locked-screen alarm**.
2. **Choose whether to run one or two bots.** Recommended two (`Ordelo Rider Bot`, `Ordelo Restaurant Bot`) for roles/permissions; both may use same FastAPI instance, but must have separate tokens/webhooks/dispatchers.
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
- Pilot recommendation: 3–5 riders plus 2–3 Android-heavy restaurants for 1–2 weeks. Test locked screens, backgrounded app, muted/battery-saver/DND conditions, peak loads, multiple staff, internet outages. Monitor `ack latency`, `% ack ≤30/60/120s`, misses, escalation count, stale offline delivery, satisfaction and manual fallback use.
- Suggested success target from discussion: **95% acknowledged within 60s**, explicitly a *proposed internal target*, not an industry guarantee.
- Consider two separate Telegram bots so riders and restaurants have distinct names, permissions, operational handling and message styles.

---

## 3. Target platform architecture

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

Suggested modules:

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

**Do not duplicate Supabase schema unnecessarily**; adapt mappings to the real tables and identifiers (`rider_ref`, `rest_ref`, delivery/order refs). Retain domain services as the only authority for state changes.

---

## 4. aiogram core implementation patterns

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
# dp.include_router(rider_router); dp.include_router(admin_router), etc.

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await bot.session.close()  # do NOT register/clear webhook on every restart

app = FastAPI(lifespan=lifespan)

@app.post('/telegram/rider/webhook')
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
    reply_markup=offer_keyboard(job_ref),
)
await save_job_root(chat_id=sent.chat.id, message_id=sent.message_id,
                    job_ref=job_ref, rider_ref=rider_ref,
                    langgraph_thread_id=thread_id)
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
| `langgraph_thread_id` | Ordelo graph's per-job conversation | Defined by application |

- `/start` again **does not reset** Telegram chat ID or user ID for the same account. Don't create new rider record or discard active threads when it is used again.
- Replacing phone number on the **same Telegram account** normally retains Telegram IDs; deleting account/re-registering can change them. Blocking the bot causes sending errors, not a fresh chat ID.
- Group IDs and topic IDs have different semantics; group→supergroup migrations can change chat ID. Store chat IDs as BIGINT or text safe for large Telegram IDs; JS should avoid numeric precision issues if values ever grow beyond safe range.
- In one-to-one conversation, `telegram_chat_id` is the target for `bot.send_message` and `telegram_user_id` is the actor for authorization checks.

---

## 6. Per-job conversations, reply chains, and LangGraph

**Critical design:** One rider private chat can contain several jobs, each with its own root Telegram message and **distinct** `LangGraph thread_id`, e.g. `delivery:<job_ref>:rider:<rider_ref>`.

```text
rider private chat (chat_id=123456789)
  message 501: job A offer / instructions    ↔ graph thread A
  message 502: reply to message 501          ↔ graph thread A
  message 503: bot reply to message 501      ↔ graph thread A
  message 524: job B offer / instructions    ↔ graph thread B
  message 525: rider reply to message 524    ↔ graph thread B
```

- For bot replies use `ReplyParameters(message_id=root_message_id)` along with `chat_id`.
- For inbound `Message`, `message.reply_to_message.message_id` points to **the immediate message being replied to**, which may not be the root. Therefore index **every job-related sent and received `(chat_id, message_id)` to the job/thread**. A rider replying to message 503 must still resolve thread A.
- For callbacks, use short offer/job ID in `callback_data`, validate that original user owns the offered action, then derive thread id from DB.
- For inbound text **without a reply**, route only if there is one unambiguous active job; otherwise ask rider to choose among jobs using an inline keyboard. Don't silently route to the latest job if multiple active jobs exist.
- Chat ID persists across jobs; **never** equate Telegram chat to LangGraph thread.
- For initial broadcast offers to multiple riders, distinguish each rider's graph and reply routing. Race on acceptance must resolve atomically so only one rider wins. Respond gracefully to stale callbacks and edited/deleted messages.
- Persist inbound/outbound messages in the conversational record as needed (human takeover and agent re-entry). Do not rely on Telegram as the durable store of agent history.

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
Order created → durable pending acknowledgement record
→ Bot sends initial order with Accept / Reject buttons
→ after 20–30s without ACK: reminder notification
→ repeat at configured interval (e.g. 30s), limited to avoid spam/rate limits
→ escalate after ~90s to owner / additional staff / ops
→ restaurant accepts/rejects → atomic status transition
→ cancellation of ALL future reminders / update original messages
```

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
- Next.js webview opened from Telegram bot, with order list, Accept/Reject and Supabase Realtime/WebSocket subscriptions.
- `new Audio(...).loop = true` (or Web Audio) can provide a **continuous alarm while Mini App is open/active** following an explicit user gesture to unlock audio/autoplay.
- **Cannot guarantee background/locked-screen playback.** Home-screen shortcut does not grant native Android foreground-service capability. Don't treat this as equivalent to printer or dedicated order terminal.
- If unacceptable pilot miss rate: consider small **Android native/Capacitor companion**, FCM notification channels + permissible foreground service / full-screen flows subject to Android's modern OS restrictions and permissions. Still no unconditional guarantee through mute/DND. A conventional PWA has similar background audio limitations.

---

## 9. Local Telegram webhook testing and switching

- Telegram bot supports exactly **one active webhook per bot token**. `setWebhook` replaces current endpoint **immediately**; `getWebhookInfo` inspects it.
- Expose local FastAPI using `cloudflared tunnel --url http://localhost:8000`; receive `https://<random>.trycloudflare.com` then set `<base>/telegram/rider/webhook`.
- Do **not** automatically call `set_webhook` in FastAPI lifespan/startup: local and production restarts will fight over ownership.
- `drop_pending_updates=False` avoids deliberately dropping queued updates, but webhook switch can still race with in-flight events. Proper idempotency required.
- For a live bot, **all** incoming updates go to local during test, including actual rider updates; safer to use **separate test bot tokens**.

```bash
# Inspect current URL and errors (ensure BOT_TOKEN is securely populated)
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | jq

# Switch to local tunnel
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${TUNNEL_BASE}/telegram/rider/webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "drop_pending_updates=false"

# Restore production
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${PROD_BASE}/telegram/rider/webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "drop_pending_updates=false"
```

- Build `scripts/telegram_webhook.py {status,local,prod} --url ...`, using aiogram `Bot.get_webhook_info()` and `Bot.set_webhook()`. Restore exact production `allowed_updates`, secret and other relevant webhook options, not just URL. Store secret safely; avoid printing token in logs/CLI traces.
- For fast dev without public webhook, polling is another option **after deleting the dev bot's webhook**, never run webhook+polling concurrently for same token. Prefer tunnel to test the exact production request lifecycle.
- Webhook endpoint should verify `X-Telegram-Bot-Api-Secret-Token`; HTTPS, rate limiting, logging redaction and per-bot secret/token isolation.

Official: https://core.telegram.org/bots/api#setwebhook

---

## 10. Suggested Supabase entities (adapt to existing schema)

1. `telegram_identities`: internal actor ref/type (`rider` / `restaurant_staff` / `operator`), `bot_key`, `telegram_user_id`, `telegram_chat_id`, username snapshot, linked_at, revoked_at, verification state, unique indexes.
2. `telegram_invites`: invite token hash, actor ref, bot, expires_at, claimed_at, claim user ID, retries, revoke state. Claim atomically.
3. `delivery_conversations`: `job_ref`, `rider_ref`, `bot_key`, `telegram_chat_id`, `root_message_id`, `langgraph_thread_id`, status, control mode, operator ID, control generation, timestamps. One per rider×job.
4. `telegram_message_index`: `(bot_key, chat_id, message_id)` composite key → `langgraph_thread_id`, job_ref, actor, direction, reply_to_id, timestamp, optional message content pointer.
5. `telegram_ops_relay_index`: `(bot_key, ops_chat_id, ops_message_id)` → delivery thread, origin message, actor metadata.
6. `restaurant_order_alerts`: restaurant ref, order ref, status, created/acknowledged_at, ack actor, reminder policy, next_due_at, attempt count, escalation state.
7. `message_outbox`: recipient/bot, kind, payload/message refs, idempotency key, deliver_after, attempts, last error, status; worker claims due items with concurrency-safe leasing.
8. `rider_locations`: rider ref, job ref, lat/lon, observed_at, Telegram source message id/live_period, consent/expires_at; apply retention policy.
9. `conversation_events`: immutable audit for agent outputs, callbacks, HITL transitions, human messages, race results.

Ensure DB unique constraints and transactional dispatch accept action. RLS/service role design should be reviewed against existing Supabase architecture. Treat Telegram payloads as untrusted; one rider must not access another rider's job simply by tampering with callback_data.

---

## 11. Tests and acceptance criteria

### Core onboarding
- Invite token valid/invalid/expired/reused; concurrent claim race; duplicate `/start`; re-link flow; blocked bot/unblocked bot; user's phone changes; old Telegram account lost.
- Bot cannot send before first `/start`; thereafter can send to chat id subject to permissions, blocks and rate limits.

### Conversation routing
- Offer to N riders → independently indexed root messages and graph threads.
- Reply to root; reply to reply; callback; message with no reply; multiple concurrent jobs; stale or deleted root; unsupported media; out-of-order webhook update; duplicate update.
- A rider who presses `/start` mid-job must not lose context.
- First valid offer acceptance atomic, rest declined as stale.

### Location
- Requested one-off location; manually shared location; active live location edited updates; expired/stopped sharing; sender not authorised; location for wrong/multiple jobs; no updates due to background constraints.

### Restaurant alert reliability
- Original order + inline buttons; repeat on configurable cadence while unacknowledged; cancel future reminders immediately after backend ACK; restaurant reject path; owner escalation; multiple staff; all phones locked; offline; mute/DND/battery saver; service restart and worker race; alert delivery failures; rate-limit flood.
- Track real observed sound/ack behaviour, not just Bot API success responses.

### HITL
- Operator takes over exactly one thread; other job for same rider remains AGENT; all messages relayed and mapped; only authorised operator can reply/release; in-flight agent response doesn't leak during HUMAN mode; operator replies are recorded for later graph context; release resumes without double reply.

### Deployment
- Local Cloudflare tunnel + dev bot; switch/restore webhook script; webhook secret verification; separate bot tokens/routes; monitoring for `pending_update_count`, `last_error_message`, Telegram errors, outbox backlog, unacknowledged order age.

---

## 12. Prioritised work plan for implementing agent

**Phase 0 — inspect actual repos and existing architecture**
- User previously cited local repositories (machine-specific and **not available in this handoff workspace**): `/Users/basavaraj/bloop/restaurant-frontend` (Next.js front end), `/Users/basavaraj/bloop/OrdeloAgent` (WhatsApp-facing backend), and `ordelo-restaurant-frontend-agents.md` documentation. Ask for repo access/current paths; don't assume the names reflect final deployment structure.
- Identify existing domain services, Supabase schema, rider / restaurant refs, job assignment transaction, LangGraph thread creation/checkpointer, PyWA callbacks, existing human support workflow, and webhook infrastructure.

**Phase 1 — skeletal bot and developer experience**
- Create dedicated **dev rider bot** with BotFather; implement FastAPI aiogram webhook, typed callback data, `/start`, `/demo`, secret header check, tunnel testing, and webhook CLI.
- No unsolicited production webhook changes or live rider messaging.

**Phase 2 — secure rider onboarding**
- One-time invite tokens sent to known phone contacts, bind Telegram user/chat ID to `rider_ref`, revocation/relink and command authorization.

**Phase 3 — rider dispatch MVP**
- Send job offer, Accept/Decline callbacks, save root message ID, map all inbound/outbound messages, route to per-job LangGraph thread, handle concurrent jobs and race conditions; request one-off location.

**Phase 4 — live location and HITL**
- Receive live location edits; implement operator group relay with takeover/release and audited per-thread mode; prevent in-flight agent replies after operator control acquired.

**Phase 5 — restaurant pilot**
- Secure restaurant admin/staff onboarding, order Accept/Reject, durable repeat-alert worker, escalation, multi-device staff support, Android test checklist and telemetry.

**Phase 6 — optional UX experiments**
- Next.js Telegram Mini App (active foreground alarm and dashboard), compare with lightweight Capacitor/Kotlin Android companion if reliable background audible alarm proves essential.

**Phase 7 — staged cutover**
- Controlled migration with PyWA fallback, operational runbooks, incident alerting, on-call owner, emergency rollback and cost/performance comparison. Do not retire printer/WhatsApp fallback until acceptance metrics support it.

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
| Move rider/restaurant operations toward Telegram | Preferred direction, pilot first |
| Existing FastAPI + Supabase + LangGraph own logic/state | Strong architectural intent |
| User already knows PyWA handlers | Confirmed |
| ~20 riders, phone numbers known, Telegram IDs unknown | Confirmed contextual input |
| Restaurants mostly Android | Confirmed |
| Avoid Pi/printer capital/setup cost | Key business motivation |
| Telegram private chat ID stable across `/start` | Telegram behavior |
| Use per-job LangGraph thread and root message mapping | Requested implementation design |
| Support human takeover through same bot | Requested capability |
| Two bots rather than one | Recommendation, not final decision |
| Dedicated admin group/forum for HITL | Recommendation, not final decision |
| Telegram repeated notifications will be audible/reliable | **Unproven: test** |
| Mini App will ring with screen locked | **No reliable guarantee** |
| WhatsApp £82.81 monthly scenario | **Estimate contingent on assumptions** |
| Production repo/database details | **Must inspect** |

## 15. Critical questions for the implementing agent before coding beyond MVP

1. Are riders and restaurant staff already modelled with distinct actor/user IDs and authorisation relationships in Supabase? Which tables should be extended?
2. Is one Telegram bot or two preferable given the existing deployment structure, distinct branding and handler separation?
3. What are current LangGraph checkpointer and per-job thread-ID conventions? Is the per-rider offer state already separate?
4. How are outgoing operational messages currently persisted? Is there an outbox/retry worker already?
5. Does a rider need **multiple jobs simultaneously**, and how should no-reply messages be routed?
6. Can restaurant staff use two or more phones and is the order accepted at restaurant or per-staff account level?
7. What constitutes order acceptance, rejection, escalation and automatic cancellation? SLA requirements and on-call contact?
8. Which phones/Android versions are in the restaurant pilot? Can a dedicated always-on device be expected, or do staff use personal phones in background?
9. What human support permission model exists? Group vs dashboard; audit / PII retention requirements?
10. What are actual Meta invoices/recipient countries and measurable messaging costs per order/job/restaurant, for migration ROI?

---

## 16. Short agent directive

> Read this document, then inspect the actual Ordelo codebases before proposing changes. Implement a **minimal, testable aiogram 3 adapter** on the existing FastAPI service, starting with a dev rider bot and webhook CLI. Securely link invited riders to stable Telegram IDs; map every `(bot, chat_id, message_id)` to the correct rider/job LangGraph thread; support typed inline callbacks, request location and live-location edits; enable per-thread human takeover through an operations group. Prototype restaurant acknowledgement with durable repeat alerts and multi-staff escalation. Treat notification audibility as an empirical Android pilot requirement and do not remove the printer/WhatsApp fallback until validated. Keep domain state in existing services/Supabase. Present a phased architecture plan, schema migration, API/event contracts, failure modes, tests, security considerations and rollback steps before production cutover.
