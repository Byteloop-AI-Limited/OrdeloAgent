## Delivery and Dispatch:
- Integrate the 2 digit confirmation code; Should it exist in dispatch or delivery detail? - partially done, need to control > 100
- Find where notify_missed_dispatches is called
- add pickup time to delivery detail table and the pymodel
- Change restaurant_master city to town (change in create_delivery_detail)
- On timeout of a delivery, notify the customer on not being able to accept the order.
- Assigment of multiple accepts should be based on most recent dispatch.
- Caraousel of the jobs?
- Reply to a particular msg when rider accepts

## Issues identified
- when multiple accepts, there is no response
- No decline sent to other accepts

## rider_registration
- build logic to populate rider_master table from rider_registration table

## Location handling
- Change from atomic inserts to batch inserts using queues
- Change the live location link to call the url 
- Make use of reusable CallBackButton data


## Delivery flow
- restaurant 2 digit confirmation
- Restaurant confirming food ready for pickup
- notification of the location events, order completion.

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
