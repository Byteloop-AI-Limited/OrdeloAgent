CREATE OR REPLACE FUNCTION clear_dispatch()
RETURNS void AS $$
BEGIN
-- delete dispatch so I can get the msg
with latestRecord as (
select order_number from delivery_dispatch order by dtts desc limit 1
)
delete from delivery_dispatch dispatch where exists (select 1 from latestRecord where order_number=dispatch.order_number);
END;
$$ LANGUAGE plpgsql;