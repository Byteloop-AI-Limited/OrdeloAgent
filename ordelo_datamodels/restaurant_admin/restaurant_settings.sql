-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/restaurant_settings.sql
-- Restaurant-dashboard settings: the audited write path, the acceptance policy (auto-accept + default pickup minutes),
-- the sys-admin change list and undo.
-- =============================================================================================
-- LIVE CHECK    Live since 19 Nov 2026 (applied with migrations/restaurant_settings_p1.sql; live body compared with this file). docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md
-- OBJECTS       table  restaurant_settings_audit
--                   One row per changed restaurant setting: who, when, via what, old -> new, and its undo.
--               fn     restaurant_setting_value(p_rest_ref text, p_setting text, p_key text) -> jsonb
--                   The current value of one audited setting (NULL = not set / inherited).
--               fn     restaurant_setting_write(p_rest_ref text, p_setting text, p_key text, p_value jsonb) -> void
--                   Store one audited setting value (internal; only restaurant_setting_change calls it).
--               fn     restaurant_setting_change(p_rest_ref text, p_setting text, p_key text, p_new jsonb, p_by text, p_via text, p_session uuid) -> boolean
--                   Write one setting and its audit row in the caller's transaction; false when nothing changed.
--               fn     restaurant_default_pickup_minutes(p_rest_ref text, p_kind text) -> TABLE(minutes integer, inherited boolean)
--                   The effective default pickup minutes (restaurant key, else global), as order creation resolves them.
--               fn     restaurant_acceptance_state(p_rest_ref text) -> jsonb
--                   Auto-accept, both default pickup times (own or inherited) and a version for stale-edit checks.
--               fn     restaurant_acceptance_apply(p_rest_ref text, p_auto_accept boolean, p_delivery_minutes integer, p_collection_minutes integer, p_version text, p_by text, p_via text, p_session uuid) -> jsonb
--                   Validate and apply the acceptance policy atomically, audited.
--               fn     rest_admin_acceptance_get(p_session_id uuid) -> jsonb
--                   Restaurant dashboard read of the acceptance policy, bound to the signed-in session.
--               fn     rest_admin_acceptance_set(p_session_id uuid, p_auto_accept boolean, p_delivery_minutes integer, p_collection_minutes integer, p_version text) -> jsonb
--                   Restaurant dashboard write of the acceptance policy, bound to the signed-in session.
--               fn     restaurant_settings_changes(p_rest_ref text, p_limit integer) -> jsonb
--                   Sys-admin: recent audited changes of one restaurant, newest first.
--               fn     restaurant_setting_revert(p_audit_id bigint, p_by text) -> jsonb
--                   Sys-admin undo of one change when the value is still what that change set.
-- REQUIRES      core/restaurant_master.sql
--               core/ordelo_config.sql
--               admin_dashboard/auth_sessions.sql (rest_admin_session_actor)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Creates the empty table restaurant_settings_audit.
-- HOW IT FITS   Any admin on a restaurant's admins[] list may change that restaurant's operating settings from the
--                 restaurant dashboard (owner decision O6). The browser never sends a rest_ref or phone: the frontend passes the
--                 session id its middleware stamped, rest_admin_session_actor() re-derives (phone, rest_ref) and re-checks
--                 membership. Every change goes through restaurant_setting_change(), which writes the value and its audit
--                 row in one transaction, so no change escapes the audit. Sys-admin lists changes and undoes one with
--                 restaurant_setting_revert(), which re-applies the old value only if nobody has changed it since.
--               Settings (setting / key):
--                 auto_accept / -                 restaurant_master.auto_accept
--                 delivery_pickup_minutes / -     ordelo_config <REST>_DEFAULT_DELIVERY_PICKUP_TIME (NULL = inherit global)
--                 collection_pickup_minutes / -   ordelo_config <REST>_DEFAULT_COLLECTION_PICKUP_TIME (NULL = inherit global)
--                 hours_date / YYYY-MM-DD         restaurant_master.service_hours_json -> 'dates' -> key (restaurant_service_hours.sql)
--                 hours_weekly / mon..sun         restaurant_master.service_hours_json -> key        (restaurant_service_hours.sql)
--                 menu_hidden / item_key          menu_item_hidden row present                       (ordering/menu_item_visibility.sql)
--               Order creation reads the policy at creation time (ADR 0001), so a change affects new orders only.
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 rest_admin_acceptance_get:  ok | not_authorised
--                 rest_admin_acceptance_set / restaurant_acceptance_apply:
--                                             ok | stale | bad_minutes | needs_defaults | not_found | not_authorised
--                 restaurant_setting_revert:  ok | not_found | already_reverted | changed_since | not_revertible
-- CALLED BY     rest_admin_acceptance_get, rest_admin_acceptance_set:
--                 frontend  restaurant-frontend/lib/rest-admin-rpc.ts (app/api/rest-admin/settings/acceptance/route.ts)
--               restaurant_acceptance_apply:
--                 sql       rest_admin_acceptance_set()
--                 frontend  restaurant-frontend/app/api/sys-admin/restaurants/[rest_ref]/acceptance/route.ts (via 'sys-admin')
--               restaurant_settings_changes, restaurant_setting_revert:
--                 frontend  restaurant-frontend/app/api/sys-admin/restaurants/[rest_ref]/changes/ (route.ts, [id]/revert)
--               restaurant_setting_change:
--                 sql       restaurant_acceptance_apply(), restaurant_setting_revert(), rest_admin_hours_*(), rest_admin_menu_*()
--                 python    utils_common/order_management/restaurant_decision.py: default_pickup_minutes()
--                           calls restaurant_default_pickup_minutes() for delivery and takeaway timeout hooks.
-- PYTHON MODEL  none (the restaurant-frontend server also calls these RPCs with the service-role key)
-- SECURITY      Table: RLS on, no policies, REVOKE ALL FROM anon, authenticated. Every function: REVOKE ALL FROM PUBLIC, anon,
--               authenticated; granted to service_role (helpers too: nested SECURITY INVOKER calls run as the caller).
-- TESTS         tests/sql/test_restaurant_settings_sql.py
-- GOTCHAS       restaurant_default_pickup_minutes() repeats the lookup inside resolve_initial_restaurant_acceptance() instead of
--                 that live order-creation function being changed; tests/sql/test_restaurant_settings_sql.py asserts they
--                 agree for every case. Change both together.
--               A setting row change locks restaurant_master FOR UPDATE: changes to one restaurant are serialised.
-- SEE ALSO      restaurant_admin/resolve_initial_restaurant_acceptance.sql, docs/adr/0001-configured-restaurant-auto-accept.md
--               docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table restaurant_settings_audit: one row per changed setting.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.restaurant_settings_audit (
    id bigserial PRIMARY KEY,
    rest_ref text NOT NULL,
    setting text NOT NULL,
    setting_key text,                      -- the date, weekday or item for keyed settings; NULL otherwise
    old_value jsonb,                       -- NULL = was not set / inherited
    new_value jsonb,
    by_who text NOT NULL,                  -- the admin phone, or 'sys-admin:<phone>', or 'operator'
    via text NOT NULL,                     -- dashboard | sys-admin | telegram | operator
    session_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    reverted_by bigint REFERENCES public.restaurant_settings_audit (id)
);
CREATE INDEX IF NOT EXISTS restaurant_settings_audit_rest_idx ON public.restaurant_settings_audit (rest_ref, created_at DESC);
ALTER TABLE public.restaurant_settings_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.restaurant_settings_audit FROM anon, authenticated;
GRANT ALL ON TABLE public.restaurant_settings_audit TO service_role;
GRANT USAGE ON SEQUENCE public.restaurant_settings_audit_id_seq TO service_role;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_setting_value(p_rest_ref, p_setting, p_key) -> jsonb
--   The current value of one audited setting; NULL when unset (inherited, no override, not hidden).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_setting_value (p_rest_ref text, p_setting text, p_key text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v jsonb;
    raw text;
BEGIN
    CASE p_setting
    WHEN 'auto_accept' THEN
        SELECT to_jsonb(rm.auto_accept) INTO v FROM restaurant_master rm WHERE rm.rest_ref = p_rest_ref;
    WHEN 'delivery_pickup_minutes', 'collection_pickup_minutes' THEN
        SELECT config_value INTO raw FROM ordelo_config
        WHERE config_key = upper(p_rest_ref) || CASE p_setting WHEN 'delivery_pickup_minutes' THEN '_DEFAULT_DELIVERY_PICKUP_TIME'
                                                                ELSE '_DEFAULT_COLLECTION_PICKUP_TIME' END;
        v := CASE WHEN btrim(coalesce(raw, '')) ~ '^[1-9][0-9]{0,3}$' THEN to_jsonb(btrim(raw)::integer) END;
    WHEN 'hours_date' THEN
        SELECT rm.service_hours_json -> 'dates' -> p_key INTO v FROM restaurant_master rm WHERE rm.rest_ref = p_rest_ref;
    WHEN 'hours_weekly' THEN
        SELECT rm.service_hours_json -> p_key INTO v FROM restaurant_master rm WHERE rm.rest_ref = p_rest_ref;
    WHEN 'menu_hidden' THEN
        EXECUTE 'SELECT CASE WHEN EXISTS (SELECT 1 FROM menu_item_hidden WHERE rest_ref = $1 AND item_key = $2)
                 THEN to_jsonb(true) END' INTO v USING p_rest_ref, p_key;
    ELSE
        RAISE EXCEPTION 'unknown restaurant setting %', p_setting USING ERRCODE = '22023';
    END CASE;
    RETURN CASE WHEN v = 'null'::jsonb THEN NULL ELSE v END;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_setting_write(p_rest_ref, p_setting, p_key, p_value) -> void   (internal)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_setting_write (p_rest_ref text, p_setting text, p_key text, p_value jsonb)
    RETURNS void
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_key text;
BEGIN
    CASE p_setting
    WHEN 'auto_accept' THEN
        UPDATE restaurant_master SET auto_accept = coalesce((p_value)::boolean, FALSE) WHERE rest_ref = p_rest_ref;
    WHEN 'delivery_pickup_minutes', 'collection_pickup_minutes' THEN
        v_key := upper(p_rest_ref) || CASE p_setting WHEN 'delivery_pickup_minutes' THEN '_DEFAULT_DELIVERY_PICKUP_TIME'
                                                     ELSE '_DEFAULT_COLLECTION_PICKUP_TIME' END;
        IF p_value IS NULL OR p_value = 'null'::jsonb THEN
            -- Inherit the global default: the restaurant key is cleared (kept as a row, empty, so it is never deleted).
            UPDATE ordelo_config SET config_value = '', updated_at = now() WHERE config_key = v_key;
        ELSE
            INSERT INTO ordelo_config (config_key, config_value, description)
                VALUES (v_key, (p_value)::text, 'Default pickup minutes for configured auto-accept (restaurant dashboard)')
            ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();
        END IF;
    WHEN 'hours_date' THEN
        UPDATE restaurant_master
        SET service_hours_json = CASE WHEN p_value IS NULL OR p_value = 'null'::jsonb
                THEN service_hours_json #- ARRAY['dates', p_key]
                ELSE jsonb_set(CASE WHEN jsonb_typeof(service_hours_json -> 'dates') = 'object' THEN service_hours_json
                                    ELSE jsonb_set(coalesce(service_hours_json, '{}'::jsonb), '{dates}', '{}'::jsonb) END,
                               ARRAY['dates', p_key], p_value) END
        WHERE rest_ref = p_rest_ref;
        -- an empty 'dates' object is removed so the JSON stays in its weekly-only shape for older readers
        UPDATE restaurant_master SET service_hours_json = service_hours_json - 'dates'
        WHERE rest_ref = p_rest_ref AND service_hours_json -> 'dates' = '{}'::jsonb;
    WHEN 'hours_weekly' THEN
        UPDATE restaurant_master
        SET service_hours_json = jsonb_set(coalesce(service_hours_json, '{}'::jsonb), ARRAY[p_key],
                                           coalesce(p_value, '[]'::jsonb))
        WHERE rest_ref = p_rest_ref;
    WHEN 'menu_hidden' THEN
        IF p_value IS NULL OR p_value = 'null'::jsonb OR p_value = 'false'::jsonb THEN
            EXECUTE 'DELETE FROM menu_item_hidden WHERE rest_ref = $1 AND item_key = $2' USING p_rest_ref, p_key;
        ELSE
            EXECUTE 'INSERT INTO menu_item_hidden (rest_ref, item_key) VALUES ($1, $2) ON CONFLICT DO NOTHING'
                USING p_rest_ref, p_key;
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown restaurant setting %', p_setting USING ERRCODE = '22023';
    END CASE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_setting_change(...) -> boolean
--   The ONE audited write: lock the restaurant, compare, write, audit. Returns false when the value is unchanged.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_setting_change (p_rest_ref text, p_setting text, p_key text, p_new jsonb,
    p_by text, p_via text, p_session uuid)
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_old jsonb;
    v_new jsonb := CASE WHEN p_new = 'null'::jsonb THEN NULL ELSE p_new END;
BEGIN
    PERFORM 1 FROM restaurant_master WHERE rest_ref = p_rest_ref FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown restaurant %', p_rest_ref USING ERRCODE = '22023';
    END IF;
    v_old := restaurant_setting_value (p_rest_ref, p_setting, p_key);
    IF v_old IS NOT DISTINCT FROM v_new THEN
        RETURN FALSE;
    END IF;
    PERFORM restaurant_setting_write (p_rest_ref, p_setting, p_key, v_new);
    INSERT INTO restaurant_settings_audit (rest_ref, setting, setting_key, old_value, new_value, by_who, via, session_id)
        VALUES (p_rest_ref, p_setting, p_key, v_old, v_new, p_by, p_via, p_session);
    RETURN TRUE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_default_pickup_minutes(p_rest_ref, p_kind) -> TABLE(minutes, inherited)
--   p_kind 'delivery' | 'takeaway'. The same lookup as resolve_initial_restaurant_acceptance(): a positive whole-minute
--   restaurant key, else the global DEFAULT_* key; minutes NULL when neither is valid (auto-accept would then RAISE).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_default_pickup_minutes (p_rest_ref text, p_kind text)
    RETURNS TABLE (minutes integer, inherited boolean)
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_suffix text := CASE p_kind WHEN 'delivery' THEN 'DELIVERY' WHEN 'takeaway' THEN 'COLLECTION' END;
    raw text;
BEGIN
    IF v_suffix IS NULL THEN
        RAISE EXCEPTION 'unsupported order kind %', p_kind USING ERRCODE = '22023';
    END IF;
    SELECT config_value INTO raw FROM ordelo_config WHERE config_key = upper(p_rest_ref) || '_DEFAULT_' || v_suffix || '_PICKUP_TIME' LIMIT 1;
    IF btrim(coalesce(raw, '')) ~ '^[1-9][0-9]*$' AND length(btrim(raw)) <= 9 THEN
        RETURN QUERY SELECT btrim(raw)::integer, FALSE;
        RETURN;
    END IF;
    SELECT config_value INTO raw FROM ordelo_config WHERE config_key = 'DEFAULT_' || v_suffix || '_PICKUP_TIME' LIMIT 1;
    IF btrim(coalesce(raw, '')) ~ '^[1-9][0-9]*$' AND length(btrim(raw)) <= 9 THEN
        RETURN QUERY SELECT btrim(raw)::integer, TRUE;
        RETURN;
    END IF;
    RETURN QUERY SELECT NULL::integer, TRUE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_acceptance_state(p_rest_ref) -> jsonb
--   {result: ok | not_found, auto_accept, delivery: {minutes, inherited, own}, collection: {...}, version}
--   own = the restaurant's own key (NULL when inherited); version = md5 of the three stored values.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_acceptance_state (p_rest_ref text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_auto jsonb := restaurant_setting_value (p_rest_ref, 'auto_accept', NULL);
    v_del jsonb := restaurant_setting_value (p_rest_ref, 'delivery_pickup_minutes', NULL);
    v_col jsonb := restaurant_setting_value (p_rest_ref, 'collection_pickup_minutes', NULL);
    d record;
    c record;
BEGIN
    IF v_auto IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    SELECT * INTO d FROM restaurant_default_pickup_minutes (p_rest_ref, 'delivery');
    SELECT * INTO c FROM restaurant_default_pickup_minutes (p_rest_ref, 'takeaway');
    RETURN jsonb_build_object(
        'result', 'ok', 'rest_ref', p_rest_ref, 'auto_accept', v_auto,
        'delivery', jsonb_build_object('minutes', d.minutes, 'inherited', d.inherited, 'own', v_del),
        'collection', jsonb_build_object('minutes', c.minutes, 'inherited', c.inherited, 'own', v_col),
        'version', md5(jsonb_build_array(v_auto, v_del, v_col)::text));
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_acceptance_apply(...) -> jsonb
--   Minutes: whole 1-180, or NULL to inherit the global default. p_version must equal the state's version (stale edit
--   guard). Enabling auto-accept needs both effective defaults (ADR 0001: order creation would RAISE otherwise).
--   Returns the new state on ok.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_acceptance_apply (p_rest_ref text, p_auto_accept boolean, p_delivery_minutes integer,
    p_collection_minutes integer, p_version text, p_by text, p_via text, p_session uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_state jsonb;
    v_del integer;
    v_col integer;
BEGIN
    PERFORM 1 FROM restaurant_master WHERE rest_ref = p_rest_ref FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_state := restaurant_acceptance_state (p_rest_ref);
    IF p_version IS DISTINCT FROM v_state ->> 'version' THEN
        RETURN jsonb_build_object('result', 'stale', 'state', v_state);
    END IF;
    IF p_auto_accept IS NULL OR (p_delivery_minutes IS NOT NULL AND p_delivery_minutes NOT BETWEEN 1 AND 180)
        OR (p_collection_minutes IS NOT NULL AND p_collection_minutes NOT BETWEEN 1 AND 180) THEN
        RETURN jsonb_build_object('result', 'bad_minutes');
    END IF;
    PERFORM restaurant_setting_change (p_rest_ref, 'delivery_pickup_minutes', NULL, to_jsonb(p_delivery_minutes), p_by, p_via, p_session);
    PERFORM restaurant_setting_change (p_rest_ref, 'collection_pickup_minutes', NULL, to_jsonb(p_collection_minutes), p_by, p_via, p_session);
    SELECT minutes INTO v_del FROM restaurant_default_pickup_minutes (p_rest_ref, 'delivery');
    SELECT minutes INTO v_col FROM restaurant_default_pickup_minutes (p_rest_ref, 'takeaway');
    IF p_auto_accept AND (v_del IS NULL OR v_col IS NULL) THEN
        RAISE EXCEPTION 'needs_defaults' USING ERRCODE = 'P0001';
    END IF;
    PERFORM restaurant_setting_change (p_rest_ref, 'auto_accept', NULL, to_jsonb(p_auto_accept), p_by, p_via, p_session);
    RETURN jsonb_build_object('result', 'ok', 'state', restaurant_acceptance_state (p_rest_ref));
EXCEPTION
    WHEN raise_exception THEN
        IF SQLERRM = 'needs_defaults' THEN
            RETURN jsonb_build_object('result', 'needs_defaults');  -- the block's writes are rolled back
        END IF;
        RAISE;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- rest_admin_acceptance_get / _set: the restaurant dashboard's session-bound wrappers.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rest_admin_acceptance_get (p_session_id uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    RETURN restaurant_acceptance_state (a.rest_ref);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_acceptance_set (p_session_id uuid, p_auto_accept boolean, p_delivery_minutes integer,
    p_collection_minutes integer, p_version text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    RETURN restaurant_acceptance_apply (a.rest_ref, p_auto_accept, p_delivery_minutes, p_collection_minutes, p_version,
                                        a.phone, 'dashboard', p_session_id);
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_settings_changes(p_rest_ref, p_limit) -> jsonb   (sys-admin)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_settings_changes (p_rest_ref text, p_limit integer)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC, x.id DESC), '[]'::jsonb)
    FROM (
        SELECT a.id, a.setting, a.setting_key, a.old_value, a.new_value, a.by_who, a.via, a.created_at,
               a.reverted_by, EXISTS (SELECT 1 FROM restaurant_settings_audit r WHERE r.reverted_by = a.id) AS is_undo
        FROM restaurant_settings_audit a
        WHERE a.rest_ref = upper(p_rest_ref)
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT least(greatest(coalesce(p_limit, 50), 1), 200)
    ) x
