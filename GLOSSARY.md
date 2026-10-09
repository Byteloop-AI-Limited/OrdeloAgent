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
The person assigned to collect food from a restaurant and deliver it to a customer.
_Avoid_: customer, restaurant admin

**Restaurant admin**:
A person authorized to confirm orders and manage preparation for a restaurant.
_Avoid_: restaurant app

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
The amount of order information a viewer or subscriber may see: full details or status only.
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
The point at which a collection order first has its pickup time finalized.
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
Acceptance used as a fallback when a manually confirmed order reaches its confirmation deadline.
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
The notice that payment has been authorized for an order. Its name does not mean later capture has occurred.
_Avoid_: payment captured

**Hand-off code**:
A one-time proof intended to attach a WhatsApp sender to an existing order's progress. It is distinct from the customer's delivery confirmation code.
_Avoid_: delivery code, order reference
