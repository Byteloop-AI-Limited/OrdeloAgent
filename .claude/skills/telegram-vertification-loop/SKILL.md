---
name: telegram-vertification-loop
description: Verify OrdeloAgent aiogram bot changes through dispatcher, webhook, and database contract tests, with clearly scoped live Telegram evidence. Use when adding or changing Telegram handlers, callbacks, Bot API sends, invite or order actions, or webhook processing.
---

# Telegram Vertification Loop

Use this skill to build and run a repeatable verification loop for this project's Telegram layer. Read `docs/telegram-layer.md` and the changed source first. For Telegram API design or migration details, also read the project `telegram-api` skill. Use the pinned aiogram version in `pyproject.toml`; check the versioned official docs before relying on an unfamiliar API.

## Set the boundary

Trace the changed path from incoming update or domain event through the webhook, dispatcher, handler, domain wrapper, SQL RPC, and outgoing Bot API call. State the observable result and durable state change for each relevant actor. Keep the restaurant-admin and rider bots separate. A green test at one boundary does not prove the next boundary.

For each state-changing action, choose cases from the actual rule: allowed actor, wrong actor, expired or revoked identity, stale button, repeated update, competing requests, and downstream failure. Check the `from_user.id` actor independently from `chat.id` and Ordelo identity. Verify callback acknowledgement and the separate business outcome. Add only cases relevant to the change.

## Run the loop

1. Capture the expected behavior in a focused test before changing behavior where practical. Run it and confirm the failure is caused by the missing behavior, then make the smallest change and rerun it.
2. Exercise routing through the real aiogram `Dispatcher` using `tests/channels/telegram/conftest.py` update builders and `RecordingSession`. Assert the Bot API method, destination, content, keyboard, callback answer, and number of sends that matter to the scenario. Test byte limits and escaping when callback data or rendered text changes. Mock external boundaries, not the router being verified.
3. Exercise the FastAPI webhook with the minimal test app in `tests/watomation/routers/test_telegram_webhook.py` when ingress changes. Cover bot selection, secret rejection, malformed updates, handler errors, and timeout as applicable. The current route returns HTTP 200 after handler failure; record the update's actual outcome rather than treating 200 as processed. For protected handlers, verify inbox persistence, deduplication, retry, and worker restart; verify unprotected handlers make no inbox calls.
4. When an RPC contract changes, update the fake to match every `result` value, then verify the actual SQL against an isolated database before claiming database behavior. Test authorization and concurrent claims or transitions where they matter. Follow the database-operations skill for database access; preparing tests or SQL does not authorize executing migrations or changing shared data.
5. Run the live check when the change has a user-visible Telegram, magic-link or frontend↔backend effect. Follow the [verify-test-order-local-setup skill](../verify-test-order-local-setup/SKILL.md) for preflight, Telegram Web, server logs and restoration. Use TEST3100 when the scenario needs an order. Check both bot webhooks and the shared URLs independently. A Telegram handler change is verified live when the relevant bot's webhook is on `rider-agent-test.ordelo.app` and the update appears in the local log. A deployed bot's decision can still trigger a local database-to-app hook.

   For magic links also confirm:
   - the GET page does not use up the link
   - the auto-POST lands on the right portal
   - a second tap is refused

   Bot-side `sendMessage` calls and an aiogram MCP event feed cannot simulate the user action. Treat a successful Bot API response as API acceptance, not confirmed human delivery.
6. Correlate the Telegram action with the webhook update, the handler result and the database row in a bounded, read-only snapshot. A quiet log pane or HTTP 200 alone does not prove the action completed.
7. Rerun the focused checks after the fix and the wider affected Telegram suite before reporting completion. Keep unrelated existing failures explicit. Update `docs/telegram-layer.md` and its change log when the Telegram layer itself changes.

## Rider invites and Overwatch alerts

Use a designated test rider. Capture the rider profile and invite state before issuing an approved invite. Keep the invite link and token in private scratch files and out of chat, shell history and captured output. Clean up those files when finished. For a same-actor claim, compare the rider profile and dashboard sessions against the baseline.

- **Browser claim.** Open the Telegram Web `/k/#?tgaddr=` link with a URL-encoded `tg://resolve?domain=ByteloopRidersBot&start=<token>` value built privately from the invite file. The bot chat can claim automatically. Check the reply, local rider webhook and invite row before looking for **START**. If the row is still unclaimed, use a visible **START** button in the verified rider bot chat. If it is absent, the typed `/start` fallback can verify the handler and alert queue. Report the fallback separately from the browser-link result.
- **Cron and WhatsApp.** A successful claim writes the pending alert in `t_invites`. Correlate the next due `job_rider_invite_alerts` tick, local `/rider-hooks/invite-alerts` sweep, final `rider_alert_result`, `rider_alert_next_at` and `rider_alert_accepted`. Use the [WhatsApp observation steps](../verify-test-order-local-setup/SKILL.md#overwatch-alerts-on-whatsapp-web) for the matching message count in the monitored chat. Use [scheduled work verification](../verify-test-order-local-setup/SKILL.md#scheduled-work) if testing an outage.
- **Replay.** Reopen the same claimed link and verify the local webhook handled it. Compare `claimed_at` and `rider_claim_update_id` against the first claim, then check for an extra alert, hook call or matching message over subsequent scheduled ticks.

## Report evidence

For each checked scenario, report the boundary, command or live action, observed result, and any remaining unverified boundary. For a live browser check, pair the visible Telegram result with the matching server log evidence when available. Label evidence **offline**, **isolated database**, or **live Telegram**. Do not claim SQL, webhook durability, user-visible delivery, payment, or fulfilment from mocked Bot API calls or an HTTP 200 alone.

An aiogram MCP server can help observe an isolated live bot. It is optional and provides no replacement for user-driven Telegram checks, the dispatcher harness, or durable application state.
