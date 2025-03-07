/**
Assigning Delivery to Riders who have accepted the job.
This is dependent on `assign_accepted_dispatch` function
Invocation:
1. Scheduled cron job 'create_dispatch_for_unassigned_orders' (10s interval)

Purpose:
- Manage unassigned orders
- Create new dispatch entries based on available riders (function - get_available_riders())
- Update delivery_detail with timeout status

Execution:
- Frequency: Every 5 seconds

Side Effects:
1. Trigger webhook: /delivery-hooks/delivery-dispatch on insert
2. Send WhatsApp messages to riders with delivery summaries
**/

CREATE OR REPLACE FUNCTION job_assign_delivery()
RETURNS void AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' LIMIT 1) THEN
    -- Process unassigned orders
    PERFORM assign_accepted_dispatch(order_number) 
    FROM delivery_detail 
    WHERE status='unassigned'
    ORDER BY dtts ASC;
    RAISE NOTICE 'Processed unassigned orders.';
  ELSE
    RAISE NOTICE 'No unassigned orders found.';
  END IF;
END;
$$ LANGUAGE plpgsql;

-- To call this function from pgcorn:
-- SELECT job_assign_delivery();
