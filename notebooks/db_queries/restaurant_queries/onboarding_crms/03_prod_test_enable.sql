-- CRMS web test window: deploy both repos first, then unpause.
-- Every test basket must contain the exact normal priced TEST3100 item.
-- An ordinary basket uses live payment even during this window.
DELETE FROM public.ordelo_config WHERE config_key='CRMS_WEB_ORDERING_PAUSED'
RETURNING config_key;

SELECT fo.order_number, fo.origin_channel, fo.payment_mode, fo.order_dtts,
       EXISTS (SELECT 1 FROM public.order_item oi
               WHERE oi.order_id=fo.order_id AND oi.product_name='TEST3100') AS has_test_item
FROM public.food_order fo WHERE fo.order_number LIKE 'CRMS-%'
ORDER BY fo.order_dtts DESC LIMIT 20;

-- Optional re-pause after the test window:
-- INSERT INTO public.ordelo_config (config_key,config_value,description)
-- VALUES ('CRMS_WEB_ORDERING_PAUSED','true','Emergency stop for new CRMS web orders')
-- ON CONFLICT (config_key) DO UPDATE SET config_value='true',updated_at=CURRENT_TIMESTAMP
-- RETURNING config_key,config_value;
