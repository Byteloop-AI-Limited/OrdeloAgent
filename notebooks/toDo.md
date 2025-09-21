## Immediate
- Session management - MarkFor Deletion. 
- Move catalog to Elai.
- When rider declines an already accepted job, before collecting the food, Ask for confirmation. Upon confirmation, cleanup so dispatches are resumed. Clean up inflight, update order status to available.
- Debug payment capture error
- Why isnt the delivery summary timed out?

## Delivery flow - Agent
- Remove the init_ordelo_graph, work on the setup node and add get_journey_instructions

## General Refactor
- Remove imports from utils_common.lg_utils and any common utils. May be create a utils folder.

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
