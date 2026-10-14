# ADR 0011: Telegram operations messaging stays in OrdeloAgent, behind an operations-messaging port

## Status

Proposed (2026-10-14).

Scope: the rider, restaurant-admin and overwatch messaging that OrdeloAgent
sends and receives today over WhatsApp. Operational fulfilment covers orders
from both web and WhatsApp. Customer conversation and checkout implementations
keep their existing owners and contracts. Source brief:
[Telegram implementation handoff](../ordelo_telegram_implementation_handoff.md).

## Context

WhatsApp is not at the edge of OrdeloAgent; it runs through the middle of it.

- **The rider agent sends directly.** `ContextSchema` in
  `ordelo/agents/rider_agent.py` carries `wa_client: WhatsApp` and a phone
  `recipient`. Its tools and response node call the client directly and build
  `pywa` objects inline.
- **Business rules live inside PyWA callback handlers.**
  `on_callback_wa_handler.dispatch_response` decides the stale-tap,
  already-inflight and taken-by-another-rider outcomes, using `msg.sender` as
  `rider_id`. Other handlers in that file (pickup time, restaurant
  accept/decline, admin ready, adjust pickup time, shift availability) follow
  the same pattern.
- **Operational outbound sends extend beyond the rider agent.** The
  `delivery_hooks`, `takeaway_hooks` and `location_hooks` routers send directly
  through WhatsApp clients or `wa_senders`; `customer_hooks` uses a WhatsApp
  sender for restaurant-admin feedback. Overwatch and admin notices have the
  same coupling. Customer-facing notifications remain a separate concern.
- **Identity is the phone number.** `rider_id` is the digits-only phone
  (`VARCHAR(12)`), the auth-session principal, and the LangGraph thread key
  (`ThreadHandler.get_or_create_thread(recipient)`).

Telegram changes these things: identity (a Telegram user/chat ID bound
to a rider through a one-time invite), conversation addressing (a root message
per job plus reply chains, with each `(bot, chat_id, message_id)` mapped to
the relevant job and graph thread), interaction primitives (inline callbacks
with a 64-byte payload, reply-keyboard location requests, live-location edits), restaurant alerts that
repeat until acknowledged, and operator takeover through an operations group.
The message index works whether graph threads are per rider or per rider and
job; Telegram does not decide that thread policy.

The handoff fixes FastAPI + Supabase + LangGraph as the system of record and
treats Telegram as a transport.

Two precedents exist in the estate:

- **restaurant-agents is a separate repository and deployment.** That works
  because each app owns an entire customer conversation and meets Ordelo
  through about ten narrow HTTP hooks (ADR 0003, ADR 0006).
- **The customer notifier already has a channel seam.** It selects a channel
  adapter per subscription (`RestaurantAppWebhookAdapter`, `WebPageAdapter`).
  Operations messaging has no equivalent.

## Decision

1. **Telegram lives in OrdeloAgent.** Its webhook route joins the existing
   FastAPI app. No new repository is needed for the messaging adapter; durable
   scheduled work can run as a separate process from the same repository.
2. **Domain code reaches riders, restaurant admins and overwatch only through
   an operations-messaging port**, a deep module in `ordelo/ops_messaging/`.
   The rider agent's tools, operational sends from the DB-trigger routers,
   restaurant-admin feedback, and overwatch/admin alert senders all call the
   port. The customer notifier remains separate. None of these callers
   imports `aiogram`.
3. **The port speaks in domain intents, not messaging primitives.** The domain
   says *what* to communicate (offer this job, pickup is ready, here is the
   drop-off, ask for location, send this restaurant acknowledgement request or
   reminder). The Telegram adapter decides *how*: text, inline or reply keyboards,
   callback-data packing, `ReplyParameters` threading, and writing the message
   index. A generic `send_text(to, text, buttons)` interface is rejected
   because it would leak Telegram's shape (64-byte callbacks, the split
   between reply and inline keyboards, chat-scoped message IDs) back into
   every caller.
4. **Inbound updates become domain commands.** aiogram routers parse an update,
   resolve the actor and the conversation, and call transport-neutral command
   handlers. Stale-tap, already-on-a-job, taken-by-another-rider and
   same-dispatch pre-pickup cancellation checks currently inside
   `dispatch_response`, plus the other button-handler rules, move into those
   handlers before Telegram handlers are added. These handlers belong to the
   relevant domain module, not to `ops_messaging`. Postgres remains the owner
   of authoritative transitions, but current race safety is not established:
   callbacks read state before separate writes, and the checked-in assignment
   function does not demonstrate serialization across competing orders/riders.
   Verify and, where necessary, add conditional writes and narrow locking at
   those transitions. Keep orchestration and policy in Python.
