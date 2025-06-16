select *
from ordelo_config;


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_ELECTRIC_BIKE';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_SCOOTER';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_CAR';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_BICYCLE';