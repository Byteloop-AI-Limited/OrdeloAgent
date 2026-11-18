# Ordelo ordering and delivery

Shared language for orders, customer progress and operational communication. This glossary defines business concepts; implementation paths and delivery guarantees belong in the alerts-and-notifications guide.

## Orders and participants

**Order**:
A customer's request for food from one restaurant, fulfilled by delivery or collection.
_Avoid_: transaction, conversation

**Origin channel**:
The way an order was placed: WhatsApp or web. Following the order elsewhere does not change its origin.
_Avoid_: channel without qualification

**Storefront**:
The seller-facing identity and terms under which an order is placed, such as Ordelo or a restaurant's direct offering.
_Avoid_: origin channel

**Collection**:
Fulfilment in which the customer collects food from the restaurant. Takeaway is the existing internal name for this mode.
_Avoid_: pickup when the collector could be either customer or rider

**Rider**:
A person who can be offered delivery work or is carrying out a delivery. Use **assigned rider** or **inflight rider** for the rider currently on an active delivery.
_Avoid_: customer, restaurant admin

**Restaurant admin**:
A person authorized to confirm orders and manage preparation for a restaurant.
_Avoid_: restaurant app

**Restaurant acknowledgement**:
The first valid accept or decline response by a restaurant admin to an order requiring manual confirmation. It is distinct from a message being sent or read, a timeout fallback, and the later choice of pickup time.
_Avoid_: notification delivery, timeout auto-accept

**Restaurant app**:
A restaurant's customer-facing WhatsApp conversation service. It is distinct from the people operating the kitchen.
_Avoid_: restaurant admin, kitchen

**Overwatch**:
The operations audience responsible for monitoring fulfilment and investigating escalations.
_Avoid_: all admins, restaurant staff

**Overwatch rider**:
A rider who is also a member of overwatch. Membership does not by itself establish availability for a delivery.
_Avoid_: every operations contact, the ordering customer

## Events and communication

**Order event**:
A fact about an order's lifecycle, such as payment authorization or food collection. A fact exists independently of whether anyone has been told about it.
_Avoid_: message, alert

**Customer event**:
An order event selected for customer progress, such as rider assignment or readiness for collection. One customer event can inform several customer-facing updates.
_Avoid_: notification record, message

**Customer notification**:
An order update presented or communicated to a customer. Its presence does not prove that the customer has read it.
_Avoid_: customer event when referring to the communication

**Customer notifier**:
The responsibility that records customer events and routes their customer-facing updates to the intended destinations.
_Avoid_: all-alerts service

**Notification subscription**:
An instruction to make one order's customer updates available at a particular destination and detail level. It is distinct from the order's origin and from marketing consent.
_Avoid_: origin channel, opt-in

**Order status page**:
A private customer view of an order's current progress, payment evidence and update history.
_Avoid_: push message, payment authority

**Operational notice**:
A message informing a rider, restaurant admin or overwatch of an order or service fact, without necessarily asking for corrective action.
_Avoid_: customer event

**Operational alert**:
A communication asking a rider, restaurant admin or overwatch to attend to a condition such as a late pickup or unresolved payment.
_Avoid_: every order update

**Order-event notice**:
An operational notice about a particular order, such as its becoming inflight or being collected. It is separate from the customer-facing account of the same fact.
_Avoid_: customer notification, error alert when no error occurred

**Rider timing alert**:
An operational alert about collection or delivery progress relative to the scheduled pickup time. Its audience may be the rider, restaurant admins or overwatch.
_Avoid_: rider-only alert, pickup-only alert

**Alert checkpoint**:
A scheduled opportunity to raise a timing alert for one assignment, phase and audience.
_Avoid_: message delivery confirmation

**Alert offset**:
The signed number of minutes before or after the scheduled pickup time at which an alert checkpoint becomes due.
_Avoid_: minutes since actual collection

**Alert phase**:
The leg of fulfilment an alert concerns: awaiting pickup or picked up and awaiting delivery.
_Avoid_: notification status

**Alert audience**:
The people intended to receive an operational alert: rider, restaurant admins or overwatch.
_Avoid_: origin channel

**Restaurant-app callback**:
A communication asking the customer-facing restaurant app to process an order or customer update.
_Avoid_: restaurant phone call, admin message

**Customer support call**:
A telephone conversation initiated by the customer to seek help from the restaurant.
_Avoid_: restaurant-app callback

**Feedback notification**:
A communication conveying a customer's feedback or complaint to the restaurant's admins.
_Avoid_: order progress event

## Visibility and money

**Test order**:
An order designated for simulated payment and testing. Restaurant staff should recognise it on the receipt and should not prepare its food.
_Avoid_: live customer order, free order

