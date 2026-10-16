-- =============================================================================================
-- ordelo_datamodels/core/menus.sql
-- Per-restaurant menu tables (<rest_ref>_menu), one row per menu item.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  crms_menu
--                   Creams Cafe (Orpington) menu.
--               table  elas_menu
--                   ELAS menu.
--               table  sfcs_menu
--                   SFCS menu.
--               table  bnat_menu
--                   BNAT menu.
--               table  strk_menu
--                   Strikers (STRK) menu.
--               table  chks_menu
--                   CHKS menu.
--               table  vavi_menu
--                   VAVI menu.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   Each restaurant's menu lives in its own table named <rest_ref lower case>_menu. The menu API (MENU_API_URL) and
--                 restaurant-agents' menu tools read them; restaurant-frontend reads crms_menu directly and builds table names from
--                 config/restaurants.ts. utils_common/web_ordering/monitoring.py audits web prices against them.
--                 Onboarding a restaurant creates its table (.claude/skills/ordelo-restaurant-onboarding).
-- LIFECYCLE     loaded and refreshed from the restaurant's menu source (e.g. the Deliveroo menu downloader); rows replaced in bulk.
-- CALLED BY     crms_menu:
--                 frontend  restaurant-frontend/app/test-crms-menu/page.tsx
--               elas_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               sfcs_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               bnat_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               strk_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               chks_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               vavi_menu:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      crms_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               elas_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               sfcs_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               bnat_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               strk_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               chks_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               vavi_menu: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       The column sets differ between restaurants (each was created from that restaurant's source); there is no shared shape.
--               id is NOT NULL but none of these tables has a primary key.
--               elas_menu_before_march is an old copy kept in _orphans/core.sql.
-- SEE ALSO      .claude/skills/ordelo-restaurant-onboarding/SKILL.md
--               _orphans/core.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table crms_menu
--   Creams Cafe (Orpington) menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.crms_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP' ::text,
    branch_link text DEFAULT 'https://www.creamscafe.com/our-stores/orpington/' ::text,
    image_link text,
    branch_name text DEFAULT 'Orpington' ::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);

-- ---------------------------------------------------------------------------------------------
-- table elas_menu
--   ELAS menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.elas_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone,
    title text,
    description text,
    availability text,
    price numeric,
    currency text,
    branch_link text,
    image_link text,
    branch_name text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text,
    CONSTRAINT elas_menu_pkey PRIMARY KEY (id)
);

COMMENT ON COLUMN public.elas_menu.dietary_requirements IS 'allergies';

-- ---------------------------------------------------------------------------------------------
-- table sfcs_menu
--   SFCS menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sfcs_menu (
    id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP' ::text,
    branch_link text DEFAULT 'https://sfc-salisbury.co.uk' ::text,
    image_link text,
    branch_name text DEFAULT 'Salisbury' ::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text,
    CONSTRAINT sfcs_menu_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- table bnat_menu
--   BNAT menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.bnat_menu (
    id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP' ::text,
    branch_link text DEFAULT 'https://sfc-salisbury.co.uk' ::text,
    image_link text,
    branch_name text DEFAULT 'Salisbury' ::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text,
    CONSTRAINT bnat_menu_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE public.bnat_menu IS 'This is a duplicate of sfcs_menu';

-- ---------------------------------------------------------------------------------------------
-- table strk_menu
--   Strikers (STRK) menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.strk_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP' ::text,
    branch_link text DEFAULT 'https://strikersbar.com/' ::text,
    image_link text,
    branch_name text DEFAULT 'Orpington' ::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);

-- ---------------------------------------------------------------------------------------------
-- table chks_menu
--   CHKS menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.chks_menu (
    id bigint GENERATED BY DEFAULT AS IDENTITY NOT NULL,
    created_at timestamp with time zone,
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text,
    branch_link text,
    image_link text,
    branch_name text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text,
    CONSTRAINT chks_menu_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- table vavi_menu
--   VAVI menu.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.vavi_menu (
    id bigint GENERATED BY DEFAULT AS IDENTITY NOT NULL,
    created_at timestamp with time zone,
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text,
    branch_link text,
    image_link text,
    branch_name text,
    category text,
    discounted_price text,
    sub_category text,
    addons text,
    sub_category_description text,
    dietary_requirements text,
    CONSTRAINT vavi_menu_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE public.vavi_menu IS 'This is a  menu of vasanth villas';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.crms_menu IS 'Creams Cafe (Orpington) menu.';

COMMENT ON TABLE public.elas_menu IS 'ELAS menu.';

COMMENT ON TABLE public.sfcs_menu IS 'SFCS menu.';

COMMENT ON TABLE public.strk_menu IS 'Strikers (STRK) menu.';

COMMENT ON TABLE public.chks_menu IS 'CHKS menu.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select * from public.crms_menu;
