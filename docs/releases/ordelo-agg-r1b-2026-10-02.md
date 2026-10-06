# R1b implementation and verification — 2 October 2026

R1b is implemented locally on `release/ordelo-agg`. It is not deployed, and the
BNAT pilot and R2 Stripe payment run have not been completed. Shared routing and
configuration were read but not changed. No production SQL or new migration was
added. Unrelated SQL notebook edits were preserved.

## What changed

- All ten restaurant-app notification hooks use the customer notifier when
  `CUSTOMER_NOTIFIER_ENABLED` is enabled for their restaurant. Legacy calls stay
  available with the flag off. The two address hooks use `notify_address`, since
  there is no order to reference yet; W-ids are skipped on both address paths.
- `publish(order_number, event)` writes the event and outbox in one transaction,
  using the existing unique constraints and a per-order advisory lock. Dispatch
  claims each outbox row before sending. HTTP errors and uncertain timeouts are
  recorded with one attempt and no retry. Stored transport JSON preserves the
  original body bytes despite JSONB key ordering.
- WhatsApp orders without active subscriptions get their original restaurant-app
  destination. Web orders cannot use the restaurant adapter, including when a
  subscription is misconfigured. Web-page delivery records a skipped/no-op
  outcome; the recorded event remains available for R3. Unsupported R4 channels,
  incompatible destinations and status-only legacy subscriptions are skipped.
- Successful order creation adds the origin subscription when the notifier is
  enabled. Publishing repairs missing subscriptions. M2 publishes
  `payment_authorised` for web orders on an applied payment event; replays queue
  neither another notification nor another fulfilment initialization.
- `CUSTOMER_NOTIFIER_REST_REFS=BNAT` limits the pilot. With the flag on, a missing
  or empty allowlist means all restaurants; a failed allowlist lookup disables
  routing through the notifier. Both settings use the existing 60-second cache.
- The application runs a sweep every 60 seconds. It recovers committed but
  unattempted rows, not failed or already attempted sends. Interrupted attempts
  older than five minutes become failed without resending. No pg_cron job was
  installed: the R1b no-new-SQL scope and zero-retry guardrail take precedence
  over the checklist's generic cron/retry wording.
- The checkout's missing D32 test-payment wiring was restored: it accepts
  `test_payment`, checks the existing overwatch/restaurant allowlist helper,
  stores the allowed mode, and returns the mode. The existing three tests for
  this behavior failed on the unchanged commit and pass after the repair.

## Verification

| Check | Result |
| --- | --- |
| Frozen legacy hook contracts | All ten baseline URLs, parsed bodies and raw HTTP body strings captured from unchanged legacy hooks; same assertions pass with notifier off and on. |
| Web isolation | All ten hooks send no restaurant-app HTTP request with notifier enabled for web/W-id inputs. Misconfigured channels/destinations, inactive and status-only subscriptions are also blocked. |
| PostgreSQL | Actual queries exercised against session-temporary tables derived from the existing R1 schema inside a rollback-only transaction. Three publishes per web/WhatsApp order leave two events, two subscriptions and two outbox rows; one mocked WhatsApp send and no web send. |
| Failure and recovery | Ambiguous HTTP timeout records `failed`, attempts=1; replay does not resend. Sweep recovers an unattempted row once and leaves failed rows untouched. Temporary tables were explicitly removed. Public tables were unchanged. |
| Full Python suite | 479 passed, one pre-existing failure: `test_restaurant_master_get_admins_fetches_live_column`. The unchanged HEAD reproduced this failure and the three D32 checkout failures mentioned above. |
| Lint | New notifier/test files clean. The touched existing files have 26 pre-existing F-rule findings, matching the unchanged baseline after accounting for moved line numbers. No new lint finding. |
| Local services | Ordelo started on 3100 and Next.js on 3000 using the local testing runbook. Existing Cloudflare tunnel reused. Ordelo `/docs` returned 200. |
| Local HTTP checks | Unrelated payment event returned 200/`ignored`; invalid create-order body returned 422; disabled payment test route returned 404. No order or payment was created by these checks. |
| Browser | BNAT menu, voucher dismissal, menu search and item details worked. BNAT was closed at test time, and both list/detail add buttons stayed disabled. No browser error; one existing image/LCP warning. |
| Service logs | Successful startup and the expected 200/422/404 requests were observed. These checks do not establish a paid delivery flow or capture/cancel behavior. |

Browser evidence: `/private/tmp/ordelo-r1b-bnat-browser.jpg`.
Local process logs: `/private/tmp/ordelo-r1b-service.log` and
`/private/tmp/ordelo-r1b-frontend.log`. These are local session evidence, not
committed fixtures. No frontend source or environment file was changed.

## Pending pilot and R2

The shared Supabase is `pqsvhidiwiydgshynfib`. At inspection:

| Setting | Observed value |
| --- | --- |
| `PAYMENT_INBOX_ENABLED` | `true` |
| `ORDER_CREATE_RPC_ENABLED` | `true` |
| `TEST_PAYMENT_REST_REFS` | `BNAT` |
| `CUSTOMER_NOTIFIER_ENABLED` | absent, therefore off |
| `CUSTOMER_NOTIFIER_REST_REFS` | absent |
| `ORDELO_APP_URL` | `https://rider-agent.ordelo.app` |
| `RESTAURANT_MENU_APP_URL` | `https://restaurant.ordelo.app` |

The running local notifier cannot protect a web test order whose subsequent
callbacks still reach the production service. Maintenance-window confirmation
was requested before changing shared routing. No test payment was made.

After confirmation, re-read and save the original settings, check tunnel
reachability, switch the two runbook URLs to their test hosts, enable the
notifier with the BNAT allowlist, and restart the local service to clear caches.
Compare a WhatsApp delivery and takeaway using the intended test customer, then
perform the §18 R2 checks. Restore the saved values afterward, including absent
flag rows, and account for consumer caches as the runbook requires.

| R2 result | Status |
| --- | --- |
| Web-style order, actual Stripe test authorization and `payment_details` | Not run |
| Once-only Ordelo payment application, no restaurant-app send, payment replay | Not run against an actual paid order; offline and temporary-table checks passed |
| Capture on rider acceptance and cancel on no rider | Not run |
| Stripe webhook endpoint/event subscriptions for every account | Not inspected |
| Browser destination after payment | Not observed; the plan's expected fixed BNAT URL is not current live verification |

The R1b release acceptance and R2 remain open until these results are recorded.