**Test item**:
A normal priced order item that designates the whole order as a test order and remains visible on its receipt.
_Avoid_: hidden flag, discount, free marker

**Test payment**:
A simulated payment for testing that does not move real customer money.
_Avoid_: payment authorization when the environment is unspecified

**Live payment**:
A payment that can authorize, charge or return real customer money.
_Avoid_: web payment, production order when referring only to money

**Detail level**:
How much of an order a grant permits someone to see. **Full** can include the customer delivery confirmation code, **recovered** includes private order details with the code withheld, and **status-only** limits access to basic progress.
_Avoid_: proof of ownership

**Order access grant**:
Permission to view a particular order, carried by a private credential. Knowing an order reference is not such permission.
_Avoid_: order number, customer identity

**Payment authorization**:
Approval to hold funds for an order before they are charged.
_Avoid_: capture, payment release

**Payment capture**:
Charging funds that were previously authorized.
_Avoid_: authorization, payment-complete event

**Payment release**:
Ending an uncaptured authorization so its hold can be removed.
_Avoid_: refund

**Payment refund**:
Returning money after it has been charged.
_Avoid_: payment release

**Pickup-time boundary**:
The point at which a collection order first receives its scheduled pickup time.
_Avoid_: actual collection time

**Reconciliation**:
Establishing what happened when recorded order or payment outcomes are missing, ambiguous or inconsistent.
_Avoid_: automatic retry

## Communication outcomes

**Callback accepted**:
The recipient system has acknowledged a communication request. Work promised by that acknowledgment may still be pending.
_Avoid_: message delivered

**Message sent**:
The messaging sender has accepted the outbound message request for an intended recipient. This alone does not establish receipt or reading by that person.
_Avoid_: callback accepted, message delivered

**Message delivered**:
The communication has reached the intended recipient's messaging endpoint, supported by delivery confirmation. It is distinct from the food order being delivered and from the message being read.
_Avoid_: scheduled, sent, order delivered

**Message read**:
The recipient has read a message, supported by read confirmation. A delivered message is not necessarily a read message.
_Avoid_: sent, delivered

## Acceptance, identity and checkout

**Configured auto-accept**:
A restaurant policy that accepts new orders without asking staff to confirm each one.
_Avoid_: timeout auto-accept

**Timeout auto-accept**:
Acceptance with a default pickup time after the restaurant confirmation deadline or the grace period for an admin who already accepted and still needs to set a time.
_Avoid_: configured auto-accept

**Configured-auto order**:
An order created under a restaurant's configured auto-accept policy. Its original acceptance basis does not change when the restaurant later changes its policy.
_Avoid_: every auto-accepted order

**Delivery progress**:
The order's actual fulfilment position: awaiting rider pickup, picked up and awaiting delivery, no longer in progress, or not currently verifiable.
_Avoid_: conversation state, alert outcome

**Web order**:
An order placed through the web origin channel. Its customer-facing progress is distinct from the restaurant's own WhatsApp customer conversation.
_Avoid_: every order with a browser menu

**Customer key**:
The identifier linking an order to its customer-side records. It is not necessarily a way to contact the customer.
_Avoid_: phone number in every context

**Web customer key**:
A synthetic customer-side identifier that cannot be used to contact a person. A checkout draft and an order's fixed delivery record may have distinct keys.
_Avoid_: customer phone, verified account

**Checkout**:
The customer's preparation of one restaurant/mode choice, basket and any required delivery address for placing an order.
_Avoid_: payment authorization, conversation

**Web thread**:
A correlation identity linking web checkout work with its orders and payments, without representing an agent conversation.
_Avoid_: running customer conversation

**Capture point**:
The fulfilment milestone at which an authorized payment is charged: rider assignment for delivery or the finalized pickup-time boundary for collection.
_Avoid_: checkout, actual food delivery

**Payment-complete event**:
In the order intake contract, the notice that payment has been authorized for an order awaiting fulfilment.
_Avoid_: payment captured

**Hand-off code**:
A one-time proof intended to attach a WhatsApp sender to an existing order's progress. It is distinct from the customer's delivery confirmation code.
_Avoid_: delivery code, order reference

## Dispatch and availability

**Offer**:
A delivery job proposed to one rider.
_Avoid_: assignment, job card

**Offer acceptance**:
A rider's response that they are willing to take an offered job. Several riders may accept before one is assigned.
_Avoid_: assignment

**Assignment**:
The selection of one rider to carry out the delivery, starting the inflight job.
_Avoid_: offer acceptance

**Dispatch round**:
One cycle of offering a delivery and selecting a rider. Cancelling an assignment before pickup can reopen dispatch for a new round.

**Inflight delivery**:
A delivery with an active assignment, including the leg before the rider picks up the food.

**Pre-pickup cancellation**:
Ending an assignment before the rider collects the food. The order can return to dispatch.

