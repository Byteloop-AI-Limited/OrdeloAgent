-- Service URL / emergency pause inspection. Payment testing is item-based.
-- Include TEST3100 in a test basket; normal new baskets always use live payment.
-- All statements below are read-only unless one commented example is enabled.
SELECT config_key, config_value, updated_at FROM public.ordelo_config
WHERE config_key IN ('ORDELO_APP_URL','RESTAURANT_MENU_APP_URL')
   OR config_key LIKE '%\_WEB\_ORDERING\_PAUSED' ESCAPE '\'
   OR config_key LIKE '%\_WEB\_MAX\_DISCOUNT\_PERCENT' ESCAPE '\'
ORDER BY config_key;

-- Emergency pause for new ELAS web orders (tracking continues):
-- INSERT INTO public.ordelo_config (config_key,config_value,description)
-- VALUES ('ELAS_WEB_ORDERING_PAUSED','true','Emergency stop for new web orders')
-- ON CONFLICT (config_key) DO UPDATE SET config_value='true',updated_at=CURRENT_TIMESTAMP
-- RETURNING config_key,config_value;

-- Reopen:
-- DELETE FROM public.ordelo_config WHERE config_key='ELAS_WEB_ORDERING_PAUSED'
-- RETURNING config_key;
