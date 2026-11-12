-- crdo_menu: Crispy Dosa Orpington menu table. Schema is the shared ordelo_datamodels/core/menus.sql
-- (re-read for drift 2026-11-12), adapted for CRDO. Not executed by the agent.
-- CREATE fails if the table already exists on purpose: inspect an existing table's columns first.
-- No primary key or identity, same as crms_menu and strk_menu; menu_seed.sql sets id explicitly.
-- Price audit joins lower(trim(title)) to order lines; the menu manager reads this table by name.
CREATE TABLE public.crdo_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP'::text,
    branch_link text DEFAULT 'https://deliveroo.co.uk/menu/London/orpington/crispy-dosa-orpington/'::text,
    image_link text,
    branch_name text DEFAULT 'Orpington'::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);

SELECT column_name, data_type, column_default FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'crdo_menu' ORDER BY ordinal_position;