**Offer reminder**:
A repeat prompt to a rider who has yet to answer an offer.

**Job card**:
The assigned rider's message with pickup details and job actions.

**Rider thread**:
The rider agent's conversation for an assignment, including any remaining cancellation discussion.
_Avoid_: rider account, checkout session

**Shift**:
A rider's on-duty or off-duty state.

**Pause**:
A temporary break with a required end time. A rider pause suppresses new offers, and an admin pause suppresses new alerts for the affected restaurants through channel-aware routing.
_Avoid_: shift, unlink

**Availability**:
Whether someone is currently able to receive work or operational alerts, taking their role, shift and pause into account.

**Dispatch eligibility**:
Whether a rider qualifies for a particular delivery offer given the rider's availability and the order's requirements.

## Restaurant decisions and kitchen

**Restaurant decision**:
A restaurant admin's acceptance or decline of an order. The admin can set the scheduled pickup time after accepting.

**Timeout action**:
The restaurant policy that determines whether an unanswered order is accepted or declined at the confirmation deadline.

**Timeout auto-decline**:
Declining an unanswered order because the restaurant's configured timeout action is decline.

**Default pickup time**:
The scheduled time applied by an acceptance rule when staff do not choose a time.

**Scheduled pickup time**:
When the food is expected to be ready for the rider or the collecting customer.
_Avoid_: actual pickup time

**Rider pickup**:
The rider's physical collection of the order from the restaurant.
_Avoid_: customer collection, scheduled pickup time

**Ready for collection**:
The order is prepared and available for the customer to collect.

**Order card**:
The restaurant admin's Telegram message showing an order and the actions available to staff.

**Order-card reminder**:
A repeated prompt to restaurant admins while an order is waiting for a decision.

**Kitchen instruction**:
A direction to hold preparation, start preparing, or stop because the order was cancelled.

**Kitchen receipt**:
The preparation instruction sent to restaurant staff. For delivery it follows a rider assignment, and its arrival tells staff to start preparing the food.
_Avoid_: payment receipt, order card

**Payment receipt**:
The customer's record of payment.
_Avoid_: kitchen receipt

**Printed receipt**:
The physical receipt produced by the payment service's print workflow.

**Pay at restaurant**:
An order payment arrangement in which the restaurant collects payment directly from the customer.

## Identity, access and tracking

**Order reference**:
A number identifying an order.
_Avoid_: order access grant

**Customer contact**:
A way to reach the person who placed the order.

**Order page link**:
A private link that opens the order status page under the permissions of its access grant.
_Avoid_: live map link

**Lookup postcode**:
The postcode used to find a web order. It comes from the locked delivery postcode or the optional postcode supplied for a collection order.

**Order lookup**:
Finding recent web orders for a restaurant and postcode with status-only access.

**House proof**:
Matching the house number or name saved for a delivery order when requesting recovered access.

**Order unlock**:
Using house proof to obtain a recovered grant for a found delivery order.

**Admin roster**:
The people authorized to act as restaurant admins for a restaurant.

**Admin record**:
The person-level record of an admin's contact, links and messaging channels. Roster membership determines the restaurants they may act for.

**Admin link**:
The binding between a Telegram account and a restaurant admin's identity.

**Admin channels**:
The messaging destinations selected for an admin, which can include WhatsApp, Telegram or both.

**Rider link**:
The binding between a Telegram account and a rider's identity.

**Rider channel**:
The messaging destination used for a rider, either WhatsApp or Telegram. An assigned job keeps the channel of its offer.

**Telegram invite**:
A legacy, expiring invitation allowing a restaurant admin to link a Telegram account for one restaurant.

**Last-admin guard**:
The rule that prevents an admin pause from leaving a restaurant without an unpaused admin.

**Current-location request**:
A request for the rider to share a current position.

**Location observation**:
A recorded report of a rider's position at a point in time.

**Live tracking**:
An ongoing feed of a rider's position during a delivery.

**Zone event**:
A recorded transition in the rider's position relative to a defined area.

**Live map link**:
A link to the rider's reported position for a delivery.
_Avoid_: order page link

## Onboarding and reporting

**Restaurant onboarding**:
Preparing a restaurant to accept Ordelo orders in its selected ordering channels.

**Rider registration**:
An application to become a rider.
_Avoid_: rider link, shift

**Restaurant dashboard session**:
Temporary access to the operations dashboard for a restaurant.
_Avoid_: checkout session

**Rider payout**:
Compensation owed to a rider for delivery work.
_Avoid_: restaurant payout, customer delivery fee

**Restaurant payout**:
Funds transferred to the restaurant for an order.
_Avoid_: rider payout, payment capture

**Delivery fee**:
The delivery charge presented to the customer.
_Avoid_: rider payout
