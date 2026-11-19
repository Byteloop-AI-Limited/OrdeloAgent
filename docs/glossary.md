# Payment and receipt implementation reference

See the [canonical Ordelo glossary](../GLOSSARY.md) for payment authorization, capture, the pickup-time boundary, reconciliation and receipt terminology.

- The payment service uses `collection` as an action and receipt status for Ordelo takeaway orders.
- In the online collection flow, authorization stores the payment intent. The later capture workflow charges the customer and also handles payout and printing. Printed capture receipts include product items and exclude service, delivery and small-order fees.
- The collection capture flow retries an explicit pre-capture payment-intent lookup failure. Other failures go to reconciliation.

See [the collection capture decision](adr/0002-takeaway-manual-capture-at-pickup-time.md) and [the payment and order flow](payment_and_order_flow.md).
