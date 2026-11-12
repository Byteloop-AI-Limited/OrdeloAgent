-- CRDO rollback. Pick the smallest level that solves the problem. Flag changes take effect within about 60 s
-- (flag cache), no deploy needed. Not executed by the agent.

-- Level 1: pause all new CRDO web orders (the normal "turn it off").
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('CRDO_WEB_ORDERING_PAUSED', 'true', 'Emergency stop for new CRDO web orders')
ON CONFLICT (config_key) DO UPDATE SET config_value = 'true', updated_at = CURRENT_TIMESTAMP
RETURNING config_key, config_value;

SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRDO_WEB_ORDERING_PAUSED';

-- Level 2: take CRDO off the web. Remove RESTAURANTS["CRDO"] (backend) and set the frontend restaurants.ts
-- entry's webOrderingEnabled to false, and deploy. Keep Level 1 meanwhile. If CRDO is removed from the backend
-- registry, orders and the order page for existing CRDO orders return unknown_restaurant.

-- Level 3: full removal. NOT PREPARED FOR EXECUTION: deleting needs the owner's explicit approval of the exact
-- statements. Only if CRDO never took an order. Check first (expect 0 for all four, or do NOT delete):
-- SELECT
--   (SELECT count(*) FROM public.food_order WHERE order_number LIKE 'CRDO-%')   AS orders,
--   (SELECT count(*) FROM public.cust_rest_map WHERE rest_ref = 'CRDO')        AS cust_maps,
--   (SELECT count(*) FROM public.web_session_meta WHERE rest_ref = 'CRDO')     AS web_sessions,
--   (SELECT count(*) FROM public.t_invites WHERE rest_ref = 'CRDO')            AS invites;
-- Then (each with approval): DELETE the CRDO_ keys from ordelo_config, DROP TABLE public.crdo_menu,
-- DELETE the restaurant_master row for CRDO.