5. **The Telegram adapter owns Telegram state**: identities, invites, the
   message index and the ops-relay index. The domain refers to riders by their
   internal rider reference and to rider/job conversations independently of
   Telegram chats or graph thread IDs. Identity binding authenticates a known
   principal; domain handlers still check current rider assignment, restaurant
   membership or operator permission for every action. A chat ID or callback
   payload alone is not authorization.
6. **Restaurant acknowledgement is a separate fulfilment module** in
   `ordelo/restaurant_acknowledgement.py`, used by delivery and collection.
   It coordinates the authoritative conditional status transition, reminder
   eligibility and stop rule, and escalation. It asks the messaging port to
   send notices; the Telegram adapter does not decide when to repeat or stop.

### Module ownership and interface

The interface expresses business intent: offer a job, communicate delivery
instructions or pickup readiness, provide a pickup/drop-off location, request
a current location, notify restaurant admins, or escalate to overwatch. Agent
replies also need an operation carrying text plus a neutral conversation
reference; requiring an intent does not mean replacing generated text with a
fixed template. Callers never construct keyboards or provider message objects.

| Module | Owns | Does not own |
| --- | --- | --- |
| Dispatch actions | Valid actor/offer, stale-tap and assignment checks, pre-pickup cancellation, eligibility | Telegram callback encoding |
| Restaurant acknowledgement | Manual attention, pickup-stage coordination, reminder eligibility, timeout races and escalation | Bot rendering or a new payment contract |
| Rider conversations | Job correlation, graph invocation, agent/operator control and send fencing | Telegram reply syntax or an implicit per-job thread policy |
| Location requests | Authorized request/response correlation and location eligibility | Telegram update parsing |
| Operations messaging | Intent-based outbound interface and neutral message references | Fulfilment decisions, graph ownership or reminder schedules |
| Telegram adapter | Provider ingress/egress, identity bindings, message/relay index and presentation | Deciding who may accept, cancel or take over a job |

Finalize the smallest interface against real callers during extraction. This
ADR does not require three separate Protocols, a command bus or a universal
event framework. A test adapter enables focused tests; it does not establish
that an independently reusable messaging product exists.

### Repository layout

```text
ordelo/
  agents/rider_agent.py        tools take the messaging interface; no transport imports
  dispatch_actions.py         extracted dispatch decisions; existing DB transitions
  restaurant_acknowledgement.py  delivery + collection acknowledgement, reminder and escalation rules
  rider_conversations.py      job/graph correlation, operator control and send fencing
  location_requests.py        evolved from wa_location.py; preserve demand/observation lifecycle
  ops_messaging/               the port, transport-neutral
    ports.py                   outbound interface
    models.py                  intents and neutral conversation/message references
channels/
  telegram/
    bots.py                    bot registry: one Bot + Dispatcher per bot_key
    routers/rider.py           aiogram -> verified actor + domain action
    routers/restaurant.py
    routers/ops.py             operations group: relay, takeover, release
    callbacks.py               CallbackData classes
    render.py                  intent -> text, keyboard, ReplyParameters
    adapter.py                 implements the ports; writes the message index
    identity.py                invite deep links, /start claim, identity lookup
    message_index.py
    inbox.py                   durable receipt/claim/completion by (bot_key, update_id)
watomation/routers/telegram_webhook.py  thin route: secret check, validated durable handoff
watomation/                    existing FastAPI app + DB-trigger routers; operational sends use the port
config/telegram_setting.py     per-bot token and webhook secret (AWS Secrets Manager / env fallback)
ordelo_datamodels/migrations/  minimal identity, message index, inbox, control and alert persistence
scripts/telegram_webhook.py    status | local | prod
tests/ordelo/                 domain actions/conversations/location through their interfaces
tests/ordelo/test_restaurant_acknowledgement.py  delivery + collection races and stop rules
tests/channels/telegram/       routers and adapter against recorded Update payloads
```

`channels/` is a new top-level package (add it to
`[tool.hatch.build.targets.wheel].packages`). The Telegram adapter lives there;
the thin FastAPI webhook route stays under `watomation/routers/`, matching the
current route layout.

