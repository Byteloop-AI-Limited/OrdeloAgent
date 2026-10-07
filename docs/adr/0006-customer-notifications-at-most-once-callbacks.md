# Customer events are durable; restaurant-app callbacks are attempted at most once

Status: documented existing implementation and R1b decision, 7 October 2026; no runtime policy change.

Ordelo records customer events independently of their communication outcomes. A web customer reads the recorded progress on the private order status page; a WhatsApp order invokes its customer-facing restaurant app through an outbox callback. Restaurant-app callbacks are claimed before I/O and are not retried after an attempted or interrupted send, because an ambiguous timeout may already have advanced a conversation or sent a customer message. This favors avoiding duplicate side effects over guaranteeing every customer update; the sweep recovers only unattempted rows and records stale interrupted attempts as failed.

A web-page outbox row marked `skipped` is a successful no-op transport choice, not a missing customer event. A restaurant-app row marked `sent` means its HTTP callback returned successfully, not that a customer read a WhatsApp message. Rider timing alerts and payment-cancellation recovery use separate ledgers and policies; this decision does not give them the same guarantees.

Sources: [customer_notifier.py](../../utils_common/notify/customer_notifier.py), [accepted plan R1b implementation update](../../plans/ordelo-agg-plan-cc.md), [alerts and notifications guide](../alerts-and-notifications.md). The older generic retry wording in the plan is narrowed by its explicit R1b implementation update.
