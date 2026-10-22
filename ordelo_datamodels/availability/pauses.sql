-- =============================================================================================
-- ordelo_datamodels/availability/pauses.sql
-- Pauses: a person steps away from jobs or alerts until a mandatory end time; "paused" is computed from the clock.
-- =============================================================================================
-- LIVE CHECK    Live since 2026-10-22 (migrations/rider_telegram_r1.sql step 3; ADR 0013). Nothing writes pauses until phase R5 (/off).
-- OBJECTS       table  pauses
--                   One row per pause: who (audience + principal [+ scope]), from, until (mandatory), and how it ended.
--               fn     pause_duration(p_audience text, p_duration text) -> interval
--                   The interval for a duration key such as '6h' or '1d' if ordelo_config allows it for this audience, else NULL.
--               fn     is_paused(p_audience text, p_principal text, p_scope text) -> boolean
--                   true while an open pause covers now(); the ONE place that answers "is this person paused?".
--               fn     pause_current(p_audience text, p_principal text, p_scope text) -> jsonb
--                   The pause covering now(), or {result: 'not_paused'}; read-only.
--               fn     pause_start(p_audience text, p_principal text, p_scope text, p_duration text, p_via text, p_by text) -> jsonb
--                   Start a pause, or move the end time of the current one (never stacks); the end time is mandatory.
--               fn     pause_end(p_audience text, p_principal text, p_scope text, p_reason text) -> jsonb
--                   End the current pause early ('resumed' by the person, 'operator' by Ordelo).
-- REQUIRES      core/ordelo_config.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Inserts the PAUSE_DURATIONS_RIDER, PAUSE_DURATIONS_REST_ADMIN and PAUSE_REMIND_BEFORE_MINS config rows if missing.
-- HOW IT FITS   ADR 0013. Availability is DERIVED, never flipped back by a job:
--                 is_paused(audience, principal, scope) = an open row (ended_at IS NULL) with starts_at <= now() < ends_at.
--                 The moment ends_at passes the person is available again, with no job involved, so a late, failed or
--                 mis-pointed sweep can only delay a MESSAGE, never leave someone switched off.
--               Audiences: 'rider' (principal = rider_master.rider_id, scope NULL = all jobs) and 'rest_admin' (principal = the
--                 admin's phone as in restaurant_master.admins, scope = rest_ref; wired in phase R6 with the last-admin guard).
--               Readers: get_available_riders() (dispatch/job_create_dispatch.sql) skips paused riders; from R6
--                 t_order_card_destinations() and the restaurant notifier skip paused admins.
--               Writers: pause_start() / pause_end() through ordelo/pauses.py, called by the bots' /off and /on (R5, R6).
--               Messages: job_pause_sweep() (availability/job_pause_sweep.sql) closes expired rows and asks the app to send
--                 "your break ends soon" and "you're back on" (POST /pause-hooks/sweep, R5).
--               Durations: ordelo_config PAUSE_DURATIONS_<AUDIENCE> (comma-separated keys like 6h,1d,3d). Only listed keys are
--                 accepted, so nobody can pause indefinitely; the longest listed key is also the cap.
-- LIFECYCLE     open (ended_at NULL, now() < ends_at) --pause_start again--> same row, new ends_at, reminded_at cleared ('extended')
--               open --pause_end--> ended (end_reason 'resumed' | 'operator', announced_at = now(): the bot already replied)
--               open --ends_at passes--> not paused at once; job_pause_sweep() then sets ended_at = ends_at, end_reason 'expired'
--               ended 'expired' --sweep POST 2xx--> announced_at set ("you're back on" sent)
--               An expired-but-unswept row found by pause_start() is closed there ('expired', announced_at = now()) before the
--                 new pause starts, so the person gets one message, not two.
--               RESULT VOCABULARY (jsonb {result, ...})
--                 pause_start:   paused | extended | bad_duration | bad_audience | not_supported (rest_admin until R6)
--                 pause_end:     resumed | not_paused
--                 pause_current: paused | not_paused
--               Rows are kept (audit); no housekeeping deletes them.
-- CALLED BY     pauses:
--                 sql       is_paused(), pause_current(), pause_start(), pause_end(), job_pause_sweep()
--               pause_duration:
--                 sql       pause_start() (availability/pauses.sql)
--               is_paused:
--                 sql       get_available_riders() (dispatch/job_create_dispatch.sql)
--               pause_current:
--                 python    ordelo/pauses.py: current()
--               pause_start:
--                 python    ordelo/pauses.py: pause()
--               pause_end:
--                 python    ordelo/pauses.py: resume()
-- PYTHON MODEL  ordelo/pauses.py (Pause, PauseOutcome)
-- SECURITY      pauses: RLS ON, no policies, REVOKE ALL FROM anon/authenticated. Every function: REVOKE ALL FROM PUBLIC, anon,
--                 authenticated (service role and the owner only; get_available_riders() runs from pg_cron as the owner).
-- TESTS         tests/sql/test_pauses_sql.py
--               tests/ordelo/test_pauses.py
-- GOTCHAS       principal is a phone (digits only) for both audiences, so a pause follows the person across channels.
--               scope NULL and scope '' are the same (the unique index and every lookup use coalesce(scope, '')).
--               is_paused() is STABLE and cheap (unique index on open rows); it is safe inside get_available_riders().
--               rest_admin pauses are refused (not_supported) until phase R6 adds the last-admin guard (D52).
-- SEE ALSO      availability/job_pause_sweep.sql
--               core/rider_master.sql
--               dispatch/job_create_dispatch.sql
--               docs/adr/0013-pauses-have-a-mandatory-end-and-are-computed.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table pauses
--   One row per pause. A person has at most one OPEN row (ended_at IS NULL) per audience and scope.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pauses (
    pause_id bigint GENERATED BY DEFAULT AS IDENTITY NOT NULL,
    audience text NOT NULL, -- 'rider' | 'rest_admin'
    principal text NOT NULL, -- phone, digits only: rider_master.rider_id or a restaurant_master.admins entry
    scope text, -- NULL = everything for this audience; rest_ref for a restaurant admin
    starts_at timestamp with time zone NOT NULL DEFAULT now(),
    ends_at timestamp with time zone NOT NULL, -- mandatory: there is no open-ended pause
    ended_at timestamp with time zone, -- NULL = open (paused while now() < ends_at)
    end_reason text, -- expired | resumed | operator
    reminded_at timestamp with time zone, -- "ends soon" message sent (cleared when the end time moves)
    announced_at timestamp with time zone, -- "you're back on" sent, or not needed (resumed by the person)
    created_via text NOT NULL, -- telegram | whatsapp | operator
    created_by text, -- Telegram user id or operator name, for audit
    CONSTRAINT pauses_pkey PRIMARY KEY (pause_id),
    CONSTRAINT pauses_audience_check CHECK ((audience = ANY (ARRAY['rider'::text, 'rest_admin'::text]))),
    CONSTRAINT pauses_principal_digits CHECK ((principal ~ '^[0-9]{8,15}$'::text)),
    CONSTRAINT pauses_ends_after_start CHECK ((ends_at > starts_at)),
    CONSTRAINT pauses_end_reason_check CHECK (((end_reason IS NULL) OR (end_reason = ANY (ARRAY['expired'::text, 'resumed'::text, 'operator'::text])))),
    CONSTRAINT pauses_closed_has_reason CHECK (((ended_at IS NULL) = (end_reason IS NULL))),
    CONSTRAINT pauses_created_via_check CHECK ((created_via = ANY (ARRAY['telegram'::text, 'whatsapp'::text, 'operator'::text])))
);

-- At most one open pause per person, audience and scope (pause_start relies on it).
CREATE UNIQUE INDEX IF NOT EXISTS pauses_one_open_uidx ON public.pauses USING btree (audience, principal, (coalesce(scope, ''::text)))
WHERE (ended_at IS NULL);

-- The sweep scans open rows by end time.
CREATE INDEX IF NOT EXISTS pauses_open_ends_idx ON public.pauses USING btree (ends_at)
WHERE (ended_at IS NULL);

-- The sweep scans expired rows that still need their "you're back on" message.
CREATE INDEX IF NOT EXISTS pauses_unannounced_idx ON public.pauses USING btree (ended_at)
WHERE ((announced_at IS NULL) AND (end_reason = 'expired'::text));

ALTER TABLE public.pauses ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.pauses FROM anon, authenticated;

INSERT INTO public.ordelo_config (config_key, config_value, description)
    VALUES ('PAUSE_DURATIONS_RIDER', '6h,1d,3d', 'Pause lengths a rider can pick with /off (keys: <n>h or <n>d). The longest is the cap. Blank = /off disabled.'),
    ('PAUSE_DURATIONS_REST_ADMIN', '6h,1d,3d', 'Pause lengths a restaurant admin can pick with /off (phase R6).'),
    ('PAUSE_REMIND_BEFORE_MINS', '60', 'Minutes before a pause ends at which job_pause_sweep() asks the app to send the "ends soon" message.')
ON CONFLICT (config_key)
    DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- function pause_duration(p_audience text, p_duration text) -> interval
--   Map a duration key ('6h', '1d', '3d' ...) to an interval, but only if PAUSE_DURATIONS_<AUDIENCE> lists that key.
--   Returns NULL for an unknown audience, an unlisted key or a malformed key.
--   Data: reads ordelo_config.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.pause_duration (p_audience text, p_duration text)
    RETURNS interval
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        CASE WHEN m[2] = 'h' THEN
            make_interval(hours => m[1]::int)
        WHEN m[2] = 'd' THEN
            make_interval(days => m[1]::int)
        END
    FROM
        ordelo_config oc,
        LATERAL regexp_split_to_table(coalesce(oc.config_value, ''), ',') AS k (key),
        LATERAL regexp_match(lower(btrim(k.key)), '^([1-9][0-9]{0,2})([hd])$') AS m
    WHERE
        oc.config_key = 'PAUSE_DURATIONS_' || upper(p_audience)
        AND lower(btrim(k.key)) = lower(btrim(p_duration))
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.pause_duration (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function is_paused(p_audience text, p_principal text, p_scope text) -> boolean
--   true while an open pause covers now(). Expired rows count as NOT paused even before the sweep closes them.
--   Data: reads pauses.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.is_paused (p_audience text, p_principal text, p_scope text DEFAULT NULL)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        EXISTS (
            SELECT
                1
            FROM
                pauses p
            WHERE
                p.audience = p_audience
                AND p.principal = p_principal
                AND coalesce(p.scope, '') = coalesce(p_scope, '')
                AND p.ended_at IS NULL
                AND p.starts_at <= now()
                AND now() < p.ends_at);
$$;

REVOKE ALL ON FUNCTION public.is_paused (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function pause_current(p_audience text, p_principal text, p_scope text) -> jsonb
--   {result: 'paused', pause_id, starts_at, ends_at} for the pause covering now(), else {result: 'not_paused'}.
--   Data: reads pauses.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.pause_current (p_audience text, p_principal text, p_scope text DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce((
            SELECT
                jsonb_build_object('result', 'paused', 'pause_id', p.pause_id, 'starts_at', p.starts_at, 'ends_at', p.ends_at)
            FROM pauses p
            WHERE
                p.audience = p_audience
                AND p.principal = p_principal
                AND coalesce(p.scope, '') = coalesce(p_scope, '')
                AND p.ended_at IS NULL
                AND p.starts_at <= now()
                AND now() < p.ends_at), jsonb_build_object('result', 'not_paused'));
$$;

REVOKE ALL ON FUNCTION public.pause_current (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function pause_start(p_audience text, p_principal text, p_scope text, p_duration text, p_via text, p_by text) -> jsonb
--   Start a pause of the given duration key from now, or, if one is open, move its end to now() + duration ('extended':
--   a second /off replaces the end time, it never stacks). An open row whose end already passed is closed first
--   ('expired', announced_at = now()). Returns {result, pause_id, ends_at}.
--   Data: reads ordelo_config; reads/writes pauses; calls pause_duration().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.pause_start (p_audience text, p_principal text, p_scope text, p_duration text, p_via text, p_by text DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_len interval;
    v_id bigint;
    v_ends timestamptz;
BEGIN
    IF p_audience NOT IN ('rider', 'rest_admin') THEN
        RETURN jsonb_build_object('result', 'bad_audience');
    END IF;
    IF p_audience = 'rest_admin' THEN
        -- Phase R6 replaces this with the last-admin guard (D52): refuse when no other admin of p_scope stays unpaused.
        RETURN jsonb_build_object('result', 'not_supported');
    END IF;
    v_len := pause_duration (p_audience, p_duration);
    IF v_len IS NULL THEN
        RETURN jsonb_build_object('result', 'bad_duration');
    END IF;
    -- Close an expired-but-unswept open row so the unique index admits the new pause; no "back on" message for it.
    UPDATE
        pauses
    SET
        ended_at = ends_at,
        end_reason = 'expired',
        announced_at = now()
    WHERE
        audience = p_audience
        AND principal = p_principal
        AND coalesce(scope, '') = coalesce(p_scope, '')
        AND ended_at IS NULL
        AND ends_at <= now();
    v_ends := now() + v_len;
    UPDATE
        pauses
    SET
        ends_at = v_ends,
        reminded_at = NULL
    WHERE
        audience = p_audience
        AND principal = p_principal
        AND coalesce(scope, '') = coalesce(p_scope, '')
        AND ended_at IS NULL
    RETURNING
        pause_id INTO v_id;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'extended', 'pause_id', v_id, 'ends_at', v_ends);
    END IF;
    INSERT INTO pauses (audience, principal, scope, ends_at, created_via, created_by)
        VALUES (p_audience, p_principal, nullif(p_scope, ''), v_ends, p_via, p_by)
    RETURNING
        pause_id INTO v_id;
    RETURN jsonb_build_object('result', 'paused', 'pause_id', v_id, 'ends_at', v_ends);
EXCEPTION
    WHEN unique_violation THEN
        -- A concurrent /off created the open row between our UPDATE and INSERT: extend that one instead.
        UPDATE
            pauses
        SET
            ends_at = v_ends,
            reminded_at = NULL
        WHERE
            audience = p_audience
            AND principal = p_principal
            AND coalesce(scope, '') = coalesce(p_scope, '')
            AND ended_at IS NULL
        RETURNING
            pause_id INTO v_id;
        RETURN jsonb_build_object('result', 'extended', 'pause_id', v_id, 'ends_at', v_ends);
END;

$$;

REVOKE ALL ON FUNCTION public.pause_start (text, text, text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function pause_end(p_audience text, p_principal text, p_scope text, p_reason text) -> jsonb
--   End the pause covering now(): ended_at = now(), end_reason = p_reason ('resumed' default, or 'operator'),
--   announced_at = now() (the caller tells the person). Returns {result: 'resumed', pause_id} or {result: 'not_paused'}.
--   Data: reads/writes pauses.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.pause_end (p_audience text, p_principal text, p_scope text, p_reason text DEFAULT 'resumed')
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_id bigint;
BEGIN
    UPDATE
        pauses
    SET
        ended_at = now(),
        end_reason = CASE WHEN p_reason = 'operator' THEN
            'operator'
        ELSE
            'resumed'
        END,
        announced_at = now()
    WHERE
        audience = p_audience
        AND principal = p_principal
        AND coalesce(scope, '') = coalesce(p_scope, '')
        AND ended_at IS NULL
        AND now() < ends_at
    RETURNING
        pause_id INTO v_id;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'resumed', 'pause_id', v_id);
    END IF;
    RETURN jsonb_build_object('result', 'not_paused');
END;
$$;

REVOKE ALL ON FUNCTION public.pause_end (text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.pauses IS 'One row per pause: who (audience + principal [+ scope]), from, until (mandatory), and how it ended.';

COMMENT ON FUNCTION public.pause_duration (p_audience text, p_duration text) IS 'The interval for a duration key such as 6h or 1d if ordelo_config allows it for this audience, else NULL.';

COMMENT ON FUNCTION public.is_paused (p_audience text, p_principal text, p_scope text) IS 'true while an open pause covers now(); the one place that answers "is this person paused?".';

COMMENT ON FUNCTION public.pause_current (p_audience text, p_principal text, p_scope text) IS 'The pause covering now(), or {result: not_paused}; read-only.';

COMMENT ON FUNCTION public.pause_start (p_audience text, p_principal text, p_scope text, p_duration text, p_via text, p_by text) IS 'Start a pause, or move the end time of the current one (never stacks); the end time is mandatory.';

COMMENT ON FUNCTION public.pause_end (p_audience text, p_principal text, p_scope text, p_reason text) IS 'End the current pause early (resumed by the person, operator by Ordelo).';

-- =============================================================================================
-- OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- Who is paused right now:
-- SELECT audience, principal, scope, starts_at, ends_at FROM pauses WHERE ended_at IS NULL AND now() < ends_at ORDER BY ends_at;
--
-- Pause a rider for a day on their behalf:
-- SELECT pause_start('rider', '447...', NULL, '1d', 'operator', 'ops');
--
-- End a pause early on their behalf:
-- SELECT pause_end('rider', '447...', NULL, 'operator');
