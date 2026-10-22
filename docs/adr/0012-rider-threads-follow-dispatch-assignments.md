# ADR 0012: Rider graph threads follow dispatch assignments

## Status

Selected design (2026-10-15); implementation deferred to the rider migration.
The first Telegram phase moves restaurant admins only. It does not change
rider threads, checkpoints or graph behaviour.

Related: [migration handoff](../ordelo_telegram_implementation_handoff.md) and
[repository and messaging boundaries](0011-telegram-operations-messaging-stays-in-ordeloagent.md).

## Context

Current `ThreadHandler` and `get_config_for_recipient` resolve an active thread
by recipient and agent. The checked-in SQL generates an opaque ID; the rider
runner uses the recipient even when its caller knows the dispatch. Several
update, cleanup and closure paths resolve the recipient again. Consequently,
choosing a readable ID alone cannot establish job isolation.

`delivery_dispatch.dispatch_id` identifies an offer/assignment attempt and
already binds an internal rider to an order. A new assignment attempt must
have a new dispatch ID. Telegram callbacks carry action context, but an Accept
tap precedes confirmation of the assignment winner. An offer is therefore not
yet a running delivery conversation.

LangGraph's installed Postgres checkpointer stores `thread_id` as text. It
does not require a UUID. Its checkpoints also have a namespace and individual
checkpoint ID; those are different from the conversation's thread ID.

## Decision

For newly initialized rider conversations in the later rider phase, use:

```text
thread_id = ordelo:rider:dispatch:<dispatch_id>
example   = ordelo:rider:dispatch:84217
```

One thread covers one assigned dispatch, including completion or cancellation
and any outstanding cancellation-reason capture. Dispatch IDs must never be
reused or reassigned to another rider/order. Add a source/environment namespace
only if independent source databases share a checkpoint store.

| Identifier | Meaning |
| --- | --- |
| Telegram `from_user.id` | Actor making the request; maps to an authorized internal principal |
| Telegram `chat.id` | Destination for messages; does not identify the delivery conversation |
| Internal `rider_id` | Existing domain identity; do not replace with a Telegram ID |
| `dispatch_id` | Offer/assignment attempt linking rider and order |
| LangGraph `thread_id` | Stable history for that assigned dispatch |
| LangGraph `checkpoint_id` | One saved snapshot within the thread |

### Callbacks and message routing

- Use a compact versioned callback, for example `rd1:84217:accept`. Packing is
  serialization, not authorization. Validate the sender's internal rider,
  dispatch ownership, current state and allowed action against authoritative
  data before acting. Telegram callback data is limited to 1–64 bytes.
- Derive the stable thread ID from the validated dispatch. Do not use the
  complete callback as a thread ID: Accept, location and other actions must
  reach the same history. Do not duplicate mutable job details in that key.
- Index `(bot_key, chat_id, message_id)` to the dispatch and, when initialized,
  its thread. Offer messages may be indexed before a graph exists. Initialize
  only for the confirmed assignment winner; losing offers need no graph.
- Index replies to replies as well as root messages. Plain text without a
  reply can route automatically only when the eligible conversation is
  unambiguous; otherwise request a job selection. Never silently choose the
  most recently active thread.

### Lifecycle and concurrency

- Pass the exact validated dispatch/thread through state updates, invocation,
  location requests, alert-cue cleanup, completion and closure. Resolve the
  recipient only as identity/destination, not as a second thread lookup.
- Keep initialization idempotent and serialize work for each thread.
  Deterministic IDs do not prevent duplicate instructions, repeated effects
  or concurrent graph invocations by themselves. Database transitions still
  protect assignment races and rider eligibility across different threads.
- Closing dispatch A must not close dispatch B. Cancellation aftercare for A
  may overlap conversation B without authorizing two active deliveries.
- Retain `order_number`, `rider_id`, `dispatch_id` and lifecycle metadata with
  the conversation. Offer cleanup must not cascade-delete historical threads
  or leave their identity dependent on a deleted dispatch row.
- Keep existing persisted thread IDs intact. Do not rename historical
  checkpoint keys wholesale. Define the boundary for existing active jobs
  before implementing this later phase.

### Debugging and boundaries

Debug by exact thread or dispatch; list a rider's conversations when searching
by rider. Debug reads must not create a thread or refresh its activity.
Validate any explicit thread/recipient pair before invocation. Logs should
carry thread, dispatch, order and internal rider references so a callback can
be traced through graph execution and fulfilment events.

Customer conversation and web checkout IDs, including `food_order.thread_id`
and `agent=WEB` threads, retain their own lifecycle. Scope cleanup by agent
and exact conversation; do not change shared customer cleanup to infer rider
ownership from the new string format.

