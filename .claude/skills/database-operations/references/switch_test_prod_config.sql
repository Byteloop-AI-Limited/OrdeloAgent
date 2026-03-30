-- ============================================================
-- Config Switch: Verification Queries
-- ============================================================

-- ============================================================
-- Config Switch: Test Setup
-- ============================================================

update ordelo_config set config_value = 'https://rider-agent-test.ordelo.app' where config_key = 'ORDELO_APP_URL';
update ordelo_config set config_value = 'https://elas-agg-test.ordelo.app' where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://sfcs-agg-test.ordelo.app' where config_key = 'SFCS_APP_URL';
update ordelo_config set config_value = 'https://wren-agg-test.ordelo.app' where config_key = 'WREN_APP_URL';
update ordelo_config set config_value = 'https://restaurant-test.ordelo.app' where config_key = 'RESTAURANT_MENU_APP_URL'; 

-- ============================================================
-- Config Switch: Production Setup
-- ============================================================


update ordelo_config set config_value = 'https://rider-agent.ordelo.app' where config_key = 'ORDELO_APP_URL';
update ordelo_config set config_value = 'https://elas-agg.ordelo.app' where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://sfcs-agg.ordelo.app' where config_key = 'SFCS_APP_URL';
update ordelo_config set config_value = 'https://restaurant.ordelo.app' where config_key = 'RESTAURANT_MENU_APP_URL'; 