$$;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_setting_revert(p_audit_id, p_by) -> jsonb   (sys-admin)
--   Re-apply the change's old value only while the current value is still the change's new value. The undo is itself
--   audited (via 'sys-admin'), and the reverted row records it in reverted_by.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_setting_revert (p_audit_id bigint, p_by text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a restaurant_settings_audit%ROWTYPE;
    v_cur jsonb;
    v_undo bigint;
BEGIN
    SELECT * INTO a FROM restaurant_settings_audit WHERE id = p_audit_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    ELSIF a.reverted_by IS NOT NULL THEN
        RETURN jsonb_build_object('result', 'already_reverted');
    ELSIF a.setting NOT IN ('auto_accept', 'delivery_pickup_minutes', 'collection_pickup_minutes', 'hours_date',
                            'hours_weekly', 'menu_hidden') THEN
        RETURN jsonb_build_object('result', 'not_revertible');
    END IF;
    PERFORM 1 FROM restaurant_master WHERE rest_ref = a.rest_ref FOR UPDATE;
    v_cur := restaurant_setting_value (a.rest_ref, a.setting, a.setting_key);
    IF v_cur IS DISTINCT FROM a.new_value THEN
        RETURN jsonb_build_object('result', 'changed_since', 'current', v_cur);
    END IF;
    IF a.setting = 'auto_accept' AND (a.old_value)::boolean
        AND EXISTS (SELECT 1 FROM restaurant_default_pickup_minutes (a.rest_ref, 'delivery') WHERE minutes IS NULL
                    UNION ALL SELECT 1 FROM restaurant_default_pickup_minutes (a.rest_ref, 'takeaway') WHERE minutes IS NULL) THEN
        RETURN jsonb_build_object('result', 'changed_since', 'current', v_cur);
    END IF;
    PERFORM restaurant_setting_change (a.rest_ref, a.setting, a.setting_key, a.old_value, p_by, 'sys-admin', NULL);
    SELECT max(id) INTO v_undo FROM restaurant_settings_audit WHERE rest_ref = a.rest_ref AND setting = a.setting
        AND setting_key IS NOT DISTINCT FROM a.setting_key;
    UPDATE restaurant_settings_audit SET reverted_by = v_undo WHERE id = a.id;
    RETURN jsonb_build_object('result', 'ok', 'undo_id', v_undo);
END;
$$;

REVOKE ALL ON FUNCTION public.restaurant_setting_value (text, text, text), public.restaurant_setting_write (text, text, text, jsonb),
    public.restaurant_setting_change (text, text, text, jsonb, text, text, uuid),
    public.restaurant_default_pickup_minutes (text, text), public.restaurant_acceptance_state (text),
    public.restaurant_acceptance_apply (text, boolean, integer, integer, text, text, text, uuid),
    public.rest_admin_acceptance_get (uuid), public.rest_admin_acceptance_set (uuid, boolean, integer, integer, text),
    public.restaurant_settings_changes (text, integer), public.restaurant_setting_revert (bigint, text)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.restaurant_setting_value (text, text, text), public.restaurant_setting_write (text, text, text, jsonb),
    public.restaurant_setting_change (text, text, text, jsonb, text, text, uuid),
    public.restaurant_default_pickup_minutes (text, text), public.restaurant_acceptance_state (text),
    public.restaurant_acceptance_apply (text, boolean, integer, integer, text, text, text, uuid),
    public.rest_admin_acceptance_get (uuid), public.rest_admin_acceptance_set (uuid, boolean, integer, integer, text),
    public.restaurant_settings_changes (text, integer), public.restaurant_setting_revert (bigint, text)
    TO service_role;
