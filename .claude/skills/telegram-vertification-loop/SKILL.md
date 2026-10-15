---
name: telegram-vertification-loop
description: Verify OrdeloAgent aiogram bot changes through dispatcher, webhook, and database contract tests, with clearly scoped live Telegram evidence. Use when adding or changing Telegram handlers, callbacks, Bot API sends, invite or order actions, or webhook processing.
---

# Telegram Vertification Loop

Use this skill to build and run a repeatable verification loop for this project's Telegram layer. Read `docs/telegram-layer.md` and the changed source first. For Telegram API design or migration details, also read the project `telegram-api` skill. Use the pinned aiogram version in `pyproject.toml`; check the versioned official docs before relying on an unfamiliar API.

## Set the boundary

Trace the changed path from incoming update or domain event through the webhook, dispatcher, handler, domain wrapper, SQL RPC, and outgoing Bot API call. State the observable result and durable state change for each relevant actor. Keep the restaurant-admin and future rider bots separate. A green test at one boundary does not prove the next boundary.

For each state-changing action, choose cases from the actual rule: allowed actor, wrong actor, expired or revoked identity, stale button, repeated update, competing requests, and downstream failure. Check the `from_user.id` actor independently from `chat.id` and Ordelo identity. Verify callback acknowledgement and the separate business outcome. Add only cases relevant to the change.

## Run the loop

1. Capture the expected behavior in a focused test before changing behavior where practical. Run it and confirm the failure is caused by the missing behavior, then make the smallest change and rerun it.
2. Exercise routing through the real aiogram `Dispatcher` using `tests/channels/telegram/conftest.py` update builders and `RecordingSession`. Assert the Bot API method, destination, content, keyboard, callback answer, and number of sends that matter to the scenario. Test byte limits and escaping when callback data or rendered text changes. Mock external boundaries, not the router being verified.
3. Exercise the FastAPI webhook with the minimal test app in `tests/watomation/routers/test_telegram_webhook.py` when ingress changes. Cover bot selection, secret rejection, malformed updates, handler errors, and timeout as applicable. The current route returns HTTP 200 after handler failure; record the update's actual outcome rather than treating 200 as processed. When a durable inbox exists, verify persistence, deduplication, retry, and worker restart at that boundary.
4. When an RPC contract changes, update the fake to match every `result` value, then verify the actual SQL against an isolated database before claiming database behavior. Test authorization and concurrent claims or transitions where they matter. Follow the database-operations skill for database access; preparing tests or SQL does not authorize executing migrations or changing shared data.
5. Run a live check only when the task calls for it and the test bot, account, and environment are authorized. Follow `docs/local-testing-runbook.md`: one webhook per token, and this test token may be shared with `tgram_starter`. When the user's Telegram Web session is open in Chrome, use the available computer use or browser controls to type a message or tap a button as the Telegram user, then inspect the visible response and persisted outcome. Bot-side `sendMessage` calls and an aiogram MCP event feed cannot simulate that user action. Treat a successful Bot API response as API acceptance, not confirmed human delivery.
6. For a local live run, use the `herdr-cli` skill to read the OrdeloAgent backend logs. The usual Herdr pane label is `localOrdeloRun`; resolve its current pane ID from the live inventory before reading. Correlate the browser action with the webhook update and handler result in a bounded, read-only log snapshot. A quiet pane or HTTP 200 alone does not prove the action completed.
7. Rerun the focused checks after the fix and the wider affected Telegram suite before reporting completion. Keep unrelated existing failures explicit. Update `docs/telegram-layer.md` and its change log when the Telegram layer itself changes.

## Report evidence

For each checked scenario, report the boundary, command or live action, observed result, and any remaining unverified boundary. For a live browser check, pair the visible Telegram result with the matching Herdr log evidence when available. Label evidence **offline**, **isolated database**, or **live Telegram**. Do not claim SQL, webhook durability, user-visible delivery, payment, or fulfilment from mocked Bot API calls or an HTTP 200 alone.

An aiogram MCP server can help observe an isolated live bot. It is optional and provides no replacement for user-driven Telegram checks, the dispatcher harness, or durable application state.