Names above indicate ownership, not a requirement to create every file or table
up front. Reuse existing domain models, auth-session principals and persistence
where they already express the needed concept. Extract responsibilities as
their callers move; avoid a repository-wide rename of `watomation` or a new
top-level `services` hierarchy as part of this migration.

### Acknowledgement and durable work

Manual acknowledgement and completing pickup-time selection are different
stages. Stop initial attention reminders after the first valid acknowledgement;
do not silently abandon an accepted order with no pickup time. The later
stage's reminder/escalation policy needs an explicit decision. Preserve
creation-time configured-auto suppression (ADR 0001) and existing timeout
fallback semantics until separately changed. Every manual and timeout writer
must condition its transition on current state; delivery and collection retain
their distinct lifecycle and payment outcomes.

Do not introduce a restaurant Reject button as a transport change. The current
sender disables Decline, and the delivery decline handler reopens dispatch by
setting `unassigned`. Rejection and cancellation/payment semantics must be
resolved before exposing that action.

Restaurant alerts that repeat until acknowledged need a durable ledger and a
scheduled claim-and-send path, for example a database job calling a hook or a
separate worker from this repository. Each attempt checks current fulfilment
state and stops that stage's reminders when it is resolved or no longer eligible.
Persist the alert obligation with the qualifying order transition, or recover
it through a database sweep. A ledger created only after a fallible DB-to-HTTP
notification can lose the entire obligation. The hook may accelerate work.
Scheduling alone cannot prevent duplicate sends after an ambiguous failure;
claims, idempotency and reconciliation are required. A sender accepting a
request does not prove that an admin received or read the message. The customer
notifier's at-most-once callback policy (ADR 0006) does not apply to these
operational alerts.

