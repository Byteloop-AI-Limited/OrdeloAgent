# Thread Closure System Documentation

## Overview

Elai implements an automated thread termination mechanism that identifies stale *active* WhatsApp conversation threads and ends them by prompting the Delivery LangGraph to call the `terminate_conversation` tool.

## System Components

### 1. Scheduled thread termination entrypoint (FastAPI)

**Endpoint**: `POST /thread-hooks/terminate-stale-active-threads`

**Location**: `watomation/routers/thread_hooks.py`

**How it works**:
1. Fetches stale active threads directly from Postgres via `ThreadHandler.get_stale_active_threads(stale_minutes=5)`.
2. For each stale thread:
   - Builds a LangGraph config:
     - `configurable.thread_id = <thread.thread_id>`
     - `configurable.recipient = <thread.recipient>`
   - Reads the current persisted graph state via `debug_state_values(config=config)`.
   - If `state_values.retain_thread == True`, the thread is **not** terminated.
   - Otherwise, schedules a background task to run the Delivery graph with a system instruction:
     - `system_msg="Call tool `terminate_conversation` with reason - Ending the conversation due to inactivity."`
3. Returns the stale thread records found (for logging/inspection).

**Important note**:
This endpoint does **not** accept an external payload of threads to close. It is responsible for querying the DB and deciding which threads to terminate.

## Thread Management Components

### Database Schema

**Table**: `public.thread`
- `thread_id` (text) - Primary key
- `recipient` (varchar(12)) - Phone number
- `is_active` (boolean) - Thread status
- `retain_thread` (boolean) - Intended to prevent automatic closure (default: false). **Currently dormant — no runtime code sets it (see "Retention" below).**
- `dt` (date) - Creation date
- `dtts` (timestamp) - Creation timestamp
- `last_access_dtts` (timestamp) - Last access timestamp

**Primary invariants**:
- A “session” in LangGraph is identified by `configurable.thread_id` (and typically also includes `configurable.recipient`).
- `last_access_dtts` is updated by `get_active_thread(agent, recipient)` when an active thread is fetched.
- Stale thread detection is purely DB-driven via `last_access_dtts` and `retain_thread`.

### Thread Handler Class

**Location**: `utils_common/thread_management/thread_handler.py`

**Key Methods**:
- `get_or_create_thread()` - Gets existing or creates new thread atomically
- `retain_thread()` - Sets retain_thread flag to true for active thread
- `make_threads_inactive()` - Marks threads as inactive for a recipient

### Database Functions

**Core Functions**:
- `get_active_thread()` - Gets active thread and updates last_access_dtts
- `create_thread()` - Creates a new thread
- `get_or_create_thread()` - Gets existing or creates new thread atomically
- `retain_thread()` - Sets retain_thread flag for active thread
- `make_threads_inactive()` - Marks threads as inactive
- `get_stale_active_threads(stale_minutes)` - Returns active, non-retained threads whose `last_access_dtts` is older than the threshold

**Location**: `utils_common/thread_management/thread_mgmnt.sql`

## Workflow Integration

1. **Thread Creation / Retrieval**
   - Most runtime entrypoints call `get_config_for_recipient(recipient)` (`utils_common/lg_utils.py`).
   - This uses `ThreadHandler.get_or_create_thread(recipient)` and returns:
     - `config = {"configurable": {"thread_id": <thread_id>, "recipient": <recipient>}}`

2. **LangGraph persistence (“session” management)**
   - `elai/agent_runner.py` compiles the Delivery graph with `AsyncPostgresSaver(pool)`.
   - The checkpointer persists graph state keyed by `configurable.thread_id`.

3. **Retention (`thread.retain_thread`) — currently dormant**
   - The `thread.retain_thread` column was designed as a manual override that exempts a thread from automatic closure: the cleanup queries (`job_close_thread()`, `get_stale_active_threads()`) only act on rows where `retain_thread` is `FALSE`/`IS NOT TRUE`.
   - **No runtime code currently sets it.** The writer path — the SQL function `retain_thread(p_agent, p_recipient)`, `ThreadHandler.retain_thread()`, and `lg_utils.retain_thread()` — is no longer invoked by the application. The former caller in `ordelo/agents/agent_runner.py::init_ordelo_graph()` was removed when termination moved to the LangGraph-driven flow. As a result the column always stays at its `false` default and the read-side filters are effectively no-ops.
   - These wrappers are kept for potential reuse but should be treated as dead code until a setter is wired back in. (See the open items in `notebooks/toDo.md`.)

4. **Runtime stale-thread handling lives in `watomation/routers/thread_hooks.py`**
   - Stale active threads are handled at runtime by the endpoints in `watomation/routers/thread_hooks.py` — notably `POST /thread-hooks/terminate-stale-active-threads` — rather than via the `retain_thread` column.

4. **Termination**
   - Termination is performed by the Delivery agent tool `terminate_conversation` (`elai/agents/delivery.py`).
   - That tool:
     - Calls `ThreadHandler.make_threads_inactive(recipient)` (DB update)
     - Sends a final WhatsApp message (“Thank you and good bye!”)

5. **DB-level stale detection**
   - `ThreadHandler.get_stale_active_threads(stale_minutes)` calls the SQL function `get_stale_active_threads(agent, stale_minutes)`.
   - The SQL function only returns threads where:
     - `is_active = TRUE`
     - `retain_thread IS NOT TRUE`
     - `last_access_dtts < now() - interval(stale_minutes)`

## Configuration Management

**Stale threshold**:
- Current code uses a fixed `stale_minutes=5` in `thread_hooks.py`.
- If you want this configurable, introduce an env/config key and plumb it into the endpoint.

**Usage Example (SQL)**:
```sql
-- Set thread retention for active thread
SELECT * FROM elas.retain_thread('ELAS', '447448440754');

-- Inspect stale threads (5 minutes)
SELECT * FROM elas.get_stale_active_threads('ELAS', 5);
```

## Error Handling

- Termination is performed in background tasks per-thread; failures will surface in app logs.
- Session corruption (OpenAI tool-call mismatch) is handled in `elai/agent_runner.py` by:
  - attempting a repair (remove the trailing AI tool-call message)
  - otherwise terminating the session by marking threads inactive.
