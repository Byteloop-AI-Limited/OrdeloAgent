/*
Run this migration outside an explicit transaction before enabling the direct
stale-thread dispatcher. CONCURRENTLY avoids blocking thread writes while the
historical table is indexed.
*/

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_thread_active_rest_ref_last_access
    ON public.thread (
        (upper(split_part(thread_id, '-', 1))),
        last_access_dtts
    )
    WHERE is_active IS TRUE
      AND last_access_dtts IS NOT NULL;