The inbound-update inbox is separate from the reminder ledger. Verify the
webhook secret and atomically persist/deduplicate `(bot_key, update_id)` before
returning success; workers claim and complete that receipt with crash recovery.
Duplicate receipts must preserve unfinished work. Marking an update as seen and
then launching an in-memory task can permanently lose it. Replayed processing
still needs idempotent domain actions; this does not promise exactly-once sends.
This receipt policy follows Telegram's documented retry-on-unsuccessful-response
contract ([Bot API](https://core.telegram.org/bots/api#setwebhook)).

## Considered options

- **Separate repository and service (a "Telegram gateway") that calls
  OrdeloAgent over HTTP.** Rejected. Its interface would be nearly as wide as
  its implementation: offer accept/decline with the atomic race, pickup-time
  selection, admin ready and adjust, location ingest, rider-graph invocation,
  operator takeover with fencing, and alert acknowledgement. Each agent tool
  send would become a network call. The takeover rule ("read the control mode
  immediately before sending") would become a distributed check. The
  message-index lookup and the dispatch transaction would sit on opposite
  sides of a network. Deletion test: removing the gateway would not remove
  complexity; it would move back into OrdeloAgent unchanged. The
  restaurant-agents precedent does not carry over, because those apps own
  their conversation and graph behind a narrow hook contract, whereas the
  rider conversation *is* OrdeloAgent's rider agent.
- **Separate repository published as a shared transport library.** Rejected.
  It has one consumer, so it adds versioning and release overhead with no
  leverage.
- **Keep it in this repository but call aiogram directly**, the way PyWA is
  called today (`ctx.tg_bot.send_message` inside tools, rules inside aiogram
  handlers). Rejected. It swaps PyWA coupling for aiogram coupling, copies
  `dispatch_response`-style rules into a second set of handlers, and makes
  every domain test depend on a transport fake.

## Consequences

- **Graph thread cardinality remains undecided.** Current lookup reuses an
  active thread by rider recipient, and normal assignment excludes a rider
  already in `delivery_inflight`. Telegram message-to-job/thread indexing is
  needed either way. Moving to one graph thread per rider and job, if chosen,
  needs its own decision and change to `ThreadHandler`,
  `get_config_for_recipient`, `agent_runner` and alert cues.
- **Rider identity.** The internal rider reference stays the domain key. The
  Telegram user ID is a mapping owned by the adapter. Phone-based flows
  (`/login` and `/sysadmin` session links, auth-session principals) need
  Telegram-command equivalents that resolve through `telegram_identities`.
- **Extraction comes before the adapter.** The rules in the WA callback
  handlers move into their owning domain modules first. Test business outcomes
  through those modules' interfaces, using a messaging test adapter. Replace
  transport-coupled assertions only after equivalent behaviour is covered;
  retain adapter contract tests.
- **The webhook remains in the current FastAPI deployment.** Configuration
  gains one token and webhook secret per bot. The local testing runbook gains
  dev-bot webhook switching via `scripts/telegram_webhook.py`; webhooks are
  never set on app startup. A durable reminder worker may be deployed
  independently from the same repository.
- **Startup construction must become explicit.** `config/__init__.py`
  currently eagerly imports WABA configuration and clients. Construct channel
  dependencies at application/worker startup and close them on shutdown;
  independent process entrypoints must load only their required dependencies.
- **Location is a lifecycle, not just a send.** Evolve `WaLocation`'s existing
  demands, observations and assignment validation into a neutral module.
  Normalize provider message references and persisted source fields. Preserve
  graph history and deterministic request correlation; neither a parallel
  location store nor Telegram live-location tracking is decided here.
- **Graph decoupling includes state and effects.** Replace provider-specific
  reply IDs, location-request fields, contacts and reactions, not just
  `ContextSchema.wa_client`. Preserve `/dontRespond` behaviour and explicit
  closure of the intended conversation. Operator takeover requires durable
  control state and serialized sends or fencing against stale graph work;
  checking a flag once before a send is insufficient.
- **Payment and printer ownership remains unchanged.** Preserve collection
  capture at finalized pickup time (ADR 0002), the existing payment contract
  (ADR 0004), and pay-at-restaurant print-only behaviour. Replacing a kitchen
  receipt with Telegram does not disable external printing. Printer retirement
  requires a separate decision across the payment/printing owners.
- **One-or-two-bot remains open.** The `bot_key` routing supports either
  choice without changing the port.
- **Risk:** Telegram ingress shares a process with the dispatch hooks, so a
  slow or flooded handler competes with them. Mitigation: verify the secret,
  deduplicate through the bot-scoped inbox, return after durable receipt, and
  process work with bounded concurrency and recovery. Separate domain ordering
  and locks are still needed for concurrent updates to the same job.

## Migration acceptance checks

These are implementation gates, not claims that this review tested runtime
behaviour or verified the deployed database.

| Area | Required evidence |
| --- | --- |
| Outbound coverage | Rider graph, all four operational DB-hook callers, restaurant/admin and overwatch sends use the interface; provider imports remain inside adapters/composition |
| Dispatch | Wrong actor, stale offer, two riders accepting one order, one rider competing for two orders, duplicate update and same-dispatch pre-pickup cancellation preserve allowed transitions |
| Restaurant confirmation | Competing admins and stale timeout cannot overwrite the winner; configured-auto suppression holds; initial acknowledgement and missing pickup time have distinct handling |
| Identity and control | Revoked restaurant/operator permission, old job messages and graph work completing after takeover cannot authorize stale actions |
| Location | Responses match the authorized rider/order/dispatch request and enter the right conversation; invalid and unsolicited observations follow existing eligibility rules |
| Reliability | Restart after receipt, missing DB hook and ambiguous send outcome recover without losing the obligation or claiming confirmed delivery |
| TEST3100 | Initial offers and missed-dispatch notices recheck exact order items and current eligibility/overwatch membership using internal rider identity (ADR 0010) |
| Existing journeys | Both origin channels and fulfilment modes retain payment, customer-notifier, checkout-thread and configured-auto contracts (ADRs 0001–0010) |

## Evidence and document authority

The handoff is a proposal/discussion record. This ADR incorporates later session
clarifications; it remains Proposed. Accepted ADRs 0001–0010 govern retained
contracts. Where descriptive guides conflict, the checked-in implementation
describes current behaviour, including defects; historical plans and release
reports do not establish deployed behaviour.

Principal source checks: `on_callback_wa_handler.dispatch_response`,
`agent_app_handlers.initial_handle_of_rider_response`,
`job_assign_dispatch.sql`, `rider_agent.py`, `wa_location.py`,
`delivery_hooks._handle_restaurant_timedout`, the collection equivalent,
`wa_senders.admin_order_reciept`, and `config/__init__.py`.

## Revisit when

- A second independently owned system needs the same bots and a stable remote
  interface has emerged. Shared bot use alone does not require a separate
  repository; revisit the split when ownership and release cycles diverge.
- Telegram ingress needs isolation or scaling independent of dispatch. Before
  splitting the repository, consider running the same image as a second
  process with a different entrypoint.
- A different owner takes over operations messaging.
