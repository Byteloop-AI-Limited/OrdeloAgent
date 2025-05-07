## Delivery and Dispatch:
- Dispatch based on vehicle type; Requires change in dispatch logic
- Integrate the 2 digit confirmation code; Should it exist in dispatch or delivery detail?

## Location handling
- Change from atomic inserts to batch inserts using queues
- Change the live location link to call the url - Done
- Make use of reusable CallBackButton data

## Agent enhancements
When a random message to WhatsApp, send standard message if no active thread.
    Look at thread