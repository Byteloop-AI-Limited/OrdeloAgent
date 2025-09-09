select * from ordelo_config;

update ordelo_config set config_value = 'https://agent.ordelo.app' where config_key = 'ORDELO_APP_URL';

update ordelo_config set config_value = 'https://rider-agent.ordelo.app' where config_key = 'ORDELO_APP_URL';

update ordelo_config set config_value = 'https://live-track.bytelooop.ai' where config_key = 'ELAB_APP_URL';

select * from delivery_detail order by dtts desc;
select * from delivery_summary order by dtts desc;


-- Change webhook in waba settings
-- restart the Ordelo server so restConfig is updated with new values
-- Run cloudflare tunnel