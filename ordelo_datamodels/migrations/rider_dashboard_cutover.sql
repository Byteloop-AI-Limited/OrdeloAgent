-- MIGRATION (history; do not edit the statements below)
-- Applied to live: not yet (prepared 2026-10-26; owner applies manually; no SQL has been run).
-- Current definitions now live in: admin_dashboard/auth_sessions.sql, admin_dashboard/get_rider_jobs.sql
--   agent_threads/rider_job_history_access.sql, core/rider_master.sql, core/rider_registrations.sql
--   core/ordelo_config.sql, core/restaurant_master.sql, dispatch/delivery_dispatch.sql
--   delivery/delivery_summary.sql, delivery/delivery_detail.sql, dispatch/delivery_inflight.sql
--   ordering/food_order_additions.sql, admin_dashboard/v_admin_orders.sql
--   admin_dashboard/get_rider_payout_report.sql
-- Purpose: Coordinated access-control and rider dashboard RPC cutover. Apply once during the maintenance window
--          before deploying/re-enabling dashboard traffic. This file is the prepared one-time SQL bundle;
--          the owner files above are the ongoing definitions after application.
-- Review and rollout steps: docs/rider-dashboard-rollout.md

-- Rider dashboard: manual coordinated maintenance cutover; not applied.
-- No transaction wrapper; the final statement revokes existing rider dashboard credentials once.


