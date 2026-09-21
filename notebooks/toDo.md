## ordelo-agg
2. Finish the rider alerting feature, May be its better to have the alerting to admins as well, since they will be in the 24hr window
1. admin enquiry - remove duplicates
3. Change the UI to include orpington payouts as well. 
4. remove Ramaswamy from inflight

## Test the deploye of these apps on fly.io
## INFO:     2a00:23c8:47bd:b201:9528:5ae4:7210:5f25:0 - "GET /location-hooks/live-location-map/SFCS-CORT-21 HTTP/1.1" 404 Not Found - Called when asked about location, this will be part of the redesign
## mono repo testing should continue - Need to find out the webhook efficiency

## Test checkpoint
On no driver found, retain_thread should be set to False:
SFCS-0cd2215c-4501-4c82-baed-f7a8c1660f8d

Users ignore waiting for marketing consent, at this point, retain_thread should be set to False. 
SFCS-719e2da9-d19b-4e96-86a9-c19971ee2fb9
SFCS-efb54f9a-69dc-4234-895f-41b4b3c40388

// Need to check why the thread is not closing
SFCS-7c8471ba-f4e2-49b2-bd9d-10a12c21b037

Callback update of pickup time should not be sent to drive if the
order has been picked up. (rider ageent change)

This doesnt close the thread, need to check why.
SFCS-f4eb506b-aa1b-4f2a-a92c-0aa029fffa1d

Need to deploy latest changes on dev; Create fake order, need to capture dispatch webhook response.
SFCS-719e2da9-d19b-4e96-86a9-c19971ee2fb9 - thread is active
To revisit, you can:

Ask me to "show the P7 TODO list" or "load the P7 checkpoint memory"
Reference the checkpoint by memory ID or tag when resuming
Current status: 5 of 7 tasks completed. One test failing (test_send_product_sections in test_p7_wa_senders.py).



## New design for terminating threads:
-- Get the latest checkpoint for a thread
SELECT
    thread_id,
    checkpoint_id,
    checkpoint -> 'channel_values' AS state
FROM checkpoints
WHERE thread_id = 'SFCS-9c0d987a-c772-4439-8511-a011344ceb65'
  AND checkpoint_ns = ''
ORDER BY checkpoint_id DESC
LIMIT 1;

<!-- utils_common/thread_management/thread_mgmnt_ddl.sql (get_stale_active_threads) -->

## SFCS go live changes

class RestaurantConfirmationPayload(BaseModel):
    """Payload model for restaurant confirmation webhook."""

    trigger_reason: str
    delivery_summary: DeliverySummaryData
    restaurant_master: RestaurantMasterData
    food_order: FoodOrder
    order_items: List[OrderItem]


## Takeaway streamlining.
- move some packages to dev depndancies
- in @takeaway_hooks.py, what is the flow when the pickup time is updated? 
Its should create admin_order_reciept, with option to notify customer for pickup
This notify should use webhook router to call restaurant and invoke the agent
The agent should ideally terminate the thread after this.

- is AutoAccept working for takeaway?, particularly after the restaurant_accept

- Remove the live tracking flow or mention of it. - Removed in elai agent, verification required.
- Does this mean rider agent should have request_location tool? - Should this be a sperate functionality of its own?

- run_rider_agent_w_custom_msg - check if the rider has collected the food and is inflight before sending this message

### Investigate this trace:
 await debug_thread('ORDELO-ee723178-5eb3-4d6b-a171-1f7c2d1e80e2')
  {'ToolMessage': {'content': 'Order number not found in state.',
    'additional_kwargs': {}}},
  {'AIMessage': {'content': '', 'additional_kwargs': {'refusal': None}}},
  {'HumanMessage': {'content': 'call `tool notify_food_ready_for_pickup`. Rider should hurry to Elai Salisbury to pickup the food.',
    'additional_kwargs': {}}},
  {'AIMessage': {'content': '/dontRespond: Link to enable the live location tracking is sent to you.',
    'additional_kwargs': {}}},
  {'ToolMessage': {'content': 'Link to enable the live location tracking is sent to you.',
    'additional_kwargs': {}}},
  {'AIMessage': {'content': 'Thank you, Abubakar. The restaurant confirmation code has been verified successfully. Please proceed to deliver the order to the customer.\n\nI will resend the live tracking link to ensure your tracking is active.',
    'additional_kwargs': {'refusal': None}}},

### Chat with riders.
If resistance on 150,
  1. Mention the savings that they make on deliveries.
  2. AI Powered, their own channel, customer base, marketing msgs, on whatsapp - most effetive for reaching, brand presence
  3. Just Delivery in Orpington and takeout - takeout for other locations (customized solution) + Only onboarding costs
  4. Commitment - 100 gbp to get started with onboarding and implementation.

## GoLive checklist:
WABA change on both elai and ordelo
Config updates for 

    update ordelo_config set config_value = 'https://elas-agg.ordelo.app' where config_key = 'ELAS_APP_URL';
    update ordelo_config set config_value = 'https://rider-agent.ordelo.app' where config_key = 'ORDELO_APP_URL';
    update ordelo_config set config_value = 'https://restaurant.ordelo.app' where config_key = 'RESTAURANT_MENU_APP_URL'; 
Hi There, On decline from rider;


Change the lat and lon for ELAS;
Update ELAS adming in restaurant master
Update 

- 
## Immediate
- [!!!] One restConfirmation, ackonwledge and then ask to start live tracking
- admin_order_receipt (graph_init_hook) can make use of live location as a ButtonURL Not possible to mix interactive with buttonURL

### 8th DEC
- Test the rider, double book orders
Message(id='wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAEhgWM0VCMDZDRkY5OTU1RTU0QkJGMjQ1NgA=', timestamp=datetime.datetime(2025, 12, 11, 17, 33, 25, tzinfo=datetime.timezone.utc), metadata=Metadata(display_phone_number='447823713944', phone_number_id='434523189754637'), from_user=User(wa_id='447448440754', name='10hith', identity_key_hash=None), waba_id='490733454126658', type=MessageType.TEXT, reply_to_message=None, forwarded=False, forwarded_many_times=False, text='hi', image=None, video=None, sticker=None, document=None, audio=None, caption=None, reaction=None, location=None, contacts=None, order=None, referral=None, error=None)

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
DISPLAY=:0 google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug-session --no-first-run --no-default-browser-check {{URL}} > /dev/null 2>&1 &