## Implementation impact and evidence

The repository review identified these later implementation points:

| Source | Required change |
| --- | --- |
| `utils_common/thread_management/thread_handler.py`, `thread_mgmnt.sql` | Exact dispatch/thread lookup, atomic initialization and exact closure; preserve historical metadata |
| `utils_common/lg_utils.py`, `ordelo/agents/agent_runner.py` | Replace recipient-based configuration resolution throughout init, invoke, update and cleanup; make debug reads read-only |
| `watomation/routers/thread_hooks.py` | `/run-system-message` must use and validate its explicit thread instead of reducing it to a recipient |
| `watomation/routers/delivery_hooks.py`, `ordelo/wa_location.py` | Carry known dispatch context through food-ready, adjusted pickup, alert and location events |
| `ordelo/agents/rider_agent.py` and close-thread routes/jobs | Close only the intended conversation, including cancellation aftercare |
| `scripts/debug_thread_messages.py`, `ordelo_datamodels/agent_threads/get_latest_state.sql` | Retain exact-ID inspection; expose dispatch lookup without implicitly selecting the latest recipient thread |
| `ordelo_datamodels/dispatch/delivery_dispatch.sql` and dispatch cleanup functions | Enforce immutable assignment identity and retain conversation audit metadata across offer deletion |

These are checked-in source findings, not a claim about deployed schema or
completed changes. Verify duplicate thread SQL definitions and active cleanup
jobs when implementing. Existing string-based debug/checkpoint APIs can
accept the selected format; their surrounding lookup semantics still matter.

## Alternatives and consequences

- **Opaque random ID:** technically valid, but adds a dispatch-to-thread lookup
  without improving isolation. Retain existing IDs; use the deterministic key
  for new rider conversations in this phase.
- **Telegram user/chat ID:** identifies an actor/destination across jobs and
  mixes their histories.
- **Order number alone, or rider plus order:** does not explicitly distinguish
  separate assignment attempts for the same order.
- **Whole packed callback:** changes with each action, couples persistence to
  transport encoding and does not remove authorization checks.

Thread policy is independent of adopting Telegram. The restaurant-admin bot
uses deterministic actions and order/message correlation without LangGraph.
Rider takeover, live-location ingestion and multiple simultaneous deliveries
are separate capabilities; this decision does not implement or approve them.

Later acceptance evidence must cover duplicate assignment initialization,
competing accepts, stale callbacks, reply-chain routing, ambiguous plain text,
concurrent events for one thread, A's cancellation cleanup after B starts,
read-only exact debug, and historical lookup after dispatch cleanup.

## References

- [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Telegram inline callback data](https://core.telegram.org/bots/api#inlinekeyboardbutton)
- [aiogram callback packing](https://docs.aiogram.dev/en/v3.31.0/dispatcher/filters/callback_data.html)

## Amendment 1 - 22 October 2026 (thread id format; shared table untouched)

Decided with the owner in the rider grilling session
([rider plan](../../plans/telegram-rider-bot-plan.md), D46, D47).

- **Format.** New rider threads use `thread_id = ORDELO-dispatch-<dispatch_id>`, not
  `ordelo:rider:dispatch:<id>`. The `thread` table is shared with restaurant-agents
  and the WEB checkout, whose ids are `<agent>-<uuid>` (`ELAS-…`, `WEB-…`), and the live
  per-restaurant stale-thread cron (`job_terminate_stale_active_threads_new`) reads the
  restaurant from `upper(split_part(thread_id, '-', 1))`. `ORDELO-dispatch-…` parses
  exactly like today's rider ids (`ORDELO-<uuid>`, never a 4-letter `rest_ref`) and keeps
  the convention.
- **No schema change to `thread`.** No new columns; `create_thread`,
  `get_or_create_thread`, `make_threads_inactive`, the cron jobs, restaurant-agents and
  customer threads are untouched. Rider-only SQL (`agent_threads/rider_threads.sql`,
  phase R2) adds `rider_thread_open` (idempotent insert of the computed id) and
  `rider_thread_close(thread_id)` (exactly one row). Nothing parses the id: code
  computes it from the dispatch; rider → dispatch comes from `delivery_inflight` and
  the graph state.
- **At most one active rider thread per rider (D47)**, enforced when a thread opens:
  opening B closes A and records A's pending cancel reason as not given. This replaces
  the "job selection prompt" and reply-index routing above for the overlap case;
  inbound text goes actor → rider → the single active thread. The scheduled stale
  close also closes a rider thread whose cancel reason is still missing;
  `retain_thread` stays `false` on rider threads.
