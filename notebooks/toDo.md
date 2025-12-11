## Immediate

- [!!!] DropOff Location not working; Its searching for `447448440754 - Drop Off`
- [!!!] Postcode is just sp1 for sp11pb; Check if lat and lon are correct however. Would the rider get the correct address when asked for in the agent?
- [!!!] Sending admin_order_ready for collection - Rider name not appearing correctly
-- No Restaurant_name in the callback data
- [!!!] If rider not already on job, there should not be a dispatch sent to him
- [!!!] Sending order reciept to restaurant admins? Where is it? Most likely when the driver accepts the job (trigger from delivery_inflight)
- admin_order_receipt (graph_init_hook) can make use of live location as a ButtonURL
- [!!!] Opening and closing times for restaurant


- [] Verify if create_order is being pass with the order_type key
- On restaurant accept, the time confirmation should include the notes; 
- Remove REST_MASTER from params.py

### 8th DEC
- Test the rider, double book orders

## Riders:
Create the WA group for riders
Add supporting materials and guides
Send videos tutorials


- Reset thread uses sget functions, need to change it. 
- Issue the admin notifications as soon as the payment is complete
- on payment successfull - update FoodOrder to status from requires_payment
- When rider declines an already accepted job, before collecting the food, Ask for confirmation. Upon confirmation, cleanup so dispatches are resumed. Clean up inflight, update order status to available.

## Delivery flow - Agent
- Remove the init_ordelo_graph, work on the setup node and add get_journey_instructions

## Location
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


# OpenAI - self heal incase of error - really need a fix for this
openai.BadRequestError: Error code: 400 - {'error': {'message': "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'. The following tool_call_ids did not have response messages: call_uJLw6MLx47cav5Vo6gq697O1", 'type': 'invalid_request_error', 'param': 'messages.[6].role', 'code': None}}
Link 
Handle this error gracefully, should happen in the agent_node/agent.invoke
openai.BadRequestError: Error code: 400 - {'error': {'message': "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'. The following tool_call_ids did not have response messages: call_zIziR7YymjJFeTXAx7Gez7li, call_A6ZJbvmyp12FpDxIFu4r19GG", 'type': 'invalid_request_error', 'param': 'messages.[14].role', 'code': None}}


    # Send restaurant order confirmation to all admins
    admin_phones = restaurant_master.admins
    order_type = food_order.action
    for admin_phone in admin_phones:
        send_restaurant_order_confirmation(
            recipient=admin_phone,
            order_number=food_order.order_number,
            order_amount=order_amount,
            order_items=order_items_str,
            order_time=order_time_epoch,
            order_type=order_type,
        )
        logger.info(
            f"Restaurant confirmation request sent for order {food_order.order_number} to {admin_phone}"
        )


http://localhost:3000/restaurant/elas?thread_id=9d211c57-4f92-4066-9f5f-9ed4421c1b1d&minimum_order=0.0&distance=0.5&recipient=447448440754&order_type=takeaway


opening browser for antigravity:
 DISPLAY=:0 google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug-session --no-first-run --no-default-browser-check http://localhost:8000/space.html > /dev/null 2>&1 &
