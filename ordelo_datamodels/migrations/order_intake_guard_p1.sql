-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-11-19 (agent, owner-authorised implementation run, during the owner's verification window)
-- Current definitions now live in: restaurant_admin/restaurant_service_hours.sql, ordering/menu_item_visibility.sql,
--   ordering/order_intake_guard.sql, ordering/create_food_order_with_items.sql
-- Purpose: docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md: one-date service-hour overrides (closed dates,
--   early close) with the dashboard editor (writes gated by ordelo_config REST_DASHBOARD_HOURS_EDITS, absent = off),
--   hidden menu items, and the new-order guard inside create_food_order_with_items (P0C01 closed_date, P0C02 hidden_items).
-- Compatibility: with no "dates" key and no hidden rows the guard returns ok and create_food_order_with_items behaves
--   exactly as before; any error inside the guard allows the order. New objects are additive.
-- VERIFY:  every live restaurant: SELECT order_intake_block(rest_ref, now(), '[]') -> ok; a rolled-back test order succeeds.
-- Then:    python scripts/datamodels/drift_check.py

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


CREATE TABLE IF NOT EXISTS public.menu_item_hidden (
    rest_ref text NOT NULL,
    item_key text NOT NULL,
    hidden_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT menu_item_hidden_pkey PRIMARY KEY (rest_ref, item_key)
);
ALTER TABLE public.menu_item_hidden ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.menu_item_hidden FROM anon, authenticated;
GRANT ALL ON TABLE public.menu_item_hidden TO service_role;

CREATE OR REPLACE FUNCTION public.menu_item_key (p_title text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT nullif(lower(btrim(regexp_replace(coalesce(p_title, ''), '\s+', ' ', 'g'))), '')
$$;

CREATE OR REPLACE FUNCTION public.menu_hidden_keys (p_rest_ref text)
    RETURNS text[]
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT coalesce(array_agg(item_key ORDER BY item_key), '{}'::text[]) FROM menu_item_hidden WHERE rest_ref = upper(p_rest_ref)
$$;

-- the menu table of a restaurant, or NULL (no table). Built from a rest_ref the caller has authorised.
CREATE OR REPLACE FUNCTION public.restaurant_menu_table (p_rest_ref text)
    RETURNS regclass
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT to_regclass(format('public.%I', lower(p_rest_ref) || '_menu'))
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_menu_list (p_session_id uuid, p_search text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_table regclass;
    v_items jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_table := restaurant_menu_table (a.rest_ref);
    IF v_table IS NULL THEN
        RETURN jsonb_build_object('result', 'no_menu', 'rest_ref', a.rest_ref);
    END IF;
    EXECUTE format($q$
        SELECT coalesce(jsonb_agg(jsonb_build_object('title', t.title, 'category', t.category, 'availability', t.availability,
                                                     'key', t.k, 'hidden', h.item_key IS NOT NULL)
                                  ORDER BY h.item_key IS NULL, t.category NULLS LAST, t.title), '[]'::jsonb)
        FROM (SELECT DISTINCT ON (menu_item_key (title)) title, category, availability::text AS availability,
                     menu_item_key (title) AS k
              FROM %s WHERE menu_item_key (title) IS NOT NULL
                AND ($1 IS NULL OR title ILIKE '%%' || $1 || '%%' OR category ILIKE '%%' || $1 || '%%')
              ORDER BY menu_item_key (title), title) t
        LEFT JOIN menu_item_hidden h ON h.rest_ref = $2 AND h.item_key = t.k
    $q$, v_table) INTO v_items USING nullif(btrim(p_search), ''), a.rest_ref;
    RETURN jsonb_build_object('result', 'ok', 'rest_ref', a.rest_ref, 'items', v_items,
                              'hidden_count', (SELECT count(*) FROM menu_item_hidden WHERE rest_ref = a.rest_ref));
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_menu_set_hidden (p_session_id uuid, p_titles text[], p_hidden boolean)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_table regclass;
    v_keys text[];
    v_known int;
    v_changed int := 0;
    k text;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_table := restaurant_menu_table (a.rest_ref);
    IF v_table IS NULL THEN
        RETURN jsonb_build_object('result', 'no_menu');
    END IF;
    v_keys := ARRAY (SELECT DISTINCT menu_item_key (t) FROM unnest(coalesce(p_titles, '{}')) t WHERE menu_item_key (t) IS NOT NULL);
    IF cardinality(v_keys) = 0 OR cardinality(v_keys) > 50 OR p_hidden IS NULL THEN
        RETURN jsonb_build_object('result', 'bad_items');
    END IF;
    -- hiding needs the item to be on the menu; showing also accepts a key that has left the menu (to clean it up)
    IF p_hidden THEN
        EXECUTE format('SELECT count(DISTINCT menu_item_key (title)) FROM %s WHERE menu_item_key (title) = ANY ($1)', v_table)
            INTO v_known USING v_keys;
        IF v_known <> cardinality(v_keys) THEN
            RETURN jsonb_build_object('result', 'bad_items');
        END IF;
    END IF;
    FOREACH k IN ARRAY v_keys LOOP
        IF restaurant_setting_change (a.rest_ref, 'menu_hidden', k, CASE WHEN p_hidden THEN to_jsonb(true) END,
                                      a.phone, 'dashboard', p_session_id) THEN
            v_changed := v_changed + 1;
        END IF;
    END LOOP;
    RETURN jsonb_build_object('result', 'ok', 'changed', v_changed, 'hidden', p_hidden);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

REVOKE ALL ON FUNCTION public.menu_item_key (text), public.menu_hidden_keys (text), public.restaurant_menu_table (text),
    public.rest_admin_menu_list (uuid, text), public.rest_admin_menu_set_hidden (uuid, text[], boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.menu_item_key (text), public.menu_hidden_keys (text), public.restaurant_menu_table (text),
    public.rest_admin_menu_list (uuid, text), public.rest_admin_menu_set_hidden (uuid, text[], boolean) TO service_role;


CREATE OR REPLACE FUNCTION public.order_intake_block (p_rest_ref text, p_at timestamptz, p_items jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_ref text := upper(nullif(btrim(p_rest_ref), ''));
    v_hidden jsonb;
BEGIN
    IF v_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'ok');
    END IF;
    IF restaurant_closed_by_override (v_ref, coalesce(p_at, now())) THEN
        RETURN jsonb_build_object('result', 'closed_date');
    END IF;
    IF jsonb_typeof(p_items) = 'array' THEN
        SELECT jsonb_agg(DISTINCT x ->> 'product_name') INTO v_hidden
        FROM jsonb_array_elements(p_items) x
        JOIN menu_item_hidden h ON h.rest_ref = v_ref AND h.item_key = menu_item_key (x ->> 'product_name');
        IF v_hidden IS NOT NULL THEN
            RETURN jsonb_build_object('result', 'hidden_items', 'hidden', v_hidden);
        END IF;
    END IF;
    RETURN jsonb_build_object('result', 'ok');
EXCEPTION
    WHEN OTHERS THEN
        RETURN jsonb_build_object('result', 'ok');
END;
$$;

REVOKE ALL ON FUNCTION public.order_intake_block (text, timestamptz, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.order_intake_block (text, timestamptz, jsonb) TO service_role;


CREATE OR REPLACE FUNCTION public.create_food_order_with_items (p_order jsonb, p_items jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_order jsonb;
    v_items integer;
    v_block jsonb;
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'create_food_order_with_items: p_items must be a non-empty array';
    END IF;
    -- New-order refusal (ordering/order_intake_guard.sql): a date override closed the restaurant, or a hidden item.
    -- The restaurant is the order number's prefix ('STRK-...' -> STRK). Any failure of the guard itself allows the order.
    BEGIN
        v_block := order_intake_block (upper(split_part(p_order ->> 'order_number', '-', 1)), now(), p_items);
    EXCEPTION
        WHEN OTHERS THEN
            v_block := NULL;
    END;
    IF v_block ->> 'result' = 'closed_date' THEN
        RAISE EXCEPTION 'order_refused: closed_date' USING ERRCODE = 'P0C01', DETAIL = v_block::text;
    ELSIF v_block ->> 'result' = 'hidden_items' THEN
        RAISE EXCEPTION 'order_refused: hidden_items' USING ERRCODE = 'P0C02', DETAIL = v_block::text;
    END IF;

    INSERT INTO public.food_order (order_id, order_number, seq_id, recipient, notes, thread_id, action, total_price, payment_status, origin_channel, storefront, payment_mode, idempotency_key)
        VALUES (p_order ->> 'order_id', p_order ->> 'order_number', (p_order ->> 'seq_id')::integer, p_order ->> 'recipient', p_order ->> 'notes', p_order ->> 'thread_id', p_order ->> 'action', (p_order ->> 'total_price')::double precision, COALESCE(p_order ->> 'payment_status', 'requires_payment'), COALESCE(p_order ->> 'origin_channel', 'whatsapp'), COALESCE(p_order ->> 'storefront', 'direct'), CASE WHEN EXISTS (
                SELECT
                    1
                FROM
                    jsonb_array_elements(p_items) x
                WHERE
                    x ->> 'product_name' = 'TEST3100') THEN
                'test'
            ELSE
                'live'
            END,
            NULLIF (p_order ->> 'idempotency_key', ''))
RETURNING
    to_jsonb (food_order.*) INTO v_order;

    INSERT INTO public.order_item (order_id, product_name, sku, quantity, price, modifications)
    SELECT
        p_order ->> 'order_id',
        x ->> 'product_name',
        x ->> 'sku',
        (x ->> 'quantity')::integer,
        (x ->> 'price')::double precision,
        CASE WHEN jsonb_typeof(x -> 'modifications') = 'array' THEN
            ARRAY (
                SELECT
                    jsonb_array_elements_text(x -> 'modifications'))
        ELSE
            NULL
        END
    FROM
        jsonb_array_elements(p_items) AS x;
    GET DIAGNOSTICS v_items = ROW_COUNT;

    RETURN jsonb_build_object('order', v_order, 'item_count', v_items);
END
$$;
