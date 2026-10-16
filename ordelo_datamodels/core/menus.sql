CREATE TABLE public.crms_menu (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    title text,
    sku text,
    description text,
    availability text,
    price numeric,
    currency text DEFAULT 'GBP'::text,
    branch_link text DEFAULT 'https://www.creamscafe.com/our-stores/orpington/'::text,
    image_link text,
    branch_name text DEFAULT 'Orpington'::text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);


select * from public.crms_menu;