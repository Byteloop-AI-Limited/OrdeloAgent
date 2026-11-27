# pg_cron rollout verification, 27 November 2026

Tested OrdeloAgent at `dd087a2` through the local FastAPI and storefront tunnels against the shared Ordelo database. The rider Telegram bot called the local app. The restaurant-admin Telegram bot ran on production and its database decisions triggered the local app. The production deployment is outside this report.

| Check | Result | Evidence |
| --- | --- | --- |
| Rollout and drift | Pass | The rider-invite migration was already present. Its 19 function bodies, constraints and indexes matched. Applied the six remaining files in one transaction and switched the local checkout. All 24 in-scope live function bodies matched the branch. |
| P1-1. Idle invite job | Pass | Three successful minute ticks without an invite-alert POST when nothing was due. |
| P1-2 to P1-5. Staged invite alert outage and recovery | Pass for the queue and recovery | Paused only the invite job at 13:24. The test rider claimed through Telegram at 13:26 using the documented typed `/start` fallback. The alert stayed pending for 157 seconds. No invite-alert POST or new matching WhatsApp message appeared while paused. Restored the schedule at 13:28. The 13:29 tick returned HTTP 200 from local FastAPI and processed the one queued row. WhatsApp accepted the alert for three recipients, and one new matching message appeared in the monitored chat. |
| P1-6. Post-recovery idle | Pass | Three further minute ticks succeeded without another invite-alert POST or a duplicate in the monitored chat. |
| P1-7 and P1-8. Invite with cron active | Pass | The new Telegram Web invite link claimed itself at 13:35:21, with no typed fallback. At 13:36 the local hook returned HTTP 200 and processed the second alert once. WhatsApp accepted three recipients, and one new matching message appeared in the monitored chat. The rider profile and dashboard session count matched baseline. |
| P1-9. Reopen a claimed invite | Pass | The local rider webhook accepted the reopened link at 13:47. The invite rows and rider profile matched the pre-reopen state. No invite-alert POST or new matching message appeared. |
| P1-10. Rider-offer job | Pass | The existing five-second rider-offer job continued to tick successfully. |
| P2-1. Customer and lifecycle schedules | Pass | Observed three consecutive ticks for each job, with one HTTP 200 and a completed sweep in the local app per tick. |
| P2-2. Decline and payment release | Pass for simulated decline and customer state. Cron retry unverified live. | For `STRK-USEV-23`, the restaurant bot recorded the decline, the local handler emitted `payment_released`, and the tracking page showed “Order cancelled” and “Payment released”. `TEST3100` has no payment intent. The decline handler released it inline, so it created no `web_payment_release` row for the cron job to consume. |
| P2-3. Accept, pickup and ready | Pass | `STRK-VSQJ-24` kept `restaurant_accept` with the explicit 2:25 PM pickup time. `ready_at` and `ready_for_collection` were recorded and the tracking page showed “Ready for collection”. The order’s `web_page` outbox rows each had one attempt and status `skipped`, consistent with the polling channel. |
| P2-4. Price audit already-completed case | Pass | The 13:05 cron run succeeded. The manual invocation at 13:47 returned true, with the day’s existing completed ledger row unchanged and no price-audit webhook call. The live check covered the already-completed case. |
| Offline release and sweep coverage | Pass | Ran 19 targeted tests covering sweep routes, queued release handling and release recovery. |

The first checkout attempt inherited two Curry Chips from the storefront basket and created `STRK-AFGJ-22` as a live-mode draft. The runner stopped before payment, and the final database check confirmed `requires_payment`. The retry verified both the basket and checkout contained only `TEST3100 × 2` before selecting **Simulate payment**.

## Final state

The four added cron jobs are active. `job_rider_invite_alerts`, `job_customer_outbox_sweep` and `job_web_lifecycle_sweep` run every minute. `job_web_price_audit` runs at minute five each hour. The remaining jobs matched the pre-rollout list.

Both simulated orders reached their intended final state, and the original two-item basket was restored. The shared URLs still point to the local test tunnels. Restore routing when local testing ends, following the timing in the [rollout plan](../../plans/telegram-rider-invite-alert-schedule.md#7-production-rollout-and-rollback).
