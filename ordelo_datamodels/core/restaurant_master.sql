-- =============================================================================================
-- ordelo_datamodels/core/restaurant_master.sql
-- One row per restaurant: identity, address, admin phones, opening hours and order-acceptance settings.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  restaurant_master
--                   Master record per restaurant; rest_ref (e.g. ELAS) is the key and the prefix of every order number.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   Every order table points back here through rest_ref (the 4-letter code, e.g. ELAS) or rest_id.
--                 init_delivery() / init_takeaway() copy name, address and coordinates into the order summary row, and
--                 resolve_initial_restaurant_acceptance() reads auto_accept to decide whether a new order skips the admin prompt.
--                 admins (text[] of phone numbers) is the authoritative admin list; each phone's Telegram link and channels live in
--                 restaurant_admin / admin_roster (restaurant_admin/admin_roster.sql).
--                 The per-restaurant behaviour switches live in ordelo_config as '<REST_REF>_<KEY>' rows, not in this table.
--                 restaurant-frontend reads it for the storefront and the admin dashboard; restaurant-agents reads it for menus,
--                 service hours and agent routing.
-- LIFECYCLE     Rows are created by the onboarding process (.claude/skills/ordelo-restaurant-onboarding) and edited by hand.
--               Nothing deletes them.
-- CALLED BY     restaurant_master:
--                 sql       enquire_admin_availability(), init_delivery(), init_takeaway(), insert_delivery_detail()
--                           job_rider_pickup_alerts(), job_terminate_stale_active_threads_new()
--                           resolve_initial_restaurant_acceptance(), restaurant_confirmation_whook()
--                           restaurant_updates_whook(), t_claim_invite(), t_invite_preview(), t_linked_restaurants()
--                           t_order_admin_phone(), t_order_card_destinations(), takeaway_pickup_time_whook()
--                           takeaway_restaurant_updates_whook()
--                 python    config/tgram_setting.py (module-level SQL)
--                 python    ordelo/wa_location.py: WaLocation._load_delivery_context()
--                 python    utils_common/order_management/order_service.py: _resolve_restaurant_coordinates()
--                 python    utils_common/order_management/restaurant_actions.py (module-level SQL)
--                 python    utils_common/web_ordering/availability.py: restaurant()
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/fapp_ordelo_agent.py: reset_restaurant_base_url_cache_endpoint()
--                 python    watomation/routers/delivery_hooks.py: RestaurantMasterData(), restaurant_confirmation_flow()
--                 python    watomation/routers/rest_admin_auth_session.py: mint_dashboard_session()
--                 python    watomation/routers/takeaway_hooks.py: RestaurantMasterData(), _post_pickup_time_event(), pickup_time_updated_hook()
--                 frontend  restaurant-frontend/app/api/sys-admin/restaurants/[rest_ref]/route.ts
--                 frontend  restaurant-frontend/app/api/sys-admin/restaurants/route.ts
--                 frontend  restaurant-frontend/lib/restaurantHours.ts
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/operational_lookup_cache.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/ordelo_service/datamodels/restaurant_master_pymodel.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/order_management/takeaway_pymodels.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/waba_callback.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/rider_event_hooks.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/web/app_factory.py
--                 r-agents  restaurant-agents/tests/services/test_operational_diagnostics.py
--                 r-agents  restaurant-agents/tests/services/test_operational_lookup_cache.py
--                 r-agents  restaurant-agents/tests/test_waba_callback.py
-- PYTHON MODEL  ordelo_datamodels/restaurant_master_pymodel.py RestaurantMaster
-- SECURITY      Public reads retained; proposed dashboard cutover removes public writes to the admin roster.
-- TESTS         tests/ordelo_datamodels/test_master_pymodels.py
--               tests/regressions/test_p7_takeaway.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_order_taps_sql.py
--               tests/sql/test_order_test_script_sql.py
--               tests/sql/test_restaurant_decision_sql.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/utils_common/order_management/test_order_service.py
--               tests/utils_common/web_ordering/test_web_contract.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/routers/test_takeaway_hooks.py
-- GOTCHAS       service_hours_json is the opening-hours source for restaurant-agents; restaurant_start_time / restaurant_end_time are
--                 older float hours (21.30 means 21:30), still set by the test/prod switch scripts in .claude/skills/database-operations.
--               Read with the anon key by restaurant-frontend and RLS is off: see docs/to-do.md (security review).
-- SEE ALSO      core/ordelo_config.sql (per-restaurant settings)
--               restaurant_admin/resolve_initial_restaurant_acceptance.sql (auto_accept)
--               docs/onboarding-web-only-restaurant.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table restaurant_master
--   Master record per restaurant; rest_ref (e.g. ELAS) is the key and the prefix of every order number.
--   admins: WhatsApp admin phone numbers (digits, no +). auto_accept: new orders are accepted without asking an admin.
--   delivery_/takeaway_order_cutoff_minutes: stop taking orders this many minutes before closing.
--   rest_stale_active_threads_minutes: idle minutes before job_terminate_stale_active_threads_new() closes an agent thread.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.restaurant_master (
    rest_ref character varying(4) NOT NULL,
    rest_id character varying(12),
    rest_name text NOT NULL,
    rest_email text,
    house_number text NOT NULL,
    building_name text,
    street_name text NOT NULL,
    city text NOT NULL,
    postcode text NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    admins text[],
    rest_stale_active_threads_minutes integer NOT NULL DEFAULT 10,
    restaurant_start_time double precision NOT NULL DEFAULT 12,
    restaurant_end_time double precision NOT NULL DEFAULT 21.30,
    service_hours_json jsonb NOT NULL DEFAULT '{}' ::jsonb,
    collection_commission double precision,
    auto_accept boolean NOT NULL DEFAULT FALSE,
    delivery_order_cutoff_minutes integer NOT NULL DEFAULT 0, -- added by migrations/add_order_cutoff_minutes.sql
    takeaway_order_cutoff_minutes integer NOT NULL DEFAULT 0, -- added by migrations/add_order_cutoff_minutes.sql
    CONSTRAINT restaurant_master_pkey PRIMARY KEY (rest_ref),
    CONSTRAINT restaurant_master_rest_id_key UNIQUE (rest_id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.restaurant_master IS 'Master record per restaurant; rest_ref (e.g. ELAS) is the key and the prefix of every order number.';

COMMENT ON COLUMN public.restaurant_master.admins IS 'Authoritative admin phone numbers (digits, no +); the Telegram link and channels per phone live in restaurant_admin';

COMMENT ON COLUMN public.restaurant_master.auto_accept IS 'true: new orders are accepted with the configured default pickup time, no admin prompt';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- LTER TABLE customer_master
--   DROP COLUMN IF EXISTS consented_rest_refs;

-- SELECT
--     column_name,
--     data_type,
--     is_nullable,
--     column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND table_name = 'customer_master'
-- ORDER BY ordinal_position;

-- Dashboard authorization/configuration authority: public clients cannot edit allowlists or login origins.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.restaurant_master FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.restaurant_master TO service_role;
