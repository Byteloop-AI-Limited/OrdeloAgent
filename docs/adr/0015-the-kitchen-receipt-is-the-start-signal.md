---
status: accepted
---

# The kitchen receipt is the start signal

Decision: 17 November 2026. A delivery kitchen waits for the kitchen receipt, which is scheduled when a rider is assigned. Setting a pickup time is restaurant
acceptance, not permission to cook. Takeaway has no rider dependency and is never held.

Delivery cards in `pickup_set` / `auto_accepted`, WhatsApp pickup replies and auto-accept notices say:

> ⏳ Don't start cooking yet — we're finding a rider.
> Start when the kitchen receipt arrives.

A rider can accept an offer before the assignment job selects them. The [inflight handler](../../watomation/routers/delivery_hooks.py#L610) schedules the kitchen receipt for the selected rider. The receipt is the start instruction for restaurant staff. The payment receipt and the payment-service print workflow have separate roles.

The kitchen receipt begins **🍳 Please start preparing now**, followed by **Rider found · ready for pickup at …**
(delivery) or **Ready for collection at …** (takeaway). The current pickup time follows +10 / +20 adjustments.
Telegram uses this headline only while the receipt is `open`; Ready restores the existing receipt heading.
WhatsApp receipts are not edited, so their original start instruction remains.

The card stays terminal after the pickup time is set (D4). Its hold text is superseded by the receipt threaded
beneath it. Rejected: a live card saying “Rider found”, because it would require rider state in
`t_order_card_status()` and another refresh trigger. No status key, SQL, migration or configuration key is added.

A replacement rider's fresh receipt uses the same “Please start preparing now” wording (D7), even if the kitchen
has already started. There is no re-dispatch flag or alternate wording.

Every delivery, including configured auto-accept restaurants, gets the hold and the no-rider cancellation notice
(D3). If no rider is found, admins on both channels are told **❌ No rider found for {order_number}. / The order is
cancelled — please don't prepare it.** as a reply to the card where its message ID is available. Overwatch stays
notified. Payment release, customer events and test-order webhook exclusions are unchanged.

`utils_common/order_management/kitchen_instructions.py` owns the plain-text hold/start/drop instructions;
Telegram and WhatsApp adapters add their own markup. Existing statuses and domain events decide when to use them.

Live verification remains separate: check the actual Telegram phone notification preview, WhatsApp receipts,
auto-accept, no-rider cancellation, and takeaway with `docs/live-order-test-harness.md`. Offline rich-message
tests cannot establish what the phone's notification preview shows.
