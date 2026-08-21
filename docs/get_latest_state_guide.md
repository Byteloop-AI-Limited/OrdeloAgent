# `get_latest_state` Usage Guide

## Overview

`get_latest_state` is a Postgres function that exposes the most recently persisted LangGraph checkpoint state for a recipient as JSONB, without going through `AsyncPostgresSaver` or compiling the graph. It's the cheapest way to answer "what does the agent currently believe about this rider's delivery?" from SQL, Supabase REST, or a Python script.

Full storage mechanics (checkpoint tables, inline vs. blob-backed channels, thread resolution) are documented in the header comment of `ordelo_datamodels/get_latest_state.sql:1-27` — read that first if you need the "why", not just the "how". This guide covers what a caller actually needs: which fields are readable, the one caveat that catches people out, and worked examples.

## Location

```sql
-- Deployed as a Postgres function; call via SQL or Supabase RPC
SELECT get_latest_state(p_recipient, p_agent, p_state_key);
SELECT get_latest_state_by_thread(p_thread_id, p_state_key);
```

```python
# Supabase REST, from Python
client_ordelo.rpc("get_latest_state", {"p_recipient": ..., "p_agent": ..., "p_state_key": ...}).execute()
```

Source: `ordelo_datamodels/get_latest_state.sql`.

## Function Signatures

```sql
get_latest_state(p_recipient VARCHAR, p_agent TEXT DEFAULT NULL, p_state_key TEXT DEFAULT NULL) RETURNS JSONB
get_latest_state_by_thread(p_thread_id TEXT, p_state_key TEXT DEFAULT NULL) RETURNS JSONB
```

`get_latest_state` resolves the recipient's newest **active** thread, then delegates to `get_latest_state_by_thread`. Use the `_by_thread` variant directly when you already have a `thread_id` (e.g. from `ThreadHandler`).

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `p_recipient` | `VARCHAR` | WhatsApp phone number / rider or customer identifier |
| `p_agent` | `TEXT`, optional | Agent name (e.g. `"ORDELO"`). Matched case-insensitively. **`NULL` means "any agent" — and so does a `NULL` value stored on the thread row itself** (`get_latest_state.sql:145`, `OR t.agent IS NULL`). Passing an agent name is not a hard filter if some threads have no agent recorded. |
| `p_state_key` | `TEXT`, optional | A single `AgentState` channel name. When given, the return value is the bare JSONB for that key rather than the full envelope. |
| `p_thread_id` | `TEXT` | A known thread id, for `get_latest_state_by_thread` |

### Returns

- `p_state_key IS NULL` → the full envelope: `{thread_id, checkpoint_id, checkpoint_ts, state, blob_channels}` (plus, for `get_latest_state` only, `agent`, `recipient`, `thread_retain_thread`, `thread_dtts`, `thread_last_access_dtts`)
- `p_state_key` given → the bare JSONB value of that channel (`NULL` if the key is absent, or blob-backed)
- `NULL` when there is no active thread, or no root checkpoint exists yet

## Which fields are actually readable

This is the function's main trap. `rider_agent.AgentState` (`ordelo/agents/rider_agent.py:85-98`) has thirteen fields, but only the primitive ones are SQL-visible:

| Readable inline (SQL-visible) | Blob-backed (`get_latest_state` returns `NULL`) |
|---|---|
| `rider_name`, `dispatch_id`, `order_number`, `reply_to_msg_id`, `delivery_start_dtts`, `is_restaurant_confirmation_code_verified`, `is_customer_confirmation_code_verified`, `awaiting_cancel_reason`, `latest_wa_msg_id`, `pickup_time`, `wa_location_request_id`, `force_wa_location_prompt` | `messages` |

