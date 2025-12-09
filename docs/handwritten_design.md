## Delivery flow - Agent
init_delivery - Create delivery_summary, eagerly call call process_delivery()

## process_delivery
- Create records in delivery_detail for each vehicle type
- Manages
- Updates timedout based on all vehicle types and timeout from ordelo_config
- Makes post request to delivery-timedout webhook

## job_create_dispatch
- For each unassinged order for vehicle_type in delivery_detail, get_available_riders gets the available riders for a given order number, vehicle type, town and sort by priority
- Insert record into delivery_dispatch, based on batch size from ordelo_config
- Updates delivery_detail status to vehicle_type_timedout; Allows dispatches to be sent for the next batch. Next batch may be next set of riders or next vehicle type

## On dispatch insert
- Makes post request to delivery-dispatch webhook
- Calls function delivery_dispatch_whook_statement, all dispatches are sent in a single request

## Assign dispatch
- for each unassigned or vehicle timeout records in delivery_detail, run assign_accepted_dispatch
- assign_accepted_dispatch ranks the accepted dispatches and assigns the first one
- it then updates the order status across summary, detail and dispatch
- The insert into delivery_inflight kicks off the rider graph and notification of missed dispatches

## On delivery_inflight insert
- Makes post request to graph-init webhook
- Calls function delivery_inflight_whook_statement, all dispatches are sent in a single request
- Also calls notify missed dispatch whook

## dispatch_complete_func
- Updates the dispatch, detail and summary table with status='completed', 
- Removes the inflight record
- Called from agent on customer confirmation code