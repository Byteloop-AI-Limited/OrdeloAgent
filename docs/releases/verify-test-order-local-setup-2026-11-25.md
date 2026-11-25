# Local test order run — 25 November 2026

Verified the storefront-controls changes ([plan](../../plans/web-storefront-controls-and-audit.md)) on the local setup with
TEST3100 orders at Strikers (STRK), simulated payment and Telegram Web. Branch `feature/bnat-price-fix`, tip `7399f77`.
Times are UK time. The method is now the
[verify-test-order-local-setup skill](../../.claude/skills/verify-test-order-local-setup/SKILL.md).

## What ran where

| Part | Code |
| --- | --- |
| Storefront, checkout, tracking, restaurant dashboard | Local (`restaurant-test.ordelo.app`) |
| Timeout, default pickup, dispatch and pickup-set hooks | Local (`ORDELO_APP_URL` = `rider-agent-test.ordelo.app`) |
| Telegram taps and messages | **Deployed production.** Both bot webhooks pointed at `rider-agent.ordelo.app` throughout; the taps reach the same SQL functions |

## Results (live local)

STRK policy during the run: auto-accept off, 3 minutes, `decline`, pickup overrides 30 / 30.

| Scenario | Order | Result |
| --- | --- | --- |
| Collection, Accept, no pickup time | `STRK-WUQP-20` | Pass. `auto_accept`, pickup exactly order time + 30; log shows the RPC and one guarded update; tracking "Ready around 10:47" |
| Delivery, Accept, no pickup time | `STRK-SAZD-21` | Pass. `auto_accept`, +30, one notice. Offers went only to the two overwatch riders. Rider accepted, codes 37 and 80, `completed`; tracking "Delivered" |
| **Blank (inherited) override**, delivery | `STRK-UCBX-23` | Pass. Stored value `''`; `auto_accept`, +30, no error. Left unaccepted by riders: `timedout`, `payment_released`, `no_rider_found` |
| **Blank (inherited) override**, collection | `STRK-XJDR-24` | Pass. `auto_accept`, +30 |
| Explicit pickup time, blank override | `STRK-VUWE-26` | Pass. 11:00 (+25) chosen; still `restaurant_accept` after the 15 s grace |
| Silence, collection | `STRK-MZTY-22` | Pass. Countdown; "Checking with…" at 10:26:33; `auto_decline` 10:26:41; page "Order cancelled" with the shared copy and released hold 10:26:54. All seven alerts sent |
| Manual Decline, collection | `STRK-FGUZ-27` | Pass. Same customer copy as silence; `restaurant_decline`; released |
| Accept, pickup tap too early | `STRK-RZVN-25` | Automation miss: Telegram Web dropped the second tap, so the fallback ran (+30). Not a product failure |

The blank override was set with the dashboard's "Use default" (audit rows 20, 21) and restored to 30 / 30 (rows 22, 23),
confirmed by a read. The default and the override are both 30, so this proves the blank value no longer fails, not that a
different global number is used; the isolated SQL tests cover that.

Price audit (read-only): `below_floor` flags all seven earlier lines (£9.50 against £10.00) at STRK's current allowance of 0
and none at 5. Until the alignment SQL is applied, the next nightly audit (about midnight) will flag all eight STRK orders and alert overwatch.

## Backend errors seen

Only the expected `Payment capture failed` for simulated payments (no PaymentIntent; overwatch alerted).

## Not verified

- **Production.** This was a local rehearsal. Commit `913302c` (the fix) is on no remote branch, and `origin/dev` still has the
  old `_get_delivery_pickup_default_minutes` parser. Once `ORDELO_APP_URL` goes back to production the timeout hooks run the
  old code again, so no restaurant should use the dashboard's "Use default" until the fix is deployed. The plan's rehearsal
  after deployment is still outstanding.
- The approved **2-minute** policy: not applied. Live STRK is 3 minutes; CRDO still has auto-accept on.
- `release_pending` as a visible intermediate state: a simulated payment is released at once.
- Accept after the deadline but before the sweep (isolated SQL tests cover it).
- Telegram handlers in this checkout, and Stripe authorisation, capture and payout.
- CRDO, CRMS and BNAT: no orders placed.

## Skill scripts

Run as committed: `order` (collection), `tg-tap`, `tg-read`, `watch-page`, `open`, `close`, and `db_evidence.py` `preflight`
and `order`. The delivery branch of `order`, `click`, `tg-say`, `dump` and `db_evidence.py watch` were run as the scratch
versions they were built from. Ruff F rules pass; the three focused pytest files pass (103 tests).

## Findings

Recorded in the [to-do](../to-do.md#found-by-the-local-test-order-run-25-nov-2026): checkout reused after payment, dashboard
totals include declined and no-rider orders, and "no answer in time" wording after an Accept.

## Follow-up: repeat-order fix (same day, local code, uncommitted)

| Check | Result |
| --- | --- |
| Failing case: same basket straight after payment | Pass. `STRK-DDHA-28` then a new order `STRK-ZHBX-29` on a new checkout (resume returned 409) |
| Retry before payment (review twice) | Pass. Both passes used `STRK-DDHA-28`; one row (resume returned 200) |
| Checkout tab left open, order paid in another window | Pass. "You've already paid for this order"; no second order beside `STRK-XYFP-30` |
| Delivery repeated | Pass. `STRK-GUUZ-31`, then `STRK-HFGQ-32` |

All five orders were declined in Telegram. Offline: OrdeloAgent 1,931 passed with 3 failures that also fail on clean `HEAD`
(one, the stale database guide, is now regenerated); restaurant-frontend 390 passed, lint and types clean. Isolated database:
the payment rule passes on real Postgres. Not verified: a live Stripe payment; the seconds between a Stripe payment and its
webhook, when the order still reads as unpaid and the same checkout is reused.

## Left behind

Eight test orders in the main run: one delivered, one no-rider, two declined and four collections marked ready. A collection ends at ready;
there is no restaurant-side "collected" action, so those four stay `pickup_confirmed` with `ready_at` set. No active cron job
acts on that state. Routing stays on the test hosts for the owner to restore
([runbook section 7](../local-testing-runbook.md)).
