-- =============================================================================
-- ordelo_datamodels/ordering/web_order_lookup.sql
-- Find web orders by postcode and unlock by house.
-- =============================================================================
-- LIVE CHECK    Pending owner application; prepared 2026-11-17.
-- OBJECTS       fn web_house_key(text): normalise house number/name.
--               fn web_order_lookup(text,text,int,int): recent matching web orders.
--               fn web_order_unlock(text,text,text,bytea,int): check and issue recovered grant.
-- REQUIRES      ordering/web_order_request.sql; ordering/order_access_grant.sql; external food_order.
-- HOW TO RUN    Owner applies in SQL editor after dependencies; idempotent.
-- SIDE EFFECTS  Unlock inserts a hash-only order access grant.
-- HOW IT FITS   Postcode find opens status only; house proof opens recovered details.
-- LIFECYCLE     Find covers seven days; recovered grants expire 30 days after order.
-- CALLED BY     utils_common/web_ordering/order_lookup.py: find(), unlock().
-- PYTHON MODEL  none
-- SECURITY      Backend psycopg only; revoked from public browser roles.
-- TESTS         tests/sql/test_web_order_lookup_sql.py
-- GOTCHAS       Flat alone is not a house key; no handover code in recovered views.
-- SEE ALSO      docs/adr/0016-orders-are-found-by-postcode-and-unlocked-by-house.md

-- House number/name → comparison key. NULL when nothing usable remains.
CREATE OR REPLACE FUNCTION public.web_house_key (p text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        nullif (lower(regexp_replace(coalesce(p, ''), '[^A-Za-z0-9]', '', 'g')), '')
$$;

-- Find: the newest web orders of one restaurant for a canonical postcode within p_days. Status-free (the caller adds views).
CREATE OR REPLACE FUNCTION public.web_order_lookup (p_postcode text, p_rest_ref text, p_days int DEFAULT 7, p_limit int DEFAULT 10)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(jsonb_agg(x.row ORDER BY x.placed DESC), '[]'::jsonb)
    FROM (
        SELECT
            f.order_dtts AS placed,
            jsonb_build_object('order_number', f.order_number, 'placed_at', f.order_dtts, 'mode', CASE WHEN f.action = 'delivery' THEN
                    'delivery'
                ELSE
                    'collection'
                END, 'can_unlock', f.action = 'delivery'
                AND coalesce(public.web_house_key (r.address ->> 'house_number'), public.web_house_key (r.address ->> 'building')) IS NOT NULL) AS row
        FROM
            web_order_request r
            JOIN food_order f ON f.order_number = r.order_number
        WHERE
            r.lookup_postcode = p_postcode
            AND f.origin_channel = 'web'
            AND f.order_number LIKE upper(p_rest_ref) || '-%'
            AND f.order_dtts > now() - make_interval(days => p_days)
        ORDER BY
            f.order_dtts DESC
        LIMIT least (p_limit, 10)) x
$$;

-- Unlock: check postcode + house key for one delivery order and insert a 'recovered' grant in the same statement.
-- result: ok | no_match. One result for every kind of mismatch, so nothing leaks.
CREATE OR REPLACE FUNCTION public.web_order_unlock (p_order_number text, p_postcode text, p_house text, p_secret_hash bytea, p_days int DEFAULT 7)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_key text := public.web_house_key (p_house);
    v record;
BEGIN
    SELECT
        f.order_number,
        f.order_dtts,
        public.web_house_key (r.address ->> 'house_number') AS k1,
        public.web_house_key (r.address ->> 'building') AS k2 INTO v
    FROM
        web_order_request r
        JOIN food_order f ON f.order_number = r.order_number
    WHERE
        r.order_number = p_order_number
        AND r.lookup_postcode = p_postcode
        AND f.origin_channel = 'web'
        AND f.action = 'delivery'
        AND f.order_dtts > now() - make_interval(days => p_days);
    IF NOT FOUND OR v_key IS NULL OR v_key NOT IN (coalesce(v.k1, ''), coalesce(v.k2, '')) THEN
        RETURN jsonb_build_object('result', 'no_match');
    END IF;
    INSERT INTO order_access_grant (order_number, kind, secret_hash, detail_level, expires_at)
        VALUES (v.order_number, 'page_token', p_secret_hash, 'recovered', v.order_dtts + interval '30 days');
    RETURN jsonb_build_object('result', 'ok', 'expires_at', v.order_dtts + interval '30 days');
END
$$;

REVOKE ALL ON FUNCTION public.web_house_key (text) FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION public.web_order_lookup (text, text, int, int) FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION public.web_order_unlock (text, text, text, bytea, int) FROM PUBLIC, anon, authenticated;

COMMENT ON FUNCTION public.web_house_key (text) IS 'House comparison key: alphanumeric lowercase; empty is NULL.';

COMMENT ON FUNCTION public.web_order_lookup (text, text, int, int) IS 'Newest matching web orders; seven days, ten rows by default.';

COMMENT ON FUNCTION public.web_order_unlock (text, text, text, bytea, int) IS 'Atomically prove delivery house and issue recovered grant; ok or no_match.';
