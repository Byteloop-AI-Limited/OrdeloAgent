/*
Direct stale-thread termination dispatcher.

The existing pg_cron schedule calls job_terminate_stale_active_threads() every
five minutes. This function now owns stale-thread selection and persisted-state
retention checks, then posts one batch directly to each restaurant service.

Routing and eligibility rules:
  * rest_ref is the uppercase prefix before the first '-' in thread.thread_id.
  * restaurant_master.rest_stale_active_threads_minutes supplies the timeout.
  * only the latest root checkpoint (checkpoint_ns = '') is inspected.
  * only JSON boolean true at channel_values.retain_thread retains a thread.
  * missing checkpoints are skipped; missing/null/malformed retain_thread values
    are treated as false.
  * thread.retain_thread is intentionally not used: LangGraph checkpoint state is
    the source of truth.

The function returns dispatch-level JSONB. Restaurant services trust the selected
batch and execute termination asynchronously, so this result does not represent
confirmed conversation closure.
*/

DROP FUNCTION IF EXISTS job_terminate_stale_active_threads_new();

CREATE OR REPLACE FUNCTION job_terminate_stale_active_threads_new()
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_run_id UUID := gen_random_uuid();
    v_started_at TIMESTAMPTZ := clock_timestamp();
    v_selection JSONB;
    v_restaurant_batch JSONB;
    v_restaurant_results JSONB := '[]'::jsonb;
    v_response http_response;
    v_webhook_url TEXT;
    v_http_success_count INTEGER := 0;
    v_http_failure_count INTEGER := 0;
BEGIN
    WITH stale_active AS (
        SELECT
            t.thread_id,
            t.agent,
            t.recipient,
            t.last_access_dtts,
            upper(split_part(t.thread_id, '-', 1)) AS rest_ref
        FROM public.thread AS t
        JOIN public.restaurant_master AS rm
          ON rm.rest_ref = upper(split_part(t.thread_id, '-', 1))
        WHERE t.is_active IS TRUE
          AND t.last_access_dtts IS NOT NULL
          AND t.last_access_dtts < (
              CURRENT_TIMESTAMP
              - make_interval(mins => rm.rest_stale_active_threads_minutes)
          )
    ),
    with_checkpoint AS (
        SELECT
            s.*,
            cp.checkpoint_id,
            cp.checkpoint -> 'channel_values' -> 'retain_thread'
                AS retain_thread_value,
            app_config.base_url
        FROM stale_active AS s
        LEFT JOIN LATERAL (
            SELECT
                c.checkpoint_id,
                c.checkpoint
            FROM public.checkpoints AS c
            WHERE c.thread_id = s.thread_id
              AND c.checkpoint_ns = ''
            ORDER BY c.checkpoint_id DESC
            LIMIT 1
        ) AS cp ON TRUE
        LEFT JOIN LATERAL (
            SELECT NULLIF(btrim(oc.config_value), '') AS base_url
            FROM public.ordelo_config AS oc
            WHERE oc.config_key = s.rest_ref || '_APP_URL'
            LIMIT 1
        ) AS app_config ON TRUE
    ),
    evaluated AS (
        SELECT
            w.*,
            (w.checkpoint_id IS NULL) AS checkpoint_missing,
            (
                w.retain_thread_value = 'true'::jsonb
            ) IS TRUE AS is_retained,
            (
                w.checkpoint_id IS NOT NULL
                AND (w.retain_thread_value = 'true'::jsonb) IS NOT TRUE
            ) AS is_eligible,
            (upper(w.agent) IS DISTINCT FROM w.rest_ref)
                AS agent_prefix_mismatch
        FROM with_checkpoint AS w
    ),
    restaurant_batches AS (
        SELECT
            e.rest_ref,
            e.base_url,
            jsonb_agg(
                jsonb_build_object(
                    'thread_id', e.thread_id,
                    'recipient', e.recipient
                )
                ORDER BY e.last_access_dtts, e.thread_id
            ) AS threads
        FROM evaluated AS e
        WHERE e.is_eligible
          AND e.base_url IS NOT NULL
        GROUP BY e.rest_ref, e.base_url
    ),
    batch_summary AS (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'rest_ref', rb.rest_ref,
                    'base_url', rb.base_url,
                    'threads', rb.threads
                )
                ORDER BY rb.rest_ref
            ),
            '[]'::jsonb
        ) AS batches
        FROM restaurant_batches AS rb
    ),
    missing_url_summary AS (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'rest_ref', missing.rest_ref,
                    'thread_count', missing.thread_count
                )
                ORDER BY missing.rest_ref
            ),
            '[]'::jsonb
        ) AS missing_url_restaurants
        FROM (
            SELECT
                e.rest_ref,
                count(*) AS thread_count
            FROM evaluated AS e
            WHERE e.is_eligible
              AND e.base_url IS NULL
            GROUP BY e.rest_ref
        ) AS missing
    ),
    counts AS (
        SELECT
            count(*) AS stale_active_count,
            count(*) FILTER (WHERE e.checkpoint_missing)
                AS missing_checkpoint_count,
            count(*) FILTER (WHERE e.is_retained)
                AS retained_count,
            count(*) FILTER (WHERE e.is_eligible)
                AS eligible_count,
            count(*) FILTER (WHERE e.is_eligible AND e.base_url IS NULL)
                AS missing_url_thread_count,
            count(*) FILTER (WHERE e.is_eligible AND e.base_url IS NOT NULL)
                AS dispatchable_count,
            count(*) FILTER (WHERE e.agent_prefix_mismatch)
                AS agent_prefix_mismatch_count
        FROM evaluated AS e
    )
    SELECT jsonb_build_object(
        'stale_active_count', counts.stale_active_count,
        'missing_checkpoint_count', counts.missing_checkpoint_count,
        'retained_count', counts.retained_count,
        'eligible_count', counts.eligible_count,
        'missing_url_thread_count', counts.missing_url_thread_count,
        'dispatchable_count', counts.dispatchable_count,
        'agent_prefix_mismatch_count', counts.agent_prefix_mismatch_count,
        'missing_url_restaurants', missing_url_summary.missing_url_restaurants,
        'batches', batch_summary.batches
    )
    INTO v_selection
    FROM counts
    CROSS JOIN batch_summary
    CROSS JOIN missing_url_summary;

    FOR v_restaurant_batch IN
        SELECT value
        FROM jsonb_array_elements(v_selection -> 'batches')
    LOOP
        v_webhook_url := rtrim(v_restaurant_batch ->> 'base_url', '/')
            || '/thread-hooks/'
            || (v_restaurant_batch ->> 'rest_ref')
            || '/terminate-stale-active-threads';

        BEGIN
            SELECT *
            INTO v_response
            FROM http_post(
                v_webhook_url,
                jsonb_build_object(
                    'job_run_id', v_job_run_id,
                    'threads', v_restaurant_batch -> 'threads'
                )::text,
                'application/json'
            );

            IF v_response.status BETWEEN 200 AND 299 THEN
                v_http_success_count := v_http_success_count + 1;
            ELSE
                v_http_failure_count := v_http_failure_count + 1;
            END IF;

            v_restaurant_results := v_restaurant_results || jsonb_build_array(
                jsonb_build_object(
                    'rest_ref', v_restaurant_batch ->> 'rest_ref',
                    'thread_count', jsonb_array_length(
                        v_restaurant_batch -> 'threads'
                    ),
                    'webhook_url', v_webhook_url,
                    'http_status', v_response.status,
                    'response_content', v_response.content,
                    'success', v_response.status BETWEEN 200 AND 299
                )
            );
        EXCEPTION
            WHEN OTHERS THEN
                v_http_failure_count := v_http_failure_count + 1;
                v_restaurant_results := v_restaurant_results || jsonb_build_array(
                    jsonb_build_object(
                        'rest_ref', v_restaurant_batch ->> 'rest_ref',
                        'thread_count', jsonb_array_length(
                            v_restaurant_batch -> 'threads'
                        ),
                        'webhook_url', v_webhook_url,
                        'success', FALSE,
                        'error', SQLERRM
                    )
                );
        END;
    END LOOP;

    RETURN (v_selection - 'batches') || jsonb_build_object(
        'job_run_id', v_job_run_id,
        'started_at', v_started_at,
        'completed_at', clock_timestamp(),
        'restaurant_batch_count', jsonb_array_length(v_selection -> 'batches'),
        'http_success_count', v_http_success_count,
        'http_failure_count', v_http_failure_count,
        'restaurant_results', v_restaurant_results
    );
