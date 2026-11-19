-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/restaurant_service_hours.sql
-- Service hours with one-date overrides (closed all day, early close, special hours) and the restaurant-dashboard editor.
-- =============================================================================================
-- LIVE CHECK    New in plans/telegram-portal-links-and-dashboard-plan.md Phase 7 (owner decision O8', 19 Nov 2026);
--               applied with migrations/restaurant_service_hours_p1.sql. Dashboard writes stay OFF until the readers are
--               deployed: ordelo_config REST_DASHBOARD_HOURS_EDITS (see GOTCHAS).
-- OBJECTS       fn     service_hours_day(p_hours jsonb, p_date date, p_use_dates boolean) -> jsonb
--                   The interval list that applies on one London date: its override (marker = []) or the weekday's.
--               fn     service_hours_open(p_hours jsonb, p_at timestamptz, p_use_dates boolean) -> boolean
--                   Open at that moment, with the date-override and overnight-spill rule shared by every reader.
--               fn     restaurant_closed_by_override(p_rest_ref text, p_at timestamptz) -> boolean
--                   true only when a date override closes a time the weekly hours would have open (the order guard).
--               fn     service_hours_valid_day(p_intervals jsonb) -> boolean
--                   An interval list is well formed: [["HH:MM","HH:MM"], ...], start < 24:00, start < end <= 48:00, no overlap.
--               fn     hours_edits_enabled(p_rest_ref text) -> boolean
--                   The rollout gate for dashboard hours writes (ordelo_config REST_DASHBOARD_HOURS_EDITS).
--               fn     rest_admin_hours_get(p_session_id uuid) -> jsonb
--                   Weekly hours, upcoming date overrides and whether editing is enabled, for the signed-in admin's restaurant.
--               fn     rest_admin_hours_close_date(p_session_id uuid, p_date date, p_from text) -> jsonb
--                   Close all day (p_from NULL) or from a local time on one date.
--               fn     rest_admin_hours_set_date(p_session_id uuid, p_date date, p_intervals jsonb) -> jsonb
--                   Special hours for one date ([] = closed all day).
--               fn     rest_admin_hours_clear_date(p_session_id uuid, p_date date) -> jsonb
--                   Remove a date override: the weekly hours apply again.
--               fn     rest_admin_hours_set_weekly(p_session_id uuid, p_day text, p_intervals jsonb) -> jsonb
--                   Change one weekday's regular hours.
-- REQUIRES      core/restaurant_master.sql, core/ordelo_config.sql
--               admin_dashboard/auth_sessions.sql (rest_admin_session_actor)
--               restaurant_admin/restaurant_settings.sql (restaurant_setting_change: settings hours_date / hours_weekly)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE OR REPLACE.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (the gate row is created by the operator when enabling)
-- HOW IT FITS   Storage (restaurant_master.service_hours_json), owner-confirmed shape:
--                 {"mon": [["12:00","22:00"]], ..., "sun": [...], "dates": {"2026-12-25": [["00:00","00:01"]],
--                                                                         "2026-12-24": [["12:00","18:00"]]}}
--               A date in "dates" is a London calendar date. Its list REPLACES that weekday's hours for that date only.
--               [["00:00","00:01"]] (the owner's all-day marker) and [] both mean closed all day. Spill-over rule shared by
--               every reader: a date with an override is described ONLY by its own list (yesterday's past-midnight hours do not
--               spill into it); an override's own interval may run past 24:00 into the next day unless that day has an
--               override too. Readers: restaurant-frontend utils/openingHours.ts (resolveServiceHoursForWeek),
--               OrdeloAgent utils_common/web_ordering/availability.py (opening), restaurant-agents
--               services/service_hours/schedule.py (WeeklySchedule.from_dict), and restaurant_closed_by_override() here,
--               which create_food_order_with_items() calls through order_intake_block() (ordering/order_intake_guard.sql)
--               so a closed date also refuses an order from a stale screen. The guard only refuses what an override closed:
--               it never adds the weekly-hours check the database has never made.
--               Early close: keep the earlier intervals of that date, cut the one containing the time, drop later ones.
--               Every write goes through restaurant_setting_change() (audited, sys-admin undo).
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 rest_admin_hours_get:          ok | not_authorised
--                 rest_admin_hours_close_date / _set_date / _clear_date / _set_weekly:
--                     ok | disabled (gate off) | bad_date (past or > 90 days) | bad_time | bad_intervals | bad_day |
--                     unchanged | not_authorised
-- CALLED BY     rest_admin_hours_*:
--                 frontend  restaurant-frontend/lib/rest-admin-rpc.ts (app/api/rest-admin/settings/hours/route.ts)
--               restaurant_closed_by_override:
--                 sql       order_intake_block() (ordering/order_intake_guard.sql)
--               service_hours_day, service_hours_open, service_hours_valid_day, hours_edits_enabled:
--                 sql       the functions above
-- PYTHON MODEL  none
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated; granted to service_role.
-- TESTS         tests/sql/test_restaurant_service_hours_sql.py
-- GOTCHAS       Deployed readers that predate "dates": restaurant-agents parse_week() RAISES on any non-weekday key, so a
--                 date override on ELAS/CHKS, BNAT or SFCS breaks WhatsApp ordering until restaurant-agents with the new
--                 schedule.py is deployed. The gate REST_DASHBOARD_HOURS_EDITS ('all' or a comma list of rest_refs; absent =
--                 off) must list only restaurants whose every reader is upgraded. The old frontend ignores "dates" (no crash,
--                 but shows weekly hours), so deploy the frontend too before enabling.
--               The sys-admin restaurant editor (restaurant-frontend app/api/sys-admin/restaurants/[rest_ref]/route.ts)
--                 keeps the stored "dates" when it saves weekly hours.
-- SEE ALSO      ordering/order_intake_guard.sql, restaurant_admin/restaurant_settings.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- service_hours_day / service_hours_open: the shared reading rule.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.service_hours_day (p_hours jsonb, p_date date, p_use_dates boolean)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT CASE
        WHEN p_use_dates AND jsonb_typeof(p_hours -> 'dates' -> to_char(p_date, 'YYYY-MM-DD')) = 'array' THEN
            CASE WHEN p_hours -> 'dates' -> to_char(p_date, 'YYYY-MM-DD') = '[["00:00","00:01"]]'::jsonb THEN '[]'::jsonb
                 ELSE p_hours -> 'dates' -> to_char(p_date, 'YYYY-MM-DD') END
        ELSE coalesce(p_hours -> (ARRAY['mon','tue','wed','thu','fri','sat','sun'])[extract(isodow FROM p_date)::int], '[]'::jsonb)
    END
$$;

CREATE OR REPLACE FUNCTION public.service_hours_open (p_hours jsonb, p_at timestamptz, p_use_dates boolean)
    RETURNS boolean
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_local timestamp := p_at AT TIME ZONE 'Europe/London';
    v_day date := v_local::date;
    v_min int := extract(hour FROM v_local)::int * 60 + extract(minute FROM v_local)::int;
    iv jsonb;
    s int;
    e int;
BEGIN
    FOR iv IN SELECT jsonb_array_elements(service_hours_day (p_hours, v_day, p_use_dates)) LOOP
        s := split_part(iv ->> 0, ':', 1)::int * 60 + split_part(iv ->> 0, ':', 2)::int;
        e := split_part(iv ->> 1, ':', 1)::int * 60 + split_part(iv ->> 1, ':', 2)::int;
        IF s <= v_min AND v_min < e THEN
            RETURN TRUE;
        END IF;
    END LOOP;
    -- yesterday's past-midnight hours spill into today, unless today has its own override
    IF p_use_dates AND jsonb_typeof(p_hours -> 'dates' -> to_char(v_day, 'YYYY-MM-DD')) = 'array' THEN
        RETURN FALSE;
    END IF;
    FOR iv IN SELECT jsonb_array_elements(service_hours_day (p_hours, v_day - 1, p_use_dates)) LOOP
        e := split_part(iv ->> 1, ':', 1)::int * 60 + split_part(iv ->> 1, ':', 2)::int;
        IF e > 1440 AND v_min + 1440 < e THEN
            RETURN TRUE;
        END IF;
    END LOOP;
    RETURN FALSE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- restaurant_closed_by_override: the order guard's question. Never raises: malformed hours = no opinion (false).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_closed_by_override (p_rest_ref text, p_at timestamptz)
    RETURNS boolean
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_hours jsonb;
BEGIN
    SELECT service_hours_json INTO v_hours FROM restaurant_master WHERE rest_ref = upper(p_rest_ref);
    IF v_hours IS NULL OR jsonb_typeof(v_hours -> 'dates') IS DISTINCT FROM 'object' THEN
        RETURN FALSE;
    END IF;
    RETURN service_hours_open (v_hours, p_at, FALSE) AND NOT service_hours_open (v_hours, p_at, TRUE);
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- service_hours_valid_day: [["HH:MM","HH:MM"], ...], minutes 0-59, start < 24:00, start < end <= 48:00, sorted, no overlap.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.service_hours_valid_day (p_intervals jsonb)
    RETURNS boolean
    LANGUAGE plpgsql
    IMMUTABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    iv jsonb;
    s int;
    e int;
    prev_end int := -1;
BEGIN
    IF jsonb_typeof(p_intervals) IS DISTINCT FROM 'array' OR jsonb_array_length(p_intervals) > 6 THEN
        RETURN FALSE;
    END IF;
    FOR iv IN SELECT jsonb_array_elements(p_intervals) LOOP
        IF jsonb_typeof(iv) <> 'array' OR jsonb_array_length(iv) <> 2
            OR NOT (iv ->> 0 ~ '^[0-9]{2}:[0-5][0-9]$' AND iv ->> 1 ~ '^[0-9]{2}:[0-5][0-9]$') THEN
            RETURN FALSE;
        END IF;
        s := split_part(iv ->> 0, ':', 1)::int * 60 + split_part(iv ->> 0, ':', 2)::int;
        e := split_part(iv ->> 1, ':', 1)::int * 60 + split_part(iv ->> 1, ':', 2)::int;
        IF s >= 1440 OR e <= s OR e > 2880 OR s < prev_end THEN
            RETURN FALSE;
        END IF;
        prev_end := e;
    END LOOP;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.hours_edits_enabled (p_rest_ref text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT coalesce((
        SELECT btrim(config_value) = 'all'
            OR upper(p_rest_ref) = ANY (SELECT upper(btrim(x)) FROM unnest(string_to_array(config_value, ',')) x)
        FROM ordelo_config WHERE config_key = 'REST_DASHBOARD_HOURS_EDITS'), FALSE)
$$;

-- ---------------------------------------------------------------------------------------------
-- Dashboard RPCs (session-bound; writes audited through restaurant_setting_change).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rest_admin_hours_get (p_session_id uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_hours jsonb;
    v_today date := (now() AT TIME ZONE 'Europe/London')::date;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    SELECT coalesce(service_hours_json, '{}'::jsonb) INTO v_hours FROM restaurant_master WHERE rest_ref = a.rest_ref;
    RETURN jsonb_build_object(
        'result', 'ok', 'rest_ref', a.rest_ref, 'today', v_today, 'editable', hours_edits_enabled (a.rest_ref),
        'weekly', (SELECT coalesce(jsonb_object_agg(d, coalesce(v_hours -> d, '[]'::jsonb)), '{}'::jsonb)
                   FROM unnest(ARRAY['mon','tue','wed','thu','fri','sat','sun']) d),
        'dates', (SELECT coalesce(jsonb_object_agg(k, v ORDER BY k), '{}'::jsonb)
                  FROM jsonb_each(CASE WHEN jsonb_typeof(v_hours -> 'dates') = 'object' THEN v_hours -> 'dates' ELSE '{}' END) x (k, v)
                  WHERE k >= to_char(v_today, 'YYYY-MM-DD')));
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

-- shared checks for a date write: actor, gate, date window. Returns NULL when allowed, else the refusal.
CREATE OR REPLACE FUNCTION public.rest_admin_hours_check (p_rest_ref text, p_date date)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_today date := (now() AT TIME ZONE 'Europe/London')::date;
BEGIN
    IF NOT hours_edits_enabled (p_rest_ref) THEN
        RETURN jsonb_build_object('result', 'disabled');
    ELSIF p_date IS NULL OR p_date < v_today OR p_date > v_today + 90 THEN
        RETURN jsonb_build_object('result', 'bad_date');
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_hours_set_date (p_session_id uuid, p_date date, p_intervals jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_refusal jsonb;
    v_value jsonb := CASE WHEN p_intervals = '[]'::jsonb THEN '[["00:00","00:01"]]'::jsonb ELSE p_intervals END;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_refusal := rest_admin_hours_check (a.rest_ref, p_date);
    IF v_refusal IS NOT NULL THEN
        RETURN v_refusal;
    END IF;
    IF NOT service_hours_valid_day (v_value) THEN
        RETURN jsonb_build_object('result', 'bad_intervals');
    END IF;
    IF NOT restaurant_setting_change (a.rest_ref, 'hours_date', to_char(p_date, 'YYYY-MM-DD'), v_value, a.phone, 'dashboard', p_session_id) THEN
        RETURN jsonb_build_object('result', 'unchanged');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'date', p_date, 'intervals', v_value);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_hours_close_date (p_session_id uuid, p_date date, p_from text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_refusal jsonb;
    v_hours jsonb;
    v_cut int;
    iv jsonb;
    s int;
    e int;
    v_out jsonb := '[]'::jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_refusal := rest_admin_hours_check (a.rest_ref, p_date);
    IF v_refusal IS NOT NULL THEN
        RETURN v_refusal;
    END IF;
    IF p_from IS NOT NULL THEN
        IF p_from !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' THEN
            RETURN jsonb_build_object('result', 'bad_time');
        END IF;
        v_cut := split_part(p_from, ':', 1)::int * 60 + split_part(p_from, ':', 2)::int;
        SELECT coalesce(service_hours_json, '{}'::jsonb) INTO v_hours FROM restaurant_master WHERE rest_ref = a.rest_ref;
        FOR iv IN SELECT jsonb_array_elements(service_hours_day (v_hours, p_date, TRUE)) LOOP
            s := split_part(iv ->> 0, ':', 1)::int * 60 + split_part(iv ->> 0, ':', 2)::int;
            e := split_part(iv ->> 1, ':', 1)::int * 60 + split_part(iv ->> 1, ':', 2)::int;
            IF s < v_cut THEN  -- keep earlier intervals; cut the one containing the time; drop later ones
                v_out := v_out || jsonb_build_array(jsonb_build_array(iv ->> 0,
                    CASE WHEN e > v_cut THEN p_from ELSE iv ->> 1 END));
            END IF;
        END LOOP;
    END IF;
    RETURN rest_admin_hours_set_date (p_session_id, p_date, v_out);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_hours_clear_date (p_session_id uuid, p_date date)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_refusal jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_refusal := rest_admin_hours_check (a.rest_ref, p_date);
    IF v_refusal IS NOT NULL THEN
        RETURN v_refusal;
    END IF;
    IF NOT restaurant_setting_change (a.rest_ref, 'hours_date', to_char(p_date, 'YYYY-MM-DD'), NULL, a.phone, 'dashboard', p_session_id) THEN
        RETURN jsonb_build_object('result', 'unchanged');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'date', p_date);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_hours_set_weekly (p_session_id uuid, p_day text, p_intervals jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    IF NOT hours_edits_enabled (a.rest_ref) THEN
        RETURN jsonb_build_object('result', 'disabled');
    ELSIF p_day IS NULL OR p_day NOT IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun') THEN
        RETURN jsonb_build_object('result', 'bad_day');
    ELSIF NOT service_hours_valid_day (p_intervals) THEN
        RETURN jsonb_build_object('result', 'bad_intervals');
    END IF;
    IF NOT restaurant_setting_change (a.rest_ref, 'hours_weekly', p_day, p_intervals, a.phone, 'dashboard', p_session_id) THEN
        RETURN jsonb_build_object('result', 'unchanged');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'day', p_day, 'intervals', p_intervals);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

REVOKE ALL ON FUNCTION public.service_hours_day (jsonb, date, boolean), public.service_hours_open (jsonb, timestamptz, boolean),
    public.restaurant_closed_by_override (text, timestamptz), public.service_hours_valid_day (jsonb),
    public.hours_edits_enabled (text), public.rest_admin_hours_get (uuid), public.rest_admin_hours_check (text, date),
    public.rest_admin_hours_set_date (uuid, date, jsonb), public.rest_admin_hours_close_date (uuid, date, text),
    public.rest_admin_hours_clear_date (uuid, date), public.rest_admin_hours_set_weekly (uuid, text, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.service_hours_day (jsonb, date, boolean), public.service_hours_open (jsonb, timestamptz, boolean),
    public.restaurant_closed_by_override (text, timestamptz), public.service_hours_valid_day (jsonb),
    public.hours_edits_enabled (text), public.rest_admin_hours_get (uuid), public.rest_admin_hours_check (text, date),
    public.rest_admin_hours_set_date (uuid, date, jsonb), public.rest_admin_hours_close_date (uuid, date, text),
    public.rest_admin_hours_clear_date (uuid, date), public.rest_admin_hours_set_weekly (uuid, text, jsonb)
    TO service_role;