-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/auth_sessions.sql
-- Magic-link login sessions for every dashboard role (restaurant admin, rider, sys-admin).
-- =============================================================================================
-- LIVE CHECK    Table columns verified read-only 2026-10-26. Rider RPCs and restricted grants below are proposed, not applied.
-- OBJECTS       table  auth_sessions
--                   One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.
--               fn     rider_dashboard_mint(p_tuid bigint, p_token_hash text) -> jsonb
--                   Atomically authorize the linked Telegram rider and mint a 30-minute credential.
--               fn     rider_dashboard_activate(p_token_hash text, p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Consume one rider token after explicit browser POST.
--               fn     rider_dashboard_session(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Read a complete valid rider session and its verified current linkage.
--               fn     rider_dashboard_touch(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Validate and execute the idle heartbeat without extending the absolute expiry.
-- REQUIRES      core/rider_master.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   OrdeloAgent issues a WhatsApp magic link, or for restaurant admins also a Telegram /manage one
--                 (watomation/routers/rest_admin_auth_session.py, ordelo/rider_dashboard.py, sys_admin_auth_session.py): a row with token_hash and a 30-minute expires_at. Opening the link activates it: token_hash
--                 is cleared, cookie_hash set, hard_expires_at = activated_at + 4 h. restaurant-frontend's dashboards send the cookie on
--                 every request; last_seen_at is updated. Revoking a person's sessions = revoked_at on their rows.
-- LIFECYCLE     created (link sent) -> activated (cookie issued) -> expired (expires_at / hard_expires_at) or revoked.
-- CALLED BY     auth_sessions:
--                 python    watomation/routers/rest_admin_auth_session.py: mint_dashboard_session_for() (via mint_dashboard_session()
--                             for WhatsApp /login; directly from channels/telegram/rest_admin/manage.py for Telegram /manage)
--                 python    ordelo/rider_dashboard.py: issue_link()
--                 python    watomation/routers/sys_admin_auth_session.py: create_sys_admin_dashboard_session()
--               Rider RPCs: ordelo/rider_dashboard.py issue_link(); restaurant-frontend/lib/rider-session.ts.
-- PYTHON MODEL  ordelo/rider_dashboard.py DashboardLink
-- SECURITY      Table and rider RPCs are service-role only; RLS enabled. Apply reviewed cutover before code deployment.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
-- GOTCHAS       Only hashes are stored (sha256), never raw tokens.
--               Live grants were open on 2026-10-26; do not deploy without the reviewed access cutover.
-- SEE ALSO      test_support/test_magic_link.sql
--               _archive/dashboard_sessions.sql (the table this replaced; not live)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table auth_sessions
--   One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.auth_sessions (
    id uuid NOT NULL DEFAULT gen_random_uuid (),
    -- Role discriminator
    role text NOT NULL,
    -- Identity (set at creation, immutable)
    -- principal_id: rest_admin_id for rest_admin; rider_id (digits-only, no '+') for rider; sys_admin id for sys_admin
    -- scope_ref:    rest_ref for rest_admin; NULL for rider/sys_admin
    -- wa_number:    digits-only canonical form for all roles
    principal_id text NOT NULL,
    scope_ref text,
    wa_number text NOT NULL,
    -- Magic link token (sha256, never the raw token)
    -- NULL after activation so a leaked URL is useless even within TTL.
    token_hash text,
    -- Post-activation cookie token (sha256). NULL until activated.
    cookie_hash text,
    -- Lifecycle timestamps
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    expires_at timestamp with time zone NOT NULL, -- 30 min from created_at; link TTL
    activated_at timestamp with time zone, -- when cookie was first issued
    hard_expires_at timestamp with time zone, -- activated_at + 4h; absolute cap
    last_seen_at timestamp with time zone, -- updated on every authed request
    -- Binding (set at activation)
    bound_ip inet, -- recorded but NOT enforced (mobile NAT)
    bound_ua_hash text, -- sha256(User-Agent), ENFORCED
    -- Revocation
    revoked boolean NOT NULL DEFAULT FALSE,
    revoked_at timestamp with time zone,
    revoked_reason text,
    CONSTRAINT auth_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_sessions_role_check CHECK ((ROLE = ANY (ARRAY['rest_admin'::text, 'rider'::text, 'sys_admin'::text]))),
    CONSTRAINT auth_sessions_scope_required_for_rest_admin CHECK ((((ROLE = 'rest_admin'::text) AND (scope_ref IS NOT NULL)) OR (ROLE <> 'rest_admin'::text)))
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_cookie_hash_idx ON public.auth_sessions USING btree (cookie_hash)
WHERE (cookie_hash IS NOT NULL);

-- Composite index for efficient lookup by role + principal (e.g. revoke all sessions for a rider)
CREATE INDEX IF NOT EXISTS auth_sessions_role_principal_idx ON public.auth_sessions USING btree (ROLE, principal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS auth_sessions_scope_ref_idx ON public.auth_sessions USING btree (scope_ref, created_at DESC)
WHERE (scope_ref IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_token_hash_idx ON public.auth_sessions USING btree (token_hash)
WHERE (token_hash IS NOT NULL);

CREATE INDEX IF NOT EXISTS auth_sessions_wa_number_idx ON public.auth_sessions USING btree (wa_number, created_at DESC);

ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.auth_sessions FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.auth_sessions TO service_role;

-- rider_dashboard_mint: service-only actor authorization and session insert under the rider row lock.
-- Arguments are Telegram sender and SHA-256 token; returns result ok | not_linked.
-- Inactive/paused riders retain financial reads. Neither phone nor shift state authorizes issuance.
CREATE OR REPLACE FUNCTION public.rider_dashboard_mint (p_tuid bigint, p_token_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    r rider_master%ROWTYPE;
    n timestamptz;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'invalid token hash'
            USING ERRCODE = '22023';
        END IF;
        SELECT
            * INTO r
        FROM
            rider_master
        WHERE
            tuid = p_tuid
        FOR UPDATE;
        IF NOT FOUND OR r.phone_verified IS DISTINCT FROM TRUE OR r.t_linked_at IS NULL THEN
            RETURN jsonb_build_object('result', 'not_linked');
        END IF;
        n := clock_timestamp();
        INSERT INTO auth_sessions (role, principal_id, wa_number, token_hash, created_at, expires_at)
            VALUES ('rider', r.rider_id, r.rider_id, p_token_hash, n, n + interval '30 minutes');
        RETURN jsonb_build_object('result', 'ok');
END;
$$;

-- rider_dashboard_activate: lock rider before session; consume only an unexpired, unrevoked rider token.
-- Arguments are SHA-256 hashes. Returns result ok | invalid, with session_id on success.
-- Caller must use an explicit same-origin POST; raw tokens/cookies never enter the database.
CREATE OR REPLACE FUNCTION public.rider_dashboard_activate (p_token_hash text, p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    s auth_sessions%ROWTYPE;
    r rider_master%ROWTYPE;
    n timestamptz;
    sid uuid;
BEGIN
    IF p_token_hash IS NULL OR p_cookie_hash IS NULL OR p_ua_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' OR p_cookie_hash !~ '^[a-f0-9]{64}$' OR p_ua_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    SELECT
        * INTO s
    FROM
        auth_sessions
    WHERE
        token_hash = p_token_hash
        AND ROLE = 'rider';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    SELECT
        * INTO r
    FROM
        rider_master
    WHERE
        rider_id = s.principal_id
    FOR UPDATE;
    IF NOT FOUND OR r.tuid IS NULL OR r.phone_verified IS DISTINCT FROM TRUE OR r.t_linked_at IS NULL OR s.created_at < r.t_linked_at THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    n := clock_timestamp();
    UPDATE
        auth_sessions
    SET
        token_hash = NULL,
        cookie_hash = p_cookie_hash,
        activated_at = n,
        last_seen_at = n,
        hard_expires_at = n + interval '4 hours',
        bound_ua_hash = p_ua_hash
    WHERE
        id = s.id
        AND ROLE = 'rider'
        AND token_hash = p_token_hash
        AND NOT revoked
        AND activated_at IS NULL
        AND expires_at > n
    RETURNING
        id INTO sid;
    IF sid IS NULL THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'session_id', sid);
END;
$$;

-- rider_dashboard_session: pure authorization read, used by the jobs statement and heartbeat.
-- Arguments are cookie/UA hashes. Returns result ok | invalid, plus internal session/principal on success.
-- Requires complete activation, idle and hard expiry, verified link and generation; status is deliberately irrelevant.
CREATE OR REPLACE FUNCTION public.rider_dashboard_session (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT
        coalesce((
            SELECT
                jsonb_build_object('result', 'ok', 'session_id', s.id, 'rider_id', s.principal_id)
            FROM auth_sessions s
            JOIN rider_master r ON r.rider_id = s.principal_id
            WHERE
                s.cookie_hash = p_cookie_hash
                AND s.bound_ua_hash = p_ua_hash
                AND s.role = 'rider'
                AND NOT s.revoked
                AND s.activated_at IS NOT NULL
                AND s.token_hash IS NULL
                AND s.hard_expires_at > statement_timestamp()
            AND s.last_seen_at > statement_timestamp() - interval '60 minutes'
        AND r.tuid IS NOT NULL
        AND r.phone_verified
        AND r.t_linked_at IS NOT NULL
        AND s.created_at >= r.t_linked_at), jsonb_build_object('result', 'invalid'));
$$;

-- rider_dashboard_touch: execute (not fire-and-forget) the session idle heartbeat.
-- Returns result ok | invalid; never changes revoked/absolute expiry or resurrects a malformed session.
CREATE OR REPLACE FUNCTION public.rider_dashboard_touch (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    out jsonb;
BEGIN
    out := rider_dashboard_session (p_cookie_hash, p_ua_hash);
    IF out ->> 'result' <> 'ok' THEN
        RETURN out;
    END IF;
    UPDATE
        auth_sessions
    SET
        last_seen_at = clock_timestamp()
    WHERE
        id = (out ->> 'session_id')::uuid
        AND NOT revoked
        AND hard_expires_at > clock_timestamp()
        AND last_seen_at > clock_timestamp() - interval '60 minutes';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    RETURN out;
END;
$$;

REVOKE ALL ON FUNCTION public.rider_dashboard_mint (bigint, text), public.rider_dashboard_activate (text, text, text), public.rider_dashboard_session (text, text), public.rider_dashboard_touch (text, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_dashboard_mint (bigint, text), public.rider_dashboard_activate (text, text, text), public.rider_dashboard_session (text, text), public.rider_dashboard_touch (text, text) TO service_role;

COMMENT ON FUNCTION public.rider_dashboard_mint (bigint, text) IS 'Mint a rider login for the verified Telegram actor under the rider lock.';

COMMENT ON FUNCTION public.rider_dashboard_activate (text, text, text) IS 'Atomically consume one unexpired rider login token after explicit POST.';

COMMENT ON FUNCTION public.rider_dashboard_session (text, text) IS 'Authorize a complete rider session against its current verified link and expiry.';

COMMENT ON FUNCTION public.rider_dashboard_touch (text, text) IS 'Authorize and execute the rider session heartbeat without extending its hard expiry.';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.auth_sessions IS 'One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.';


-- =============================================================================================
-- ordelo_datamodels/agent_threads/rider_job_history_access.sql
-- Restrict direct access to external thread and checkpoint history containing rider job details.
-- =============================================================================================
-- LIVE CHECK    Anonymous reads verified open on all four tables read-only 2026-10-26; restrictions not applied.
-- OBJECTS       alter  thread
--                   Server-only access to the restaurant-agent-owned conversation index.
--               alter  checkpoints
--                   Server-only access to LangGraph checkpoint metadata.
--               alter  checkpoint_blobs
--                   Server-only access to serialized LangGraph state.
--               alter  checkpoint_writes
--                   Server-only access to pending LangGraph writes.
-- REQUIRES      restaurant-agents: thread; LangGraph checkpoint installation: checkpoints, checkpoint_blobs, checkpoint_writes
-- HOW TO RUN    Included by scripts/datamodels/rider_dashboard_cutover.py; owner applies during maintenance.
-- SIDE EFFECTS  Revokes direct public access; does not change library DDL, histories or graph behavior.
-- HOW IT FITS   Securing the jobs view must not leave the same private details readable through graph storage.
-- LIFECYCLE     No rows are created, removed or repaired. Existing server/DB-pool graph access continues.
-- CALLED BY     scripts/datamodels/rider_dashboard_cutover.py (manual SQL generation only)
-- PYTHON MODEL  none
-- SECURITY      RLS on; no PUBLIC/anon/authenticated grants; explicit server-role grants.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
-- GOTCHAS       These objects are owned externally. This file changes access only, never copies their definitions.
-- SEE ALSO      agent_threads/rider_threads.sql
-- =============================================================================================

-- The external index and library checkpoint tables can contain the same jobs/customer details as dispatches.
-- Restrict their direct access without redefining their schema or replacing LangGraph persistence.
ALTER TABLE public.thread ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoints ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoint_blobs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoint_writes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.thread, public.checkpoints, public.checkpoint_blobs, public.checkpoint_writes FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.thread, public.checkpoints, public.checkpoint_blobs, public.checkpoint_writes TO service_role;


-- From ordelo_datamodels/core/rider_master.sql
-- Private dashboard source: legitimate runtime callers use server credentials.
ALTER TABLE public.rider_master ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.rider_master FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.rider_master TO service_role;

-- Revoke rider dashboard access when a verified Telegram link moves or is removed.
-- The rider row is already locked; sessions are locked second, matching mint/activation order.
CREATE OR REPLACE FUNCTION public.rider_dashboard_revoke_link ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
BEGIN
    UPDATE
        auth_sessions
    SET
        revoked = TRUE,
        revoked_at = clock_timestamp(),
        revoked_reason = 'rider_link_changed'
    WHERE
        ROLE = 'rider'
        AND principal_id = OLD.rider_id
        AND NOT revoked;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_rider_dashboard_revoke_link ON public.rider_master;

CREATE TRIGGER trigger_rider_dashboard_revoke_link
    AFTER UPDATE OF tuid,
    phone_verified,
    t_linked_at ON public.rider_master
    FOR EACH ROW
    WHEN (OLD.tuid IS DISTINCT FROM NEW.tuid OR OLD.phone_verified IS DISTINCT FROM NEW.phone_verified OR OLD.t_linked_at IS DISTINCT FROM NEW.t_linked_at)
    EXECUTE FUNCTION public.rider_dashboard_revoke_link ();

REVOKE ALL ON FUNCTION public.rider_dashboard_revoke_link () FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_dashboard_revoke_link () TO service_role;

COMMENT ON FUNCTION public.rider_dashboard_revoke_link () IS 'Revoke pending and active rider dashboard sessions atomically on link change.';

COMMENT ON TRIGGER trigger_rider_dashboard_revoke_link ON public.rider_master IS 'Invalidate dashboard credentials when verified rider linkage changes.';


-- From ordelo_datamodels/core/rider_registrations.sql
-- Private dashboard source: legitimate runtime callers use server credentials.
ALTER TABLE public.rider_registrations ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.rider_registrations FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.rider_registrations TO service_role;


-- From ordelo_datamodels/core/ordelo_config.sql
-- Dashboard authorization/configuration authority: public clients cannot edit allowlists or login origins.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.ordelo_config FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.ordelo_config TO service_role;


-- From ordelo_datamodels/core/restaurant_master.sql
-- Dashboard authorization/configuration authority: public clients cannot edit allowlists or login origins.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.restaurant_master FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.restaurant_master TO service_role;


-- From ordelo_datamodels/dispatch/delivery_dispatch.sql
-- Private dashboard source: legitimate runtime callers use server credentials.
ALTER TABLE public.delivery_dispatch ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_dispatch FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_dispatch TO service_role;


-- From ordelo_datamodels/delivery/delivery_summary.sql
-- Private dashboard source: legitimate runtime callers use server credentials.
ALTER TABLE public.delivery_summary ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_summary FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_summary TO service_role;


-- From ordelo_datamodels/delivery/delivery_detail.sql
-- Private dashboard source: assignment details must not bypass the authenticated rider read.
ALTER TABLE public.delivery_detail ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_detail FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_detail TO service_role;


-- From ordelo_datamodels/dispatch/delivery_inflight.sql
-- Private dashboard source: assignment details must not bypass the authenticated rider read.
ALTER TABLE public.delivery_inflight ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_inflight FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_inflight TO service_role;


-- From ordelo_datamodels/ordering/food_order_additions.sql
-- Private order source: server runtimes retain access; public clients use authorized projections.
ALTER TABLE public.food_order ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.food_order FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.food_order TO service_role;


-- From ordelo_datamodels/admin_dashboard/v_admin_orders.sql
-- Owner-rights views must not bypass the restricted source tables.
REVOKE ALL ON public.v_admin_orders, public.v_admin_order_items, public.v_admin_orders_daily, public.v_admin_orders_monthly FROM PUBLIC, anon, authenticated;

GRANT SELECT ON public.v_admin_orders, public.v_admin_order_items, public.v_admin_orders_daily, public.v_admin_orders_monthly TO service_role;


-- From ordelo_datamodels/admin_dashboard/get_rider_payout_report.sql
-- Banking details are an authenticated operations read, never an anonymous RPC.
REVOKE ALL ON FUNCTION public.get_rider_payout_report (date, date, text[]) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.get_rider_payout_report (date, date, text[]) TO service_role;


-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/get_rider_jobs.sql
-- Session-authorized rider jobs, full-filter earnings and a masked profile.
-- =============================================================================================
-- LIVE CHECK    New functions, not applied. UTC database timezone and recent dispatch offsets checked read-only 2026-10-26.
-- OBJECTS       fn     get_rider_jobs(p_cookie_hash text, p_ua_hash text, p_tab text, p_from date, p_to date, p_paid text, p_cursor_time timestamptz, p_cursor_id integer, p_limit integer) -> jsonb
--                   One statement snapshot of rider jobs, aggregates and pagination; no customer details.
--               fn     get_rider_profile(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Read only the session rider's name/town/vehicle and masked bank account suffix.
-- REQUIRES      admin_dashboard/auth_sessions.sql
--               dispatch/delivery_dispatch.sql
--               delivery/delivery_summary.sql
--               core/rider_registrations.sql
--               restaurant-agents: food_order
-- HOW TO RUN    Owner applies after auth_sessions.sql; functions are idempotent. No live execution by agents.
-- SIDE EFFECTS  none; read-only functions, no delivery or payout transition.
-- HOW IT FITS   restaurant-frontend/lib/rider-jobs.ts calls the jobs RPC for SSR and GET /api/rider/jobs.
-- LIFECYCLE     Current assigned/pickedup amounts are expected; only completed dispatches count as earned.
-- CALLED BY     restaurant-frontend/lib/rider-jobs.ts; restaurant-frontend/app/rider/more/page.tsx
-- PYTHON MODEL  none
-- SECURITY      Service-role only; cookie and UA hashes authorize the principal, never a supplied rider ID.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
-- GOTCHAS       Dispatch timestamps are UTC without timezone; London day bounds are converted explicitly.
--               No test/channel-specific financial rule; report the stored completed dispatch payout.
-- SEE ALSO      admin_dashboard/get_rider_payout_report.sql
-- =============================================================================================

-- get_rider_jobs: typed inputs, one snapshot for rows/summary; cursor affects rows only.
-- Returns result ok | invalid | bad_input | bad_data and {tab,rows,summary,nextCursor,asOf} on success.
-- Reads auth_sessions/rider_master for authorization, dispatches for money, summary/order only for allowed enrichment.
CREATE OR REPLACE FUNCTION public.get_rider_jobs (p_cookie_hash text, p_ua_hash text, p_tab text, p_from date DEFAULT NULL, p_to date DEFAULT NULL, p_paid text DEFAULT 'all', p_cursor_time timestamptz DEFAULT NULL, p_cursor_id integer DEFAULT NULL, p_limit integer DEFAULT 25)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    SET timezone = 'UTC'
    AS $$
    WITH session AS MATERIALIZED (
        SELECT
            rider_dashboard_session (
                p_cookie_hash, p_ua_hash
) AS value
),
    valid AS (
        SELECT
            coalesce(p_tab IN ('current', 'completed')
                AND p_paid IN ('all', 'paid', 'unpaid')
                AND p_limit BETWEEN 1 AND 50
                AND ((p_cursor_time IS NULL
                    AND p_cursor_id IS NULL)
                OR (p_cursor_time IS NOT NULL
                    AND p_cursor_id > 0))
            AND CASE WHEN p_tab = 'current' THEN
                p_from IS NULL
                AND p_to IS NULL
                AND p_paid = 'all'
            ELSE
                p_from IS NOT NULL
                AND p_to IS NOT NULL
                AND p_to >= p_from
                AND p_to - p_from < 366
            END, FALSE) AS ok
),
filtered AS MATERIALIZED (
    SELECT
        d.*,
        CASE WHEN d.rider_payout::text NOT IN (
            'NaN', 'Infinity', '-Infinity'
) THEN
            round(
                d.rider_payout::numeric * 100
)::bigint
        END AS amount_minor
    FROM
        delivery_dispatch d,
        session s,
        valid v
    WHERE
        s.value ->> 'result' = 'ok'
        AND v.ok
        AND d.rider_id = s.value ->> 'rider_id'
        AND CASE WHEN p_tab = 'current' THEN
            d.status IN (
                'assigned', 'pickedup'
)
        ELSE
            d.status = 'completed'
            AND d.dtts >= ((
                    p_from::timestamp AT TIME ZONE 'Europe/London'
) AT TIME ZONE 'UTC'
)
            AND d.dtts < ((
                    (
                        p_to + 1
)::timestamp AT TIME ZONE 'Europe/London'
) AT TIME ZONE 'UTC'
)
            AND (
                p_paid = 'all'
                OR d.paid_status = p_paid
)
        END
),
page AS MATERIALIZED (
    SELECT
        *
    FROM
        filtered
    WHERE
        p_cursor_time IS NULL
        OR (
            dtts,
            dispatch_id
) < (
            p_cursor_time AT TIME ZONE 'UTC',
            p_cursor_id
)
    ORDER BY
        dtts DESC,
        dispatch_id DESC
    LIMIT p_limit + 1
),
shown AS MATERIALIZED (
    SELECT
        *
    FROM
        page
    ORDER BY
        dtts DESC,
        dispatch_id DESC
    LIMIT p_limit
),
projected AS (
    SELECT
        d.dtts,
        d.dispatch_id,
        jsonb_build_object('dispatch_id', d.dispatch_id, 'order_number', d.order_number, 'restaurant_name', s.rest_name, 'offered_at', d.dtts AT TIME ZONE 'UTC', 'order_placed_at', o.order_dtts, 'pickup_time', s.pickup_time, 'amount_minor', d.amount_minor, 'distance_km', d.distance, 'status', d.status, 'paid_status', CASE WHEN p_tab = 'completed' THEN
                d.paid_status
            END, 'marked_paid_at', CASE WHEN p_tab = 'completed'
                AND d.paid_status = 'paid' THEN
                d.paid_dtts AT TIME ZONE 'UTC'
            END) AS value
    FROM
        shown d
        LEFT JOIN delivery_summary s USING (order_number)
        LEFT JOIN LATERAL (
            SELECT
                min(order_dtts) AS order_dtts
            FROM
                food_order
            WHERE
                order_number = d.order_number) o ON TRUE
),
totals AS (
    SELECT
        CASE WHEN p_tab = 'current' THEN
            jsonb_build_object('count', count(*), 'expected_minor', coalesce(sum(amount_minor), 0))
        ELSE
            jsonb_build_object('count', count(*), 'earned_minor', coalesce(sum(amount_minor), 0), 'paid_minor', coalesce(sum(amount_minor) FILTER (WHERE paid_status = 'paid'), 0), 'unpaid_minor', coalesce(sum(amount_minor) FILTER (WHERE paid_status = 'unpaid'), 0))
        END AS value
    FROM
        filtered
)
SELECT
    CASE WHEN (
        SELECT
            value ->> 'result'
        FROM
            session) <> 'ok' THEN
        jsonb_build_object('result', 'invalid')
    WHEN NOT (
        SELECT
            ok
        FROM
            valid) THEN
        jsonb_build_object('result', 'bad_input')
    WHEN EXISTS (
        SELECT
            1
        FROM
            filtered
        WHERE
            rider_payout IS NULL
            OR rider_payout::text IN ('NaN', 'Infinity', '-Infinity')
            OR paid_status NOT IN ('paid', 'unpaid')
            OR paid_status IS NULL) THEN
        jsonb_build_object('result', 'bad_data')
    ELSE
        jsonb_build_object('result', 'ok', 'tab', p_tab, 'asOf', statement_timestamp(), 'rows', coalesce((
            SELECT
                jsonb_agg(value ORDER BY dtts DESC, dispatch_id DESC)
            FROM projected), '[]'::jsonb), 'summary', (
        SELECT
            value
        FROM totals), 'nextCursor', CASE WHEN (
        SELECT
            count(*)
    FROM page) > p_limit THEN
    (
        SELECT
            jsonb_build_object('time', dtts AT TIME ZONE 'UTC', 'id', dispatch_id)
    FROM shown ORDER BY dtts, dispatch_id LIMIT 1)
    ELSE
        NULL
    END)
    END;
$$;

-- get_rider_profile: authorize the cookie independently, then return only the rider's safe projection.
-- Returns result ok | invalid; bank_account_suffix is masked in SQL, never in the browser.
CREATE OR REPLACE FUNCTION public.get_rider_profile (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    WITH session AS (
        SELECT
            rider_dashboard_session (p_cookie_hash, p_ua_hash) AS value
)
    SELECT
        CASE WHEN value ->> 'result' <> 'ok' THEN
            jsonb_build_object('result', 'invalid')
        ELSE
            (
                SELECT
                    jsonb_build_object('result', 'ok', 'rider_name', r.rider_name, 'town', r.town, 'vehicle_type', r.vehicle_type, 'bank_account_suffix', CASE WHEN b.bank_account IS NOT NULL THEN
                            '•••• ' ||
                        RIGHT (b.bank_account, 4)
                        END)
                FROM
                    rider_master r
                LEFT JOIN LATERAL (
                    SELECT
                        bank_account
                    FROM
                        rider_registrations
                    WHERE
                        regexp_replace(phone, '[^0-9]', '', 'g') = r.rider_id
                    ORDER BY
                        updated_at DESC NULLS LAST
                    LIMIT 1) b ON TRUE
            WHERE
                r.rider_id = value ->> 'rider_id')
        END
    FROM
        session;
$$;

REVOKE ALL ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer), public.get_rider_profile (text, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer), public.get_rider_profile (text, text) TO service_role;

COMMENT ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer) IS 'Read only the authenticated rider jobs and full-filter earnings in one snapshot.';

COMMENT ON FUNCTION public.get_rider_profile (text, text) IS 'Read only the authenticated rider profile and server-masked account suffix.';


-- Deliberate clean cutover: old pending/active rider credentials are invalidated; no payout changes.
UPDATE public.auth_sessions
SET revoked = true, revoked_at = clock_timestamp(), revoked_reason = 'rider_dashboard_cutover'
WHERE role = 'rider' AND NOT revoked
RETURNING id, role, revoked;