END;
$$;

-- The existing pg_cron registration continues to call:
SELECT job_terminate_stale_active_threads_new();

----------------------------- DEBUG QUERY -----------------------------

-- 1. Evaluate both threads exactly against the dispatcher criteria.
WITH target_threads(thread_id) AS (
    SELECT DISTINCT thread_id
    FROM public.thread
    WHERE is_active = TRUE
),
evaluated AS (
    SELECT
        target.thread_id AS requested_thread_id,
        t.thread_id,
        t.agent,
        t.recipient,
        t.is_active,
        t.retain_thread AS legacy_thread_retain_value,
        t.dtts,
        t.last_access_dtts,
        CURRENT_TIMESTAMP AS database_time,
        CURRENT_TIMESTAMP - t.last_access_dtts AS thread_age,
        upper(split_part(t.thread_id, '-', 1)) AS derived_rest_ref,
        rm.rest_stale_active_threads_minutes AS stale_after_minutes,
        t.last_access_dtts
            + make_interval(
                mins => rm.rest_stale_active_threads_minutes
            ) AS became_stale_at,
        cp.checkpoint_id AS latest_root_checkpoint_id,
        cp.checkpoint
            -> 'channel_values'
            -> 'retain_thread' AS checkpoint_retain_value,
        jsonb_typeof(
            cp.checkpoint
                -> 'channel_values'
                -> 'retain_thread'
        ) AS checkpoint_retain_type,
        app_config.base_url
    FROM target_threads AS target
    LEFT JOIN public.thread AS t
      ON t.thread_id = target.thread_id
    LEFT JOIN public.restaurant_master AS rm
      ON rm.rest_ref = upper(split_part(t.thread_id, '-', 1))
    LEFT JOIN LATERAL (
        SELECT
            c.checkpoint_id,
            c.checkpoint
        FROM public.checkpoints AS c
        WHERE c.thread_id = t.thread_id
          AND c.checkpoint_ns = ''
        ORDER BY c.checkpoint_id DESC
        LIMIT 1
    ) AS cp ON TRUE
    LEFT JOIN LATERAL (
        SELECT NULLIF(btrim(oc.config_value), '') AS base_url
        FROM public.ordelo_config AS oc
        WHERE oc.config_key =
            upper(split_part(t.thread_id, '-', 1)) || '_APP_URL'
        LIMIT 1
    ) AS app_config ON TRUE
)
SELECT
    *,
    thread_id IS NOT NULL AS thread_exists,
    (
        is_active IS TRUE
        AND last_access_dtts IS NOT NULL
        AND last_access_dtts < (
            CURRENT_TIMESTAMP
            - make_interval(mins => stale_after_minutes)
        )
    ) AS is_stale,
    latest_root_checkpoint_id IS NULL AS checkpoint_missing,
    (
        checkpoint_retain_value = 'true'::jsonb
    ) IS TRUE AS is_retained,
    (
        latest_root_checkpoint_id IS NOT NULL
        AND (
            checkpoint_retain_value = 'true'::jsonb
        ) IS NOT TRUE
    ) AS checkpoint_eligible,
    base_url IS NOT NULL AS has_app_url,
    upper(agent) IS DISTINCT FROM derived_rest_ref
        AS agent_prefix_mismatch,
    (
        is_active IS TRUE
        AND last_access_dtts IS NOT NULL
        AND last_access_dtts < (
            CURRENT_TIMESTAMP
            - make_interval(mins => stale_after_minutes)
        )
        AND latest_root_checkpoint_id IS NOT NULL
        AND (
            checkpoint_retain_value = 'true'::jsonb
        ) IS NOT TRUE
        AND base_url IS NOT NULL
    ) AS should_be_dispatched_now,
    CASE
        WHEN thread_id IS NULL
            THEN 'thread_not_found'
        WHEN is_active IS NOT TRUE
            THEN 'already_inactive'
        WHEN stale_after_minutes IS NULL
            THEN 'restaurant_or_timeout_missing'
        WHEN last_access_dtts IS NULL
            THEN 'last_access_missing'
        WHEN last_access_dtts >= (
            CURRENT_TIMESTAMP
            - make_interval(mins => stale_after_minutes)
        )
            THEN 'not_stale_yet'
        WHEN latest_root_checkpoint_id IS NULL
            THEN 'skipped_missing_checkpoint'
        WHEN (
            checkpoint_retain_value = 'true'::jsonb
        ) IS TRUE
            THEN 'skipped_retained'
        WHEN base_url IS NULL
            THEN 'skipped_missing_app_url'
        ELSE 'eligible_and_dispatchable'
    END AS selection_result
