CREATE TABLE IF NOT EXISTS public.elas_menu_before_march (
    id bigint,
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
    dietary_requirements text
);
