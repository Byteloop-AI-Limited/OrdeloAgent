# Stale Restaurant Thread Closure

## Overview

Restaurant conversation cleanup is coordinated directly by PostgreSQL. The existing five-minute `pg_cron` entry calls `job_terminate_stale_active_threads()`; the Ordelo FastAPI service is not in the dispatch path.

The job selects stale active restaurant threads, reads retention from the latest LangGraph root checkpoint, and sends one batch directly to each restaurant service. SFCS and Elai trust that selection and ask the graph to call `terminate_conversation` without an additional preflight database query.

## Scheduled database job

**Location:** `OrdeloAgent/ordelo_datamodels/agent_threads/job_terminate_stale_active_threads.sql`

For each active thread with a non-null `last_access_dtts`:

1. Derive `rest_ref` from the uppercase prefix before the first hyphen in `thread_id`.
2. Join `restaurant_master` and apply `rest_stale_active_threads_minutes`.
3. Read the newest `checkpoints` row for the thread where `checkpoint_ns = ''`.
4. Skip a missing root checkpoint.
5. Skip only when `checkpoint.channel_values.retain_thread` is JSON boolean `true`. Missing, null, false, or malformed values are treated as not retained.
6. Resolve `{REST_REF}_APP_URL` from `ordelo_config`.
7. POST one unbounded batch per restaurant to `/thread-hooks/{rest_ref}/terminate-stale-active-threads`.

The legacy `thread.retain_thread` column is not used by this job. It remains in the schema for compatibility with older thread-management functions.

The job returns JSONB containing the run ID, selection counts, missing checkpoint/URL counts, prefix-agent mismatches, and per-restaurant HTTP dispatch results. It reports dispatch, not confirmed background completion.

## Restaurant request contract

```json
{
  "job_run_id": "12345678-1234-5678-1234-567812345678",
  "threads": [
    {
      "thread_id": "SFCS-154c76b0-4a38-411c-bb4a-9553249f6653",
      "recipient": "447000000001"
    }
  ]
}
```

The endpoint rejects a route that does not match the restaurant service configuration and any thread whose prefix does not match the route `rest_ref`. A valid request returns HTTP 202 with `job_run_id`, `received_count`, and `queued_count`.

## Restaurant background processing

Each service queues one batch worker and processes at most three threads concurrently. For each supplied `thread_id` and `recipient`, the worker builds the LangGraph configuration and invokes `run_rest_graph_with_custom_msg` with the existing inactivity instruction. It does not explicitly reread the thread or checkpoint before invocation. The graph retains its existing marketing-consent behavior and ultimately sends the goodbye message and marks the thread inactive through `terminate_conversation`.

Failures are isolated per thread and recorded in restaurant logs with `job_run_id`, `rest_ref`, and `thread_id`.

## Delivery and failure semantics

- Delivery is at least once; there is no database lease or deduplication claim across requests.
- Changes after database selection are intentionally not rechecked; a thread that becomes active before background execution can still be terminated.
- Failed or timed-out restaurant POSTs are not retried within the same SQL invocation. Still-active threads are reconsidered by the next five-minute run.
- Missing or empty `{REST_REF}_APP_URL` values skip that restaurant without blocking other batches.
- The direct endpoint is currently unauthenticated.
- The existing pg_cron registration is retained and must call `job_terminate_stale_active_threads()` with a five-minute cadence.