FROM evaluated
ORDER BY requested_thread_id;


-- 2. Check which old/new dispatcher functions are deployed.
SELECT
    p.oid::regprocedure::text AS function_signature,
    pg_get_function_result(p.oid) AS return_type,
    l.lanname AS language,
    md5(p.prosrc) AS source_hash,
    p.prosrc ILIKE '%rest_stale_active_threads_minutes%'
        AS uses_restaurant_timeout,
    p.prosrc ILIKE '%checkpoint_ns = ''''%'
        AS reads_root_checkpoint,
    p.prosrc ILIKE '%/terminate-stale-active-threads%'
        AS posts_to_restaurant_endpoint,
    p.prosrc ILIKE '%http_post%'
        AS performs_http_post
FROM pg_proc AS p
JOIN pg_namespace AS n
  ON n.oid = p.pronamespace
JOIN pg_language AS l
  ON l.oid = p.prolang
WHERE n.nspname = 'public'
  AND p.proname IN (
      'job_terminate_stale_active_threads',
      'job_terminate_stale_active_threads_new'
  )
ORDER BY p.proname;


-- 3. Confirm which dispatcher function pg_cron actually calls.
SELECT
    jobid,
    jobname,
    schedule,
    command,
    database,
    username,
    active
FROM cron.job
WHERE command ILIKE '%terminate_stale_active_threads%'
   OR jobname ILIKE '%terminate%stale%thread%'
ORDER BY jobid;


-- 4. Inspect recent executions, including the period after 17:45 UTC.
SELECT
    details.jobid,
    job.jobname,
    job.command,
    details.runid,
    details.status,
    details.return_message,
    details.start_time,
    details.end_time,
    details.end_time - details.start_time AS duration
FROM cron.job_run_details AS details
JOIN cron.job AS job
  ON job.jobid = details.jobid
WHERE (
        job.command ILIKE '%terminate_stale_active_threads%'
        OR job.jobname ILIKE '%terminate%stale%thread%'
    )
  AND details.start_time >= TIMESTAMPTZ '2026-07-25 17:35:00+00'
ORDER BY details.start_time DESC
LIMIT 50;
----------------------------- END DEBUG QUERY -----------------------------
