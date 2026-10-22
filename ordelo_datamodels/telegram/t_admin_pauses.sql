-- =============================================================================================
-- ordelo_datamodels/telegram/t_admin_pauses.sql
-- Restaurant admins pause and resume their Telegram order alerts (/off, /on on the restaurant bot; phase R6).
-- =============================================================================================
-- LIVE CHECK    NOT yet live (phase R6 of plans/telegram-rider-bot-plan.md). migrations/rider_telegram_r5_r6.sql step 3 applies it.
-- OBJECTS       fn     t_admin_pause(p_bot_key text, p_tuid bigint, p_duration text) -> jsonb
--                   Pause this Telegram user's alerts for every restaurant they are a linked admin of, one pause per restaurant.
--               fn     t_admin_resume(p_bot_key text, p_tuid bigint) -> jsonb
--                   End this Telegram user's alert pauses now, for every restaurant they are a linked admin of.
--               fn     t_admin_pause_status(p_bot_key text, p_tuid bigint) -> jsonb
--                   Read-only: per linked restaurant, paused or not and until when, plus the durations /off may offer.
--               fn     t_admin_pause_chats(p_bot_key text, p_phone text, p_rest_ref text) -> jsonb
--                   Read-only: the Telegram chats of one admin for one restaurant (where "ends soon" / "back on" go).
-- REQUIRES      availability/pauses.sql
--               telegram/t_invites.sql
--               telegram/t_order_alerts.sql
--               restaurant_admin/restaurant_order_decision.sql
--               core/restaurant_master.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (functions only).
-- HOW IT FITS   ADR 0013, D51, D52. The actor is the Telegram USER (tuid = from_user.id), as for every restaurant-bot action (D14):
--                 the restaurants come from t_invites (claimed by this tuid) and the phone from t_order_admin_phone() (the invite
--                 phone must still be in restaurant_master.admins), so a revoked invite or a removed admin can neither pause
--                 nor resume. The pause itself is pauses.pause_start('rest_admin', phone, rest_ref, ...) per restaurant, which
--                 applies the durations policy and the last-admin guard; this file only finds the restaurants and the phone.
--                 Python: channels/telegram/admin_pauses.py (wrapper), channels/telegram/rest_admin/pauses.py (/off, /on taps),
--                 watomation/routers/pause_hooks.py (the sweep messages to an admin, through t_admin_pause_chats()).
--                 Effect: while paused, t_alert_destinations() (telegram/t_order_alerts.sql) leaves the admin out of NEW Telegram
--                 order cards, kitchen receipts and notices for that restaurant. WhatsApp alerts are unchanged.
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 t_admin_pause:  not_linked | ok + restaurants:[{rest_ref, rest_name, result, ends_at}] where result is
--                                 pause_start()'s: paused | extended | bad_duration | not_admin | not_allowed (last admin)
--                 t_admin_resume: not_linked | ok + restaurants:[{rest_ref, rest_name, result}] (resumed | not_paused)
--                 t_admin_pause_status: not_linked | ok + restaurants:[{rest_ref, rest_name, paused, ends_at}] + options:[keys]
--                 t_admin_pause_chats: [{tcid, rest_name}] ('[]' when the admin has no linked chat for that restaurant)
-- CALLED BY     t_admin_pause:
--                 python    channels/telegram/admin_pauses.py: pause()
--               t_admin_resume:
--                 python    channels/telegram/admin_pauses.py: resume()
--               t_admin_pause_status:
--                 python    channels/telegram/admin_pauses.py: status()
--               t_admin_pause_chats:
--                 python    channels/telegram/admin_pauses.py: chats()
-- PYTHON MODEL  channels/telegram/admin_pauses.py (AdminPauseOutcome, RestaurantPause)
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated (service role only; client_ordelo_service).
-- TESTS         tests/sql/test_admin_pauses_sql.py
--               tests/channels/telegram/test_rest_admin_pauses.py
-- GOTCHAS       One /off pauses every restaurant the person is an admin of; a restaurant where they are the last unpaused
--                 admin answers not_allowed and stays on, the others are paused.
--               Restaurants are visited in rest_ref order, so two admins of the same two restaurants take the per-restaurant
--                 advisory locks (pause_start) in the same order and cannot deadlock.
-- SEE ALSO      availability/pauses.sql
--               availability/job_pause_sweep.sql
--               telegram/t_order_alerts.sql
--               docs/adr/0013-pauses-have-a-mandatory-end-and-are-computed.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function t_admin_pause(p_bot_key text, p_tuid bigint, p_duration text) -> jsonb
--   Pause this Telegram user's alerts for every restaurant they are a linked admin of, one pause per restaurant.
--   Data: reads restaurant_master, t_invites; calls pause_start(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_pause (p_bot_key text, p_tuid bigint, p_duration text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    r record;
    v_res jsonb;
    v_out jsonb := '[]'::jsonb;
BEGIN
    FOR r IN
    SELECT
        x.rest_ref,
        rm.rest_name,
        x.phone
    FROM (
        SELECT DISTINCT
            i.rest_ref,
            public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) AS phone
        FROM
            public.t_invites i
        WHERE
            i.bot_key = p_bot_key
            AND i.telegram_user_id = p_tuid
            AND i.status = 'claimed') x
    JOIN public.restaurant_master rm ON rm.rest_ref = x.rest_ref
WHERE
    x.phone IS NOT NULL
ORDER BY
    x.rest_ref LOOP
        v_res := public.pause_start ('rest_admin', r.phone, r.rest_ref, p_duration, 'telegram', p_tuid::text);
        v_out := v_out || jsonb_build_array(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name, 'result', v_res ->> 'result', 'ends_at', v_res -> 'ends_at'));
    END LOOP;
    IF jsonb_array_length(v_out) = 0 THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'restaurants', v_out);