Rule of thumb: primitives (`str` / `int` / `bool` / `None`) are inlined into `checkpoint -> 'channel_values'` and are SQL-readable. Anything structured (LangChain message objects, dicts, Pydantic models) is msgpack-serialised into `public.checkpoint_blobs`, which SQL cannot decode — `get_latest_state` reports those as metadata only (`channel`, `type`, `size_bytes`) under `blob_channels` in the full envelope, and as bare `NULL` for a single-key lookup.

**`retain_thread` is not one of these fields.** It's a `public.thread` table column (`utils_common/thread_management/thread_mgmnt.sql:8`), set via `ThreadHandler.retain_thread()` (`thread_handler.py:111`) — not part of `AgentState` at all. `get_latest_state` (not `_by_thread`) exposes it correctly as `thread_retain_thread` in the full envelope; asking for it via `p_state_key='retain_thread'` will always return `NULL`, because there is no such channel to find.

## The active-thread caveat

`get_latest_state` resolves only threads with `is_active IS TRUE` (`get_latest_state.sql:142`). Once a thread is closed — by an explicit close (e.g. `verify_customer_confirmation_code` on delivery completion) or by `job_terminate_stale_active_threads` — every key reads back `NULL`, indistinguishable from "this was never true".

This is exactly why `ordelo/delivery_progress.check_delivery_progress()` does **not** use this function to answer "has the food been picked up?" post-completion: it reads `delivery_inflight` / `delivery_dispatch.status` instead, which stay correct after the thread closes. Reach for `get_latest_state` for *in-flight* questions; reach for the delivery tables for anything that needs to stay answerable after completion. See `docs/pickup_time_logic.md` and `CONTEXT.md`'s "Delivery progress" entry.

Read-only by design: unlike `get_active_thread()`, this never bumps `thread.last_access_dtts`, so reading state can never itself keep a stale thread alive.

## Usage Examples

### Full state envelope for a recipient

```sql
SELECT get_latest_state('447700900123', 'ORDELO');
```

### Any agent (latest active thread wins)

```sql
SELECT get_latest_state('447700900123');
```

### Single value, bare JSONB

```sql
SELECT get_latest_state('447700900123', 'ORDELO', 'order_number') #>> '{}' AS order_number;
SELECT (get_latest_state('447700900123', 'ORDELO', 'is_restaurant_confirmation_code_verified') = 'true'::jsonb) IS TRUE AS picked_up;
```

The `#>> '{}'` idiom unwraps bare JSONB into a plain text value — needed because a single-key lookup returns JSONB, not SQL `text`/`boolean` directly.

### Straight from a known thread_id

```sql
SELECT get_latest_state_by_thread('ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9');
SELECT get_latest_state_by_thread('ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9', 'dispatch_id');
```

### From Python via Supabase REST

```python
from config import client_ordelo

response = await asyncio.to_thread(
    lambda: client_ordelo.rpc(
        "get_latest_state",
        {"p_recipient": recipient, "p_agent": "ORDELO", "p_state_key": "pickup_time"},
    ).execute()
)
value = response.data  # bare JSONB value, or None
```

This is the exact pattern `ordelo/agents/agent_runner.is_food_already_picked_up()` uses — kept in the codebase, unused, as a worked example even though its callers have moved to `check_delivery_progress()`.

## Debug queries

`ordelo_datamodels/get_latest_state.sql` (bottom of the file) ships two ready-to-run debug queries:

1. Every active thread with its resolvable state, to see who has no checkpoint yet.
2. Which state keys are SQL-readable (inline) vs. msgpack-only (blob), for one given `thread_id` — the fastest way to confirm the inline/blob table above against live data.

Both are safe to run ad hoc; neither mutates anything.

## Related

- `ordelo_datamodels/get_latest_state.sql` — full source, storage-mechanics header, debug queries
- `ordelo/delivery_progress.py` — the delivery-tables-based check that supersedes `is_food_already_picked_up` for post-pickup questions
- `docs/pickup_time_logic.md` — section C, where this history is discussed in context
- `utils_common/thread_management/thread_mgmnt.sql` — `retain_thread` and thread lifecycle functions
