-- =============================================================================================
-- ordelo_datamodels/core/ordelo_config.sql
-- Runtime configuration as key/value rows (URLs, timeouts, feature flags, per-restaurant overrides), plus its parser helper.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  ordelo_config
--                   Key/value runtime configuration. config_key is the primary key; per-restaurant keys are prefixed with the rest_ref.
--               fn     parse_alert_offsets(p_config_key text) -> integer[]
--                   Parse a config value like '-15, -5, x, 5' into a sorted distinct int[] ({-15,-5,5}).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only; the policy below is re-created)
-- HOW IT FITS   Almost every function and job reads its settings here instead of hard-coding them:
--                 ORDELO_APP_URL (base URL every trigger/job POSTs to), <REST>_APP_URL (restaurant-agents per restaurant),
--                 <REST>_DELIVERY_TIMEOUT_TIME, <REST>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME, DISPATCH_BATCH_SIZE_<VEHICLE>,
--                 CONFIRMATION_CODE_SALT, overwatch_list, alert interval keys, TGRAM_* keys and many more.
--                 A per-restaurant key '<REST_REF>_<KEY>' wins over the global '<KEY>' wherever the code checks both.
--                 Python reads it through config/params.py and config/feature_flags.py; restaurant-frontend's lib/config.ts reads it
--                 with a 60-second cache; restaurant-agents reads it through its operational lookup cache.
--                 parse_alert_offsets() turns a comma-separated interval value into an int[] for the alert jobs.
-- LIFECYCLE     Rows are added by feature SQL (idempotent INSERT ... ON CONFLICT DO NOTHING seeds) and edited by operators.
-- CALLED BY     ordelo_config:
--                 sql       delivery_dispatch_whook_statement(), delivery_inflight_whook()
--                           delivery_summary_timedout_whook(), enquire_admin_availability()
--                           enquire_shift_availability(), fake_delivery_dispatch_whook(), get_available_riders()
--                           init_delivery(), init_takeaway(), job_close_thread(), job_create_dispatch()
--                           job_null_or_outdated_location(), job_payment_init_reconciler()
--                           job_restaurant_confirmation_timeout(), job_rider_pickup_alerts(), job_t_order_alerts()
--                           job_t_receipt_refresh(), job_terminate_stale_active_threads()
--                           job_terminate_stale_active_threads_new(), notify_missed_dispatches(), ordelo_post()
--                           parse_alert_offsets(), process_delivery(), process_restaurant_confirmation()
--                           resolve_initial_restaurant_acceptance(), restaurant_confirmation_whook()
--                           restaurant_updates_whook(), rider_location_event_update(), t_housekeeping()
--                           t_invites_shareable, takeaway_pickup_time_whook(), takeaway_restaurant_updates_whook()
--                 python    config/feature_flags.py: _read_flag(), _read_str()
--                 python    config/params.py: get_dashboard_app_url_async(), get_overwatch_list(), get_restaurant_base_url_async()
--                 python    utils_common/order_management/test_order_dispatch.py: read_overwatch_riders()
--                 python    utils_common/web_ordering/monitoring.py: sweep()
--                 python    watomation/routers/delivery_hooks.py: _get_delivery_pickup_default_minutes()
--                 python    watomation/routers/sys_admin_auth_session.py: _ensure_sys_admin() (fresh authorization read)
--                 python    watomation/routers/takeaway_hooks.py: _get_pickup_default_minutes()
--                 frontend  restaurant-frontend/app/api/sys-admin/restaurants/[rest_ref]/config/route.ts
--                 frontend  restaurant-frontend/app/api/test-db-connection/route.ts
--                 frontend  restaurant-frontend/app/test-config/page.tsx
--                 frontend  restaurant-frontend/lib/config.ts
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/operational_diagnostics.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/operational_lookup_cache.py
--                 r-agents  restaurant-agents/tests/services/test_operational_diagnostics.py
--                 r-agents  restaurant-agents/tests/services/test_operational_lookup_cache.py
--               parse_alert_offsets:
--                 sql       job_rider_pickup_alerts() (dispatch/job_rider_pickup_alerts.sql)
--                 sql       job_t_order_alerts() (telegram/t_order_alerts.sql)
-- PYTHON MODEL  none
-- SECURITY      Public reads retained; proposed dashboard cutover removes public writes to URLs and authorization allowlists.
--               parse_alert_offsets(): executable by PUBLIC (default)
-- TESTS         tests/config/test_params.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/utils_common/order_management/test_test_order_dispatch.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/routers/test_takeaway_hooks.py
-- GOTCHAS       The policy lets anyone read every key (USING true, TO public). Do not store secrets here.
--               Switching test/prod URLs is done by editing rows here: see docs/local-testing-runbook.md.
-- SEE ALSO      docs/local-testing-runbook.md
--               dispatch/job_rider_pickup_alerts.sql, telegram/t_order_alerts.sql (parse_alert_offsets users)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table ordelo_config
--   Key/value runtime configuration. config_key is the primary key; per-restaurant keys are prefixed with the rest_ref.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ordelo_config (
    config_key character varying(100) NOT NULL,
    config_value text NOT NULL,
    description text,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ordelo_config_pkey PRIMARY KEY (config_key)
);

DROP POLICY IF EXISTS "Enable read access for all users" ON public.ordelo_config;

CREATE POLICY "Enable read access for all users" ON public.ordelo_config AS PERMISSIVE
    FOR SELECT TO public
        USING (TRUE);

-- ---------------------------------------------------------------------------------------------
-- function parse_alert_offsets(p_config_key text) -> integer[]
--   Parse a config value like '-15, -5, x, 5' into a sorted distinct int[] ({-15,-5,5}).
--   Absent key, blank value or nothing parseable -> NULL. Junk entries are skipped, not fatal: one stray character must not
--   silence every alert. Callers tell 'absent' from 'present but unparseable' and RAISE a NOTICE for the latter.
--   Data: reads ordelo_config.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION parse_alert_offsets (p_config_key text)
    RETURNS int[]
    LANGUAGE sql
    STABLE
    AS $$
    SELECT
        array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
    FROM
        ordelo_config c
    CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t (x)
WHERE
    c.config_key = p_config_key
    AND btrim(t.x) ~ '^-?\d+$';
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.ordelo_config IS 'Key/value runtime configuration. config_key is the primary key; per-restaurant keys are prefixed with the rest_ref.';

COMMENT ON FUNCTION public.parse_alert_offsets (p_config_key text) IS 'Parse a config value like ''-15, -5, x, 5'' into a sorted distinct int[] ({-15,-5,5}).';

-- -- Optional: trigger to auto-update "updated_at" on row modification
-- CREATE OR REPLACE FUNCTION trigger_update_timestamp()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     NEW.updated_at = CURRENT_TIMESTAMP;
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;

-- CREATE TRIGGER trg_app_config_updated
-- BEFORE UPDATE ON app_config
-- FOR EACH ROW
-- EXECUTE FUNCTION trigger_update_timestamp();

-- update restaurant_master
-- set admins = '{}'::text[]
-- where rest_ref='WREN';

-- Dashboard authorization/configuration authority: public clients cannot edit allowlists or login origins.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.ordelo_config FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.ordelo_config TO service_role;
