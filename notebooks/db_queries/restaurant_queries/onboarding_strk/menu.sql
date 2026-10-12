-- DRAFT: proposed STRK identity. Inspect existing schema first; CREATE fails if already present.
-- Official site verified via Chrome; branch_name set to confirmed Orpington venue.
CREATE TABLE public.strk_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP'::text,
    branch_link text DEFAULT 'https://strikersbar.com/'::text,
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
WHERE table_schema='public' AND table_name='strk_menu' ORDER BY ordinal_position;
