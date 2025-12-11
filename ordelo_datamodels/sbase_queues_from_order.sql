-- Deprecated - To Be Deleted
-- This query processes rider acceptance messages from the queue
-- and dispatches them to the appropriate dispatch function
WITH accepted_msgs AS (
  SELECT 
  *,
  message::JSONB ->> 'order_number' as order_number,
  message::JSONB ->> 'dispatch_id' as dispatch_id,
  message::JSONB ->> 'status' as status,
  message::JSONB ->> 'rider_id' as rider_id,
  RANK() OVER (PARTITION BY message::JSONB ->> 'order_number' ORDER BY enqueued_at ASC) as msg_rank
  FROM pgmq.read(
    queue_name => 'rider_accept_q', vt =>0, qty => 100
  )
--  where message::JSONB ->> 'order_number' in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a')
  where false
  order by enqueued_at desc
), firstMsg AS
(
	select * 
	from accepted_msgs 
	where msg_rank=1 
	and not exists (select 1 from delivery_inflight where rider_id=accepted_msgs.rider_id)
), processFirstAcceptMsg as (
select 
dispatch_accept_func(
	cast(dispatch_id as int), 
	order_number,
	rider_id
	) 
from firstMsg
), has_updates AS (
    SELECT EXISTS (SELECT 1 FROM processFirstAcceptMsg WHERE processFirstAcceptMsg IS NOT NULL) AS updated
)
select updated from has_updates;