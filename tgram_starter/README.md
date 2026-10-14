# Telegram starter kit (throwaway)

A small, self-contained aiogram 3.31 + FastAPI bot for learning how Telegram works before the real Ordelo migration
(see `docs/ordelo_telegram_implementation_handoff.md`, `docs/adr/0011-*`, and `.claude/skills/telegram-api`).
**Nothing outside this folder imports it. Delete the folder to remove it.**

```
tgram_starter/
  app.py            FastAPI host: webhook endpoint + invite/send HTTP endpoints
  bot_factory.py    builds Bot + Dispatcher
  config.py         env settings (TGRAM_*), reads tgram_starter/.env_local (then .env)
  invites.py        TGRAM_INVITES dict = the fake `tgram_invites` table (+ SQL for the real one)
  keyboards.py      inline/reply keyboards, typed callback data
  handlers/
    onboarding.py   /start <code> claim, contact verification, /whoami, /invite, /invites
    interactive.py  inline buttons, callbacks, edit-in-place, stale-tap handling, photo/document
    basic.py        /help, formatting, typing, location + live location, media, echo (must be last)
  miniapp/          Demo Kitchen Mini App: auth.py (verify initData) · store.py · router.py · static/index.html
  handlers/miniapp.py  /app command that opens it
  notebook_setup_bot.py  `# %%` cells: validate token, SET/inspect/delete the webhook, bot commands
  notebook.py       `# %%` cells: ad-hoc sends and calls to the app's invite endpoints
  pyproject.toml    uv project (deps + venv in tgram_starter/.venv); uv.lock pins versions
  .env_local.example  placeholder-only reference for your real, gitignored .env_local
  .gitignore        keeps secrets, .venv and caches out of git
  explainer.html    open in a browser: diagrams of how the files fit together
  tests/            offline tests (no network)
```

## 1. Credentials you need

| What | Where it comes from | Used for |
|---|---|---|
| **Bot token** | Telegram app → chat with **@BotFather** → `/newbot` → pick a name and a username ending in `bot`. BotFather replies with `123456789:AA...`. | Every Bot API call. It is a password: never commit it. If leaked, `/revoke` in BotFather. |
| **Bot username** | Same step (e.g. `my_ordelo_test_bot`). | Building invite links `https://t.me/<username>?start=<code>`. |
| **Webhook secret** | You invent it: `python -c "import secrets; print(secrets.token_urlsafe(32))"` (chars `A-Za-z0-9_-`, ≤256). | Telegram sends it back in `X-Telegram-Bot-Api-Secret-Token` on every update; we reject requests without it. |
| **Public HTTPS URL** | Wherever your FastAPI app is hosted. Telegram only calls HTTPS on ports 443, 80, 88 or 8443. | `TGRAM_WEBHOOK_BASE_URL`; registered with `notebook_setup_bot.py`. |
| **Your Telegram user id** | Message **@userinfobot** (or send `/whoami` to your bot). | `TGRAM_ADMIN_IDS` so you can use `/invite`. |

No phone number, API id/hash, or Business account is needed. (Those are for user-account/MTProto automation, which this does not do.)

Optional BotFather polish: `/setdescription`, `/setuserpic`, `/setcommands` (paste the command list from `/help`) and `/setprivacy` (only matters in groups).

## 2. Run it

The bot runs in **webhook mode only**: Telegram POSTs each update to your FastAPI app. Set `TGRAM_WEBHOOK_BASE_URL` to the public HTTPS URL where the app is reachable (wherever you host it).

```bash
# from the repo root
uv sync --project tgram_starter                                # creates tgram_starter/.venv from uv.lock
cp tgram_starter/.env_local.example tgram_starter/.env_local   # then fill in your values (gitignored)

uv run --project tgram_starter python -m tgram_starter.app    # the app on port 3100 (must be reachable at the base URL)
```

Then register the webhook from **`notebook_setup_bot.py`** (open it in VS Code / Jupyter with the `tgram_starter/.venv` interpreter and run the cells):

| Cell | Does |
|---|---|
| 1-2 | load settings, validate the token (`get_me`) |
| 3 | `get_webhook_info`: what Telegram has now (read-only) |
| 4 | **`set_webhook`**: `<TGRAM_WEBHOOK_BASE_URL>/telegram/webhook` + secret token, `drop_pending_updates=False` |
| 5 | verify URL, pending count, last error |
| 6 | optional: set the "/" command menu |
| 7 | optional: hit `/health` and confirm a wrong secret gets 403 |
| 8 | `delete_webhook` (commented out) |

