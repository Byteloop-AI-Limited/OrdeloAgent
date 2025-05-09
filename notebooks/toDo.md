## Delivery and Dispatch:
- Dispatch based on vehicle type; Requires change in dispatch logic; 
    - get_available_riders to include vehicle type
    - Create delivery_detail record with vehicle type *(ordered)*; Insert record only if the order_id is unassigned
- Integrate the 2 digit confirmation code; Should it exist in dispatch or delivery detail?
- add pickup time to delivery detail table and the pymodel
- Add vehicle type to delivery_dispatch table (job_create_dispatch)
- Change ant_master city to town (change in create_delivery_detail)

## Location handling
- Change from atomic inserts to batch inserts using queues
- Change the live location link to call the url 
- Make use of reusable CallBackButton data


## Delivery flow
- notification of the location events, order completion.

## Pricing service
- Is the distance calculated based on the vehicle type?


## Agent enhancements
When a random message to WhatsApp, send standard message if no active thread.
    Look at thread

## How to indentify the deliveries that failed?
To consider cases where the rider did not deliver the order at all, or did not deliver within a certain time frame.
- Create a notification for dispatches that have been open for too long. It could be based on the pickup time and the distance. 
- How should it be handled? Reachout to rider on whatsapp and prompt a call from restaurant. What is the handoff scenario?
