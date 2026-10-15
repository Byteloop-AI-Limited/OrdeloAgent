---
name: telegram-api
description: Implement Telegram messaging and handlers with aiogram 3, especially migrating OrdeloAgent from PyWa/WhatsApp. Use for keyboards, callbacks, template-to-text conversion, locations, address forms, catalogs, identity mapping, and FastAPI webhook integration. Excludes Telegram user-account automation with MTProto.
---

# Telegram API

Use **aiogram 3.31.0** as the requested migration baseline. [Official documentation](https://docs.aiogram.dev/en/v3.31.0/index.html) and the [Telegram Bot API](https://core.telegram.org/bots/api) define behavior; community templates provide integration examples. Check the installed/locked version before implementing. Do not silently upgrade or copy aiogram 2.x patterns.

## Read only relevant references

- For Ordelo migration, read [the WhatsApp inventory and migration map](references/ordelo-migration.md): producers, handlers, templates, indirect notifications and incomplete/example paths.
- For API signatures, limits or capabilities, use [the official documentation index](references/api-docs.md), then open the linked versioned page. Verify uncertain details rather than inventing equivalent methods.
- For implementation, read [adaptation patterns](references/implementation-patterns.md): text, callbacks, identity, location and FastAPI. Examples are not a complete bot.
- For integration/architecture examples, read [the six inspected repositories](references/repository-patterns.md). Their Redis, ORM and DI choices are not Ordelo requirements.

## Migration approach

Inspect current source and project instructions. Trace sender → handler → domain transition → graph/persistence/notifications. Decide and explain the approach before edits. Skill creation or migration planning does not authorize application migration, database changes or live webhook registration.

Classify interactions as direct equivalents, rendering changes or new user flows. WhatsApp approved templates, Flow JSON, product catalogs/cart submissions, phone addressing and delivery/read statuses cannot simply be renamed into Telegram methods.

Keep delivery/payment rules and LangGraph checkpoints authoritative. aiogram FSM can collect conversational input; it must not become a second source of truth for assignments. Preserve stale-button/progress guards, the assigned rider's same-dispatch pre-pickup decline path and `/dontRespond` suppression after tools send messages.

## Constraints that change decisions

- Separate actor `from_user.id`, destination `chat.id` and Ordelo identity. Never cast a phone number or W-id to a Telegram destination. Use authenticated account linking; ordinary private-chat bots require user initiation before reaching a new user.
- Callback data is **1–64 UTF-8 bytes**, not characters. Use typed compact data or opaque server-side tokens. Authorize against the actual actor and current domain state; payload recipients, orders and human/AI instructions are untrusted.
- Acknowledge callbacks promptly, including denied, stale and throttled taps. Clearing the spinner does not confirm a business transition. Report its outcome separately.
- Inline buttons yield callback queries; reply-keyboard buttons yield messages. Location/contact request buttons are private-chat reply controls. URL buttons do not generate action callbacks.
- Render header/body/footer into text/captions, escape data for the parse mode and preserve full payment URLs. Ordinary bot messaging has no WA template approval or WA-style delivery/read receipt API.
- Separate OwnTracks tracking, sending a map pin, asking for location and receiving edited live locations. Telegram location does not expose PyWa's `current_location` flag or prove physical provenance.
- Authenticate FastAPI updates with the configured secret header before processing. Preserve pending updates, deduplicate domain mutations and define how long graph work survives HTTP acknowledgment. Background tasks alone are not durable delivery.

## Validate and report

For implementation, check callback packing including Unicode, actor/order authorization, stale/duplicate taps, identity linkage, location correlation, formatting/length and webhook rejection/replay as relevant. Mock Bot API calls for offline checks. Schema-valid messages and successful HTTP responses do not demonstrate user-visible delivery.

Report migrated paths, deferred interactions and offline versus live evidence. Keep external customer-facing restaurant apps and web customers explicit in scope: changing direct sends here does not migrate the entire customer journey.
