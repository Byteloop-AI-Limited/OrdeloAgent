-- Proposed identity STRK / strk: confirm venue and run read-only checks first.
SELECT rest_ref,rest_id,rest_name,city,postcode,auto_accept,service_hours_json,
       collection_commission,delivery_order_cutoff_minutes,takeaway_order_cutoff_minutes
FROM public.restaurant_master
WHERE rest_ref='STRK' OR rest_name ILIKE '%striker%';

SELECT column_name,data_type,is_nullable,column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name IN ('restaurant_master','ordelo_config')
ORDER BY table_name,ordinal_position;

SELECT conrelid::regclass AS table_name,conname,pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN ('public.restaurant_master'::regclass,'public.ordelo_config'::regclass);

SELECT config_key,config_value FROM public.ordelo_config
WHERE left(config_key,5)='STRK_' ORDER BY config_key;

SELECT to_regclass('public.strk_menu') AS existing_menu;
SELECT column_name,data_type,is_nullable,column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='strk_menu' ORDER BY ordinal_position;

SELECT count(*) AS existing_orders FROM public.food_order WHERE order_number LIKE 'STRK-%';
SELECT count(*) AS existing_sessions FROM public.web_session_meta WHERE rest_ref='STRK';
-- Once a real rest_id is supplied, check its UNIQUE collision separately.
-- Run menu_verify.sql only if the menu table exists; do not query it here.
