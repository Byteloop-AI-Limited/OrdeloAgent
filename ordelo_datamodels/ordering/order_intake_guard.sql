-- =============================================================================================
-- ordelo_datamodels/ordering/order_intake_guard.sql
-- The one new-order refusal rule: a date override closed the restaurant, or the basket has a hidden item.
-- =============================================================================================
-- LIVE CHECK    Live since 19 Nov 2026 (applied with migrations/order_intake_guard_p1.sql; live body compared with this file). docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md
--               (which also replaces create_food_order_with_items to call it).
-- OBJECTS       fn     order_intake_block(p_rest_ref text, p_at timestamptz, p_items jsonb) -> jsonb
--                   ok | closed_date | hidden_items (+ the hidden titles) for a new order; never raises.
-- REQUIRES      restaurant_admin/restaurant_service_hours.sql (restaurant_closed_by_override)
--               ordering/menu_item_visibility.sql (menu_item_hidden, menu_item_key)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE OR REPLACE.
-- SIDE EFFECTS  none
-- HOW IT FITS   create_food_order_with_items() (ordering/create_food_order_with_items.sql) calls this first for BOTH channels
--                 (WhatsApp: utils_common/order_management/order_service.py; web: utils_common/web_ordering/web_checkout.py)
--                 and RAISEs SQLSTATE P0C01 (closed_date) or P0C02 (hidden_items) with the JSON outcome as DETAIL. The callers
--                 map those to typed refusals. It only refuses on a POSITIVE decision: no override and no hidden row means
--                 exactly the old behaviour, and any error inside means "ok" (the guard can never stop orders by itself).
--                 Weekly opening hours are NOT checked here (they never were); only a date override that closes a time the
--                 weekly hours had open (restaurant_closed_by_override) and hidden items.
--               p_rest_ref: the order's restaurant (callers pass the order_number prefix, e.g. 'STRK' from 'STRK-...').
--               p_items: the create_food_order_with_items p_items array ([{product_name, ...}, ...]).
-- LIFECYCLE     RESULT VOCABULARY: ok | closed_date {reopens: null} | hidden_items {hidden: [titles]}
-- CALLED BY     order_intake_block:
--                 sql       create_food_order_with_items() (ordering/create_food_order_with_items.sql)
-- PYTHON MODEL  none (callers read the SQLSTATE: order_service.py, web_checkout.py)
-- SECURITY      REVOKE ALL FROM PUBLIC, anon, authenticated; granted to service_role.
-- TESTS         tests/sql/test_order_intake_guard_sql.py
-- GOTCHAS       Both callers run create_food_order_with_items() as the service role (order_service.py client_ordelo, a
--                 service-keyed client since the 26 Oct cutover) or as the database owner (web_checkout.py pool), so the
--                 guard is granted to service_role only. An anon caller of create_food_order_with_items (still executable by
--                 PUBLIC, docs/to-do.md) gets permission denied on the guard inside and its order fails: intended.
-- SEE ALSO      restaurant_admin/restaurant_service_hours.sql, ordering/menu_item_visibility.sql
-- =============================================================================================

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
