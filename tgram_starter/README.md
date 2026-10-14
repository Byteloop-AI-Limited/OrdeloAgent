# Telegram starter kit (throwaway)

A small, self-contained aiogram 3.31 + FastAPI bot for learning how Telegram works before the real Ordelo migration
(see `docs/ordelo_telegram_implementation_handoff.md`, `docs/adr/0011-*`, and `.claude/skills/telegram-api`).
**Nothing outside this folder imports it. Delete the folder to remove it.**

```
tgram_starter/
  app.py            FastAPI host: webhook endpoint + invite/send HTTP endpoints
  bot_factory.py    builds Bot + Dispatcher (shared by webhook and polling)
  config.py         env settings (TGRAM_*), reads tgram_starter/.env
  invites.py        TGRAM_INVITES dict = the fake `tgram_invites` table (+ SQL for the real one)
  keyboards.py      inline/reply keyboards, typed callback data
  handlers/
    onboarding.py   /start <code> claim, contact verification, /whoami, /invite, /invites
    interactive.py  inline buttons, callbacks, edit-in-place, stale-tap handling, photo/document
    basic.py        /help, formatting, typing, location + live location, media, echo (must be last)
  polling.py        run locally with no public URL
  webhook_cli.py    me | set | info | delete
  notebook.py       `# %%` cells for ad-hoc calls against the real Bot API (VS Code / Jupyter / ipython)
  explainer.html    open in a browser: diagrams of how the files fit together
  tests/            offline tests (no network)
```

## 1. Credentials you need

| What | Where it comes from | Used for |
|---|---|---|
| **Bot token** | Telegram app → chat with **@BotFather** → `/newbot` → pick a name and a username ending in `bot`. BotFather replies with `123456789:AA...`. | Every Bot API call. It is a password: never commit it. If leaked, `/revoke` in BotFather. |
| **Bot username** | Same step (e.g. `my_ordelo_test_bot`). | Building invite links `https://t.me/<username>?start=<code>`. |
| **Webhook secret** | You invent it: `python -c "import secrets; print(secrets.token_urlsafe(32))"` (chars `A-Za-z0-9_-`, ≤256). | Telegram sends it back in `X-Telegram-Bot-Api-Secret-Token` on every update; we reject requests without it. |
| **Public HTTPS URL** | Cloudflare Tunnel / ngrok pointing at your FastAPI port (see `docs/local-testing-runbook.md`). Telegram only calls HTTPS on ports 443, 80, 88 or 8443. | Webhook mode only. Skip it by using polling. |
| **Your Telegram user id** | Message **@userinfobot** (or send `/whoami` to your bot). | `TGRAM_ADMIN_IDS` so you can use `/invite`. |

No phone number, API id/hash, or Business account is needed. (Those are for user-account/MTProto automation, which this does not do.)

Optional BotFather polish: `/setdescription`, `/setuserpic`, `/setcommands` (paste the command list from `/help`) and `/setprivacy` (only matters in groups).

## 2. Run it

```bash
# from the repo root
uv pip install -r tgram_starter/requirements.txt        # or: pip install -r ...
cp tgram_starter/.env.example tgram_starter/.env        # then edit it

python -m tgram_starter.webhook_cli me                  # sanity check: prints @yourbot if token is valid
```

**Option A: polling (easiest, no tunnel).** Telegram → your machine by long polling. This removes any webhook on the bot.
```bash
python -m tgram_starter.polling
```
Note: polling mode only runs the bot; the HTTP endpoints (`/invites`, `/send`) live in the FastAPI app.

**Option B: webhook on FastAPI (how production works).**
```bash
uvicorn tgram_starter.app:app --port 3200               # terminal 1
cloudflared tunnel --url http://localhost:3200          # terminal 2 → copy the https URL into TGRAM_WEBHOOK_BASE_URL
python -m tgram_starter.webhook_cli set                 # registers <base>/telegram/webhook with the secret
python -m tgram_starter.webhook_cli info                # check url, pending_update_count, last_error_message
```
A bot can have **either** a webhook **or** polling, never both. Tunnel URLs change on restart; run `set` again.
`webhook_cli delete` removes it. Updates that arrive while the webhook is down are queued by Telegram (up to 24h) unless you drop them.

## 3. Invites: how a person gets linked

A bot **cannot message someone first** and cannot look up a Telegram id from a phone number. The person must press **Start**. The deep link carries a one-time code that ties their Telegram account to the phone number you invited.

1. **Create the invite** (any of):
   - Telegram: as an admin, send your bot `/invite 447700900123`
   - HTTP: `curl -X POST 'localhost:3200/invites?phone_number=447700900123' -H 'X-Admin-Key: <TGRAM_ADMIN_API_KEY>'`
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
python -m pytest tgram_starter/tests -q
```
Covers invite lifecycle (claim, reuse, expiry, revoke, phone check), callback ≤64 bytes, webhook secret rejection, and admin-key protection. These are offline; they do not prove real delivery to Telegram.

## 7. Mapping to the real migration

Telegram `chat_id`/`user_id` are never WhatsApp phone ids; `tgram_invites` becomes the linking table that maps `rider_id`/admin → `(bot, telegram_user_id, telegram_chat_id)`. LangGraph thread selection, delivery state, durable ingress, message-id↔job indexing and 1-vs-2 bots are open decisions in the handoff doc and ADR 0011, not settled here.
