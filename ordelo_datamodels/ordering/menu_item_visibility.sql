-- =============================================================================================
-- ordelo_datamodels/ordering/menu_item_visibility.sql
-- Hidden menu items: a restaurant admin hides an item until an admin explicitly shows it again.
-- =============================================================================================
-- LIVE CHECK    New in plans/telegram-portal-links-and-dashboard-plan.md Phase 8; applied with migrations/menu_item_visibility_p1.sql.
-- OBJECTS       table  menu_item_hidden
--                   One row per hidden item of a restaurant; no row = visible.
--               fn     menu_item_key(p_title text) -> text
--                   The item key shared by menus and orders: the normalised title (lower case, single spaces, trimmed).
--               fn     menu_hidden_keys(p_rest_ref text) -> text[]
--                   The hidden item keys of a restaurant (storefront and menu readers filter with it).
--               fn     rest_admin_menu_list(p_session_id uuid, p_search text) -> jsonb
--                   The signed-in admin's menu (from <rest_ref>_menu) with a hidden flag per item.
--               fn     rest_admin_menu_set_hidden(p_session_id uuid, p_titles text[], p_hidden boolean) -> jsonb
--                   Hide or show items (audited, idempotent).
-- REQUIRES      core/menus.sql (<rest_ref>_menu tables), restaurant_admin/restaurant_settings.sql (restaurant_setting_change),
--               admin_dashboard/auth_sessions.sql (rest_admin_session_actor)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Creates the empty table menu_item_hidden.
-- HOW IT FITS   The <rest_ref>_menu tables are bulk-replaced on menu refresh, so visibility lives here, keyed by the item TITLE
--                 (owner check P-4: elas_menu has no sku column; every menu has title and every order line has product_name).
--                 Hiding never touches the menu row (its stock/availability stays as it is); showing again deletes the row
--                 here, so the item is back with whatever stock status the menu has. Only an explicit show clears it (O7').
--               Enforced by: order_intake_block() (ordering/order_intake_guard.sql) inside create_food_order_with_items()
--                 for both channels; the storefront menu route (restaurant-frontend app/api/menu/route.ts) filters with
--                 menu_hidden_keys(). WhatsApp menu tools that read MENU_API_URL are not covered until that service's owner
--                 filters too (plan P-5); the order guard is the backstop there.
--               Every change goes through restaurant_setting_change() ('menu_hidden', key = item key): audited, undoable.
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 rest_admin_menu_list:       ok | no_menu (no <rest_ref>_menu table) | not_authorised
--                 rest_admin_menu_set_hidden: ok (changed: n) | bad_items (empty, > 50, or a title not on the menu) |
--                                             no_menu | not_authorised
-- CALLED BY     rest_admin_menu_list, rest_admin_menu_set_hidden:
--                 frontend  restaurant-frontend/lib/rest-admin-rpc.ts (app/api/rest-admin/settings/menu/route.ts)
--               menu_hidden_keys:
--                 frontend  restaurant-frontend/lib/hiddenMenuItems.ts (app/api/menu/route.ts)
--               menu_item_key:
--                 sql       order_intake_block(), the functions above
-- PYTHON MODEL  none
-- SECURITY      Table: RLS on, no policies, REVOKE ALL FROM anon, authenticated. Functions: REVOKE ALL FROM PUBLIC, anon,
--               authenticated; granted to service_role.
-- TESTS         tests/sql/test_order_intake_guard_sql.py (hide / show / list / audit and the order refusal)
-- GOTCHAS       CHKS (Wings and Things) orders are numbered ELAS-...: the order guard checks the ELAS list for them, so a
--                 CHKS-only hidden item is enforced by the CHKS storefront menu, not by the guard.
--               The menu table name is built from the session's rest_ref only (format %I), never from the browser.
-- SEE ALSO      ordering/order_intake_guard.sql, core/menus.sql
-- =============================================================================================

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
