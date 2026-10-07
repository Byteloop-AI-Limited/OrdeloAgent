# Ordelo glossary

Canonical domain terms are in [GLOSSARY.md](../GLOSSARY.md). This older reference preserves payment/receipt implementation terminology; alerts and notification outcome meanings are documented in [alerts-and-notifications.md](alerts-and-notifications.md).

| Term | Meaning |
|---|---|
| Takeaway | Ordelo's internal `food_order.action` value for a collection order. |
| Collection | Payment-service action and receipt status for takeaway payments. |
| Authorization | Customer approves a manual-capture payment; the payment service stores the PaymentIntent and prints nothing. |
| Capture | Charges an authorized PaymentIntent, transfers the restaurant payout, and prints the receipt. |
| Product items | Food item lines shown in capture receipts. |
| Fee items | Service, delivery, and small-order fee rows, excluded from every capture receipt. |
| Pickup-time boundary | The first non-null takeaway `pickup_time`, which initiates online-payment capture. |
| Safe retry | A retry after the explicit pre-capture PaymentIntent lookup failure only. |
| Reconciliation | Manual investigation of a non-retryable or exhausted capture failure. |
