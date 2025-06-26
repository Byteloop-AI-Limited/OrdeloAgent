
## Delivery flow - Agent
- Remove the init_ordelo_graph, work on the setup node and add get_journey_instructions

## Rider Agent


## Location
- Disable offline capture on owntracks app - Not possible, so implement a check to see if the location is within the last 5 minutes. This logic should be in @owntracks-webhook_edge_funciton.ts 
- Update the job_process_owntracks_q to populate both rider_location and rider_location_event tables
- rider_location_event table should have a trigger to call rider_hooks based on the order_number (ie call the right consumer)
- Write a script to get the distance travelled

## Scheduled delivery events
- Create a new route for these events
- Events include
    - location not enabled for inflight deliveries
    - Riders not moved for a while
    - inflight not completed for over 45 mins
    - order not ready for pick up even after the pickup time


## Delivery and Dispatch:
- The dispatches are being sent even after the job has been accepted - Debug + notify missed dispatches should be tested as well. 
- Change restaurant_master city to town (change in create_delivery_detail)

## rider_registration
- build logic to populate rider_master table from rider_registration table

## Location handling
- Change from atomic inserts to batch inserts using queues
- Change the live location link to call the url 
- Make use of reusable CallBackButton data

## Pricing service
- Is the distance calculated based on the vehicle type?
- Increase the coverage limit


## Agent enhancements
When a random message to WhatsApp, send standard message if no active thread.
    Look at thread

## How to indentify the deliveries that failed?
To consider cases where the rider did not deliver the order at all, or did not deliver within a certain time frame.
- Create a notification for dispatches that have been open for too long. It could be based on the pickup time and the distance. 
- How should it be handled? Reachout to rider on whatsapp and prompt a call from restaurant. What is the handoff scenario?
