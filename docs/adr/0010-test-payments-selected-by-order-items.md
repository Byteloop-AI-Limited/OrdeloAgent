---
status: accepted
---

# Test payments and rider isolation are selected by the order's test item

The restaurant-wide payment switch sent ordinary ELAS customer orders to Stripe test, including a customer outside overwatch. For new orders, select test payment only when an accepted order item has the exact product name `TEST3100`; otherwise select live payment. Customer identity, restaurant, origin channel and browser switches do not select the payment environment.

Keep `TEST3100` as a normal priced item in the basket, payment payload and receipt, where it tells restaurant staff not to prepare the food. Save the item-derived payment mode with the order and keep that service throughout checkout, capture and cancellation. Do not scan or rewrite historical food orders; the creation rule applies when a new order is inserted.

For delivery orders containing that same test item, restrict new dispatch offers to riders who are both normally eligible and members of overwatch. Replace the current restriction based on the ordering customer's overwatch number, which permits only a rider with the same number. Filter candidates before dispatch creation and guard dispatch messages, including later missed notices, so the restriction does not merely hide initial messages while creating offers for ordinary riders. An ordinary order placed by an overwatch customer uses the normal rider pool.

The owner confirmed the receipt behaviour and clarified on 9 October 2026 that there is no retrospective repair requirement. The owner ran the routing migration; its revised file removes the unnecessary readiness and global mode-protection artifacts. Service deployment is a separate step. The detailed rollout and validation are in [the implementation plan](../../plans/test3100-payment-routing-plan.md).