Re-run cell 4 whenever the base URL changes. Updates that arrive while the webhook is down are queued by Telegram (about 24h) unless you drop them.

`notebook.py` is the separate scratchpad for sending messages and calling the app's invite endpoints. Add a dependency with `uv add --project tgram_starter <pkg>`; the root project's `uv.lock` is not touched.

## 3. Invites: how a person gets linked

A bot **cannot message someone first** and cannot look up a Telegram id from a phone number. The person must press **Start**. The deep link carries a one-time code that ties their Telegram account to the phone number you invited.

1. **Create the invite** (any of):
   - Telegram: as an admin, send your bot `/invite 447700900123`
   - HTTP: `curl -X POST 'localhost:3100/invites?phone_number=447700900123' -H 'X-Admin-Key: <TGRAM_ADMIN_API_KEY>'`
   - Python: `invites.create_invite("447700900123")`
2. **Send the link** `https://t.me/<bot_username>?start=<invite_code>` to that person over WhatsApp/SMS/email (the response/`/invite` reply contains it). On a phone it opens Telegram with a **Start** button. A QR of the same link works too.
3. **They tap Start.** Telegram sends the bot `/start <invite_code>`. `onboarding.cmd_start` claims the code atomically and records their ids.
4. **Optional phone proof:** the bot asks them to tap "Share my phone number". We accept it only if `contact.user_id == from_user.id` (otherwise they could forward anyone's contact card) and the number matches the invite.
5. From now on `invites.find_by_telegram_user(id)` is the identity lookup, and `chat_id` is where proactive messages go (`POST /send`).

### The `tgram_invites` table (dict now, SQL in `invites.py` docstring)

| Column | Meaning |
|---|---|
| `invite_code` | random single-use code in the link (≤64 chars of `A-Za-z0-9_-`; hash it in production) |
| `phone_number` | who the invite was meant for (digits, E.164) |
| `status` | `pending` → `claimed` (or `expired` / `revoked`) |
| `created_at`, `expires_at`, `claimed_at` | lifecycle; default TTL 48h (`TGRAM_INVITE_TTL_HOURS`) |
| `telegram_user_id` | `from_user.id`: **the person**. Stable for that account. Use this to authorise actions. |
| `telegram_chat_id` | `chat.id`: **where we send**. In a private chat it equals the user id, but store it separately: groups differ. |
| `telegram_username` | optional, changeable, display only. Never use for identity. |
| `first_name`, `language_code` | convenience |
| `phone_verified` | true if they shared their own contact and it matched |

Behaviour: unknown / expired / revoked / already-used-by-someone-else codes are refused; the same person pressing Start again is a no-op (their ids do not change on repeat `/start`). Blocking the bot makes sends fail with `TelegramForbiddenError`; it does not change ids.
Ids can exceed 32 bits, so use `bigint` in SQL.

## 4. What the demo shows (try these in order)

| Try | Feature | Code |
|---|---|---|
| `/start`, `/help`, any text | basic commands, echo | `basic.py` |
| `/format` | HTML formatting and **why you `escape()` user text** | `basic.py` |
| `/typing` | chat action + `reply()` | `basic.py` |
| `/menu` → *Demo order offer* → Accept/Decline | **inline buttons → callback queries**, typed `CallbackData`, message editing, stale/double-tap guard (try tapping a second offer's old button) | `keyboards.py`, `interactive.py` |
| `/menu` → *Counter* | state packed in the button, message edited in place | `interactive.py` |
| `/menu` → *Ask for location* | **reply keyboard** `request_location` → arrives as a *message* with `.location` | `keyboards.py`, `basic.py` |
| attach → Location → **Share Live** | live location updates arrive as `edited_message` (logged to console) | `basic.py` |
| `/menu` → *Share my phone* | `request_contact` and ownership check | `onboarding.py` |
| `/menu` → *Send a photo* | photo + document uploads with captions | `interactive.py` |
| `/menu` → *URL button* | URL buttons open a link; they do **not** produce a callback | `keyboards.py` |
| `/whoami` | user id vs chat id vs Ordelo link | `onboarding.py` |
| `/invite <phone>`, `/invites` (admin) | invite flow above | `onboarding.py` |

## 5. Things that will bite you

- **Always `await query.answer()`** on a callback (even rejected/stale taps) or the button spinner hangs.
- **Callback data is max 64 bytes** (not characters). Use compact typed data (`ord:1042:a`) or a server-side token for anything long.
- Inline buttons → `callback_query`; reply-keyboard buttons → ordinary `message`. Location/contact request buttons only work in private chats.
- Parse mode is HTML by default here: escape any dynamic text with `html.escape`. Message limit is 4096 characters.
- Register specific handlers before the catch-all text echo (`bot_factory.py` order).
- Authorise on `from_user.id` + current state, never on text, username or button label.
- Webhook handler here processes inline (fine for a demo). Production needs: dedupe on `update_id`, fast ack, worker for slow work (ADR 0011).
- The dict store is per-process: restarts forget everything, and multiple uvicorn workers would not share it. Run a single worker.
- Rate limits: roughly 1 msg/sec per chat, ~30/sec overall. Respect `TelegramRetryAfter`.

## 6. Tests

```bash
uv run --project tgram_starter pytest tgram_starter/tests -q
```
Covers invite lifecycle (claim, reuse, expiry, revoke, phone check), callback ≤64 bytes, webhook secret rejection, and admin-key protection. These are offline; they do not prove real delivery to Telegram.

## 7. Mini app: "Demo Kitchen"

A **Telegram Mini App** is a web page that opens *inside* Telegram (full-height sheet) from a bot button. It is served by the same FastAPI app, so there is nothing extra to host.

**Try it**
1. App running and reachable over **HTTPS** (Telegram will not open `http://`). `TGRAM_WEBHOOK_BASE_URL` (or `TGRAM_MINIAPP_URL`) must point at it; the page lives at `<base>/miniapp/`.
2. Send the bot `/app` (or `/menu` → *Open mini app*) and tap the button.
3. Optional: run cell **6b** of `notebook_setup_bot.py` to add a permanent "Demo Kitchen" button next to the message box.
4. Add items, tap the Telegram **Checkout** button, confirm. The server prices the order, the bot sends a chat confirmation with a **Track order** button that reopens the page on that order, and the status moves placed → preparing → ready (a demo timer).

**What it demonstrates**

| Feature | Where |
|---|---|
| Open from an inline `web_app` button, `/app`, or the chat menu button | `handlers/miniapp.py`, `keyboards.py`, setup notebook 6b |
| **Verifying `initData`** (HMAC with the bot token, `auth_date` freshness) | `miniapp/auth.py` |
| Unverified `initDataUnsafe` vs server-verified identity, side by side | "What Telegram gave this page" panel |
| Telegram-native chrome: `MainButton`, `BackButton`, `showConfirm`, haptics, theme colours | `static/index.html` |
| Server-side pricing (page sends ids + quantities, never prices) and quantity limits | `miniapp/store.py` |
| Idempotent checkout (double tap returns the same order, one chat message) | `store.create_order`, `router.place_order` |
| Owner-only orders (someone else's id looks like a missing one) | `store.get_order_for` |
| Bot ↔ page round trip: chat message → `?order=` deep link → page | `router._notify` |
| Link to the invite table: the page shows the user's Ordelo phone if linked | `GET /miniapp/api/session` |

**Rules worth remembering**
- Never trust `initDataUnsafe` or a user id sent in a body/query. Every API call sends the signed `initData` in `X-Telegram-Init-Data`; the server verifies it and takes `user.id` from that.
- A valid signature only proves Telegram produced it. Reject old ones (`TGRAM_MINIAPP_AUTH_MAX_AGE`, default 1 hour).
- Opening a mini app from a keyboard button does not message the user by itself; the confirmation only arrives if the user has started the bot (the page reports `chat_notified: false` otherwise).
- Build page DOM with `textContent` (display names are user-controlled).
- Not covered here: payments (Telegram Stars/Stripe invoices), `sendData` via reply-keyboard buttons, `answerWebAppQuery` (inline-mode only), cloud/device storage.
- Orders are an in-memory dict like invites: restarts forget them, run one worker.

Offline checks: `tests/test_miniapp.py` (auth, pricing, idempotency, ownership, `/app` button). The page itself was exercised in headless Chromium with a stubbed Telegram bridge; that does not replace opening it in a real Telegram client.

## 8. Mapping to the real migration

Telegram `chat_id`/`user_id` are never WhatsApp phone ids; `tgram_invites` becomes the linking table that maps `rider_id`/admin → `(bot, telegram_user_id, telegram_chat_id)`. LangGraph thread selection, delivery state, durable ingress, message-id↔job indexing and 1-vs-2 bots are open decisions in the handoff doc and ADR 0011, not settled here.