END
$$;

REVOKE ALL ON FUNCTION public.t_admin_pause (text, bigint, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_admin_resume(p_bot_key text, p_tuid bigint) -> jsonb
--   End this Telegram user's alert pauses now, for every restaurant they are a linked admin of.
--   Data: reads restaurant_master, t_invites; calls pause_end(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_resume (p_bot_key text, p_tuid bigint)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    r record;
    v_res jsonb;
    v_out jsonb := '[]'::jsonb;
BEGIN
    FOR r IN
    SELECT
        x.rest_ref,
        rm.rest_name,
        x.phone
    FROM (
        SELECT DISTINCT
            i.rest_ref,
            public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) AS phone
        FROM
            public.t_invites i
        WHERE
            i.bot_key = p_bot_key
            AND i.telegram_user_id = p_tuid
            AND i.status = 'claimed') x
    JOIN public.restaurant_master rm ON rm.rest_ref = x.rest_ref
WHERE
    x.phone IS NOT NULL
ORDER BY
    x.rest_ref LOOP
        v_res := public.pause_end ('rest_admin', r.phone, r.rest_ref, 'resumed');
        v_out := v_out || jsonb_build_array(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name, 'result', v_res ->> 'result'));
    END LOOP;
    IF jsonb_array_length(v_out) = 0 THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'restaurants', v_out);
END
$$;

REVOKE ALL ON FUNCTION public.t_admin_resume (text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_admin_pause_status(p_bot_key text, p_tuid bigint) -> jsonb
--   Read-only: per linked restaurant, paused or not and until when, plus the durations /off may offer.
--   Data: reads restaurant_master, t_invites; calls pause_current(), pause_options(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_pause_status (p_bot_key text, p_tuid bigint)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    WITH mine AS (
        SELECT
            x.rest_ref,
            rm.rest_name,
            public.pause_current ('rest_admin', x.phone, x.rest_ref) AS cur
        FROM (
            SELECT DISTINCT
                i.rest_ref,
                public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) AS phone
            FROM
                public.t_invites i
            WHERE
                i.bot_key = p_bot_key
                AND i.telegram_user_id = p_tuid
                AND i.status = 'claimed') x
        JOIN public.restaurant_master rm ON rm.rest_ref = x.rest_ref
    WHERE
        x.phone IS NOT NULL
)
SELECT
    CASE WHEN NOT EXISTS (
        SELECT
            1
        FROM
            mine) THEN
        jsonb_build_object('result', 'not_linked')
    ELSE
        jsonb_build_object('result', 'ok', 'options', public.pause_options ('rest_admin'), 'restaurants', (
                SELECT
                    jsonb_agg(jsonb_build_object('rest_ref', m.rest_ref, 'rest_name', m.rest_name, 'paused', (m.cur ->> 'result') = 'paused', 'ends_at', m.cur -> 'ends_at')
                    ORDER BY m.rest_ref)
                FROM mine m))
    END
$$;

REVOKE ALL ON FUNCTION public.t_admin_pause_status (text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_admin_pause_chats(p_bot_key text, p_phone text, p_rest_ref text) -> jsonb
--   Read-only: the Telegram chats of one admin for one restaurant (where "ends soon" / "back on" go).
--   Data: reads restaurant_master; calls t_order_card_destinations().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_pause_chats (p_bot_key text, p_phone text, p_rest_ref text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(jsonb_agg(jsonb_build_object('tcid', d.tcid, 'rest_name', rm.rest_name)
            ORDER BY d.tcid), '[]'::jsonb)
    FROM
        public.t_order_card_destinations (p_bot_key, p_rest_ref) d
        JOIN public.restaurant_master rm ON rm.rest_ref = p_rest_ref
    WHERE
        d.phone = regexp_replace(coalesce(p_phone, ''), '\D', '', 'g')
$$;

REVOKE ALL ON FUNCTION public.t_admin_pause_chats (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.t_admin_pause (p_bot_key text, p_tuid bigint, p_duration text) IS 'Pause this Telegram user''s alerts for every restaurant they are a linked admin of, one pause per restaurant.';

COMMENT ON FUNCTION public.t_admin_resume (p_bot_key text, p_tuid bigint) IS 'End this Telegram user''s alert pauses now, for every restaurant they are a linked admin of.';

COMMENT ON FUNCTION public.t_admin_pause_status (p_bot_key text, p_tuid bigint) IS 'Read-only: per linked restaurant, paused or not and until when, plus the durations /off may offer.';

COMMENT ON FUNCTION public.t_admin_pause_chats (p_bot_key text, p_phone text, p_rest_ref text) IS 'Read-only: the Telegram chats of one admin for one restaurant (where ends-soon / back-on messages go).';

-- =============================================================================================
-- OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- Which restaurant admins are paused right now:
-- SELECT principal AS admin_phone, scope AS rest_ref, ends_at FROM pauses
--  WHERE audience = 'rest_admin' AND ended_at IS NULL AND now() < ends_at ORDER BY scope, ends_at;
--
-- What a Telegram user would see for /off (replace the tuid):
-- SELECT t_admin_pause_status('rest_admin', 123456789);
