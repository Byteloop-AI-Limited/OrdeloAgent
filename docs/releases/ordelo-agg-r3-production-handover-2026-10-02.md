> Historical design/verification snapshot. Payment testing was superseded on 9 October 2026: new orders use test only with an exact `TEST3100` item, and test delivery offers are restricted to eligible overwatch riders. See the current test-orders guide.

# R3 production handover — 2 October 2026

The owner intends to check in/deploy OrdeloAgent and restaurant-frontend and
ultimately enable web ordering for ELAS. This document records the release
position and configuration. The owner subsequently authorised the table changes
below; they were applied and verified at **15:39 Europe/London**. No provider
changes or deployment were performed by that configuration update. Both app
URLs and the Meta override were restored by the
owner and verified read-only at approximately **14:46 Europe/London**.

## Release position

The normal overwatch WhatsApp delivery regression **ELAS-LXGM-26 passed**,
including the owner's frontend UI ordering, restaurant acceptance, rider
assignment, £28.37 Stripe-test capture, pickup and customer-confirmed completion.
All four recorded customer notifications had one successful restaurant-app
adapter attempt. This is evidence for that delivery path, not for every
WhatsApp payment/mode combination or a non-overwatch live customer.

R3 web creation, access and test authorisation work. **Web collection capture
failed for ELAS-RNRX-25.** I recommend deploying the code with new web checkout
paused while the issues below are resolved. I cannot recommend paid web ordering
on the current evidence. Low expected traffic on `/town` is not an access
control: a customer can still open the page or use its public API, and the live
sitemap can advertise those pages. The owner's wish to enable web is recorded;
the final ELAS live values are specified below without calling them accepted.

See the [detailed R3 evidence](ordelo-agg-r3-2026-10-02.md) for bugs fixed,
533 passing tests, the pre-existing deselected failure, actual order/provider
IDs, concurrency testing and evidence limits.

## Unresolved issues

| Issue | Evidence / required next step | Effect on release |
|---|---|---|
| Manual collection capture | RNRX-25 has no payment_details record under either short or full reference. Three capture attempts failed. At 14:47 local Stripe still reports £27.90 authorised, zero received. Actual session metadata lacks captureMode/restRef. Local payment-service commit `58158ca` already adds manual-capture metadata and persistence; inspect the deployed creation and webhook Lambdas and deploy/verify that fix through the separate payment-service release. Reconcile the existing session separately. | Blocks live paid web collection; can also affect WhatsApp manual-capture collection. No source workaround, fabricated DB payment row or longer retry was used. |
| Production web environment | Current `restaurant-frontend/amplify.yml` copies only legacy variables into `.env.production`, omitting new web mode, key, cookie secret and site URL. Amend its existing allowlist to include the names below and configure actual production values. R3 now resolves the backend through `ordelo_config.ORDELO_APP_URL`, using the shared WhatsApp URL lookup. Backend needs the matching key too. Amplify wiring is documented, not changed in this handover. | Web will not function in production just by committing local `.env.local` settings. |
| Remaining regression | Real web delivery, collection success after provider fix, decline/no-rider cancellation, late-payment cancellation and kill switch with an in-flight order have not passed the full R3 matrix. Non-overwatch live WhatsApp payment, takeaway and pay-at-restaurant were not rerun during R3. | R3 acceptance remains incomplete. Earlier R1/R2 evidence is separate. |
| Public business/legal details | Owner chose to leave business identity, support email and approved Terms/Privacy links pending. | Pending public launch details; no names or legal copy invented. |
| Production privacy | App query logging was redacted, but development access logs include secret `/o/{token}` paths. Verify/mask actual ingress, Amplify and backend access logs before launch. | Infrastructure token/privacy acceptance remains open. |
| Monitoring and pricing | M1–M9 operations acceptance remains open. Price-floor audit exists but is off. Client-supplied pricing is the accepted D8 risk; this audit only alerts, it does not enforce menu prices. | Complete/enable monitoring before public orders; do not describe D8 as fixed. |
| Accessibility | Lighthouse mobile accessibility ≥90 has not been measured. | Open planned R3 entry gate. |
| Existing test failure | `test_restaurant_master_get_admins_fetches_live_column` predates R3 and expects fresh fetch whereas current get_admins returns its cached field. | Documented separate defect; 533 tests passed with this one deselected. |
| Existing security limitations | Legacy routes remain outside the new authenticated `/web/*` router; webhook signatures remain the accepted existing limitation. | Record existing hardening scope; do not claim the whole backend is authenticated because web routes use a key. |

## ordelo_config: verified current and target

The table is **public.ordelo_config**, keyed by config_key; values below are
config_value strings. On the owner's explicit approval, retired restaurant-wide payment switch
was changed from BNAT,ELAS to BNAT and WEB_ORDERING_ENABLED_REST_REFS from ELAS
to the empty string. WEB_LATE_PAYMENT_GUARD_ENABLED was already true and retained.
All seven production URL/payment/notifier settings were verified unchanged
after commit. Before snapshot (private, mode 600):
`/private/tmp/ordelo-r3-production-config-before-20261002T143925Z.json`.

| Key | Verified at 15:39 local | Deploy code with checkout paused | Final ELAS live target after acceptance |
|---|---|---|---|
| ORDELO_APP_URL | `https://rider-agent.ordelo.app` | Keep: owner restored | Same |
| RESTAURANT_MENU_APP_URL | `https://restaurant.ordelo.app` | Keep: owner restored | Same |
| PAYMENT_INBOX_ENABLED | `true` | Keep `true` | `true` |
| ORDER_CREATE_RPC_ENABLED | `true` | Keep `true` | `true` |
| ENABLE_PAYMENT_TEST_ROUTES | `false` | Keep `false` | `false` |
| CUSTOMER_NOTIFIER_ENABLED | `true` | Keep `true` | `true` |
| CUSTOMER_NOTIFIER_REST_REFS | `ELAS,BNAT` | Keep existing pilot | `ELAS,BNAT`; do not widen automatically |
| retired restaurant-wide payment switch | `BNAT` | Restored documented production baseline | `BNAT` |
| WEB_ORDERING_ENABLED_REST_REFS | Empty string `''` | New web checkout paused | `ELAS` |
| WEB_LATE_PAYMENT_GUARD_ENABLED | `true` | Keep `true` while any web payment/session can arrive | **Keep `true`**, required for live web |
| WEB_PRICE_MONITOR_ENABLED | absent/off | Can stay off while checkout paused | `true`, after checking audit and ops alert destination |
| ELAS_WEB_MAX_DISCOUNT_PERCENT | absent, default 0 | No change needed while paused | `0` for current no-offer web menu; revise if offers are approved |

An empty **web** allowlist disables new web checkouts, while an empty notifier
allowlist means **all restaurants**. Do not empty the notifier pilot list to
pause web. Disabling the notifier, inbox or order RPC is not the production
restoration for this release. Keep PAYMENT_INIT_RECONCILER_SINCE, timeouts,
restaurant URLs, admins, rider availability and cron unchanged. Init reconciler
scheduling remains the owner's deferred D33 item.

The R3 flags were originally absent, but removing the late-payment guard now
would leave payable sessions unprotected. Deploying R3/live web keeps it enabled;
an eventual complete rollback can remove it only after all relevant sessions and
financial jobs are resolved. Keep the additive R3 schema migration applied.

The [pause/unpause SQL](../../notebooks/db_queries/ordelo-agg-db-switch.sql) writes
only the three differing/required R3 handover values and then reads the wider
profile back. PAUSE is the default; the ELAS UNPAUSE section is commented out
and must be selected separately, after the launch gates are complete. The
PAUSE target values were applied through a scoped transaction with
a before snapshot and independent post-commit verification; the unchanged late
guard row was not rewritten. For future use, save its before SELECT first.
The legacy skill's pre-R1b production profile turns the notifier
off and must not be blindly used for this release.

## Production environment outside the table

| Service / variable | Production setting |
|---|---|
| Backend ORDELO_WEB_KEY | Strong production server secret, ≥32 characters; alternatively AWS application secret field `ordelo_web_key` as supported by require_key. Keep outside Git. |
| Frontend ORDELO_WEB_KEY | Exactly the same backend secret, server only. |
| Frontend WEB_COOKIE_SECRET | Separate strong production secret, ≥32 characters; stable across rebuilds so valid cookies continue to work. |
| Backend URL lookup | R3 uses `ordelo_config.ORDELO_APP_URL` through `getRiderAgentUrl()`, like WhatsApp. The shared lookup caches for 60 seconds and retains `RIDER_AGENT_URL` as its fallback when DB configuration is unavailable. `ORDELO_WEB_API_URL` is no longer used. |
| Frontend NEXT_PUBLIC_WEB_ORDERING_MODE | `live` renders the real channel; a production rebuild is required. New checkout still obeys the backend empty/ELAS allowlist. `off` makes web routes unavailable. |
| Frontend ORDELO_WEB_SITE_URL | `https://restaurant.ordelo.app` if that is the chosen public storefront host; it emits public town/menu sitemap entries. Leave absent until advertising is intended. |
| Frontend RIDER_AGENT_URL | Existing production fallback `https://rider-agent.ordelo.app`; preserve authorised MENU_API_URL and other existing variables. |

Amend Amplify's existing environment-copy regex with:
`NEXT_PUBLIC_WEB_ORDERING_MODE|ORDELO_WEB_KEY|WEB_COOKIE_SECRET|ORDELO_WEB_SITE_URL`.
These are names only; do not place keys in source or prefix them NEXT_PUBLIC.
The current local backend `.env.r3-local` and frontend `.env.local` are ignored
test configuration, not production secret delivery. Do not copy the entire local
frontend environment into production.

Frontend source edits (including robots/sitemap/origin helpers) were still
uncommitted at this inspection; backend HEAD was `a8f6442` with the user's R3
commit preceding it. Review and commit the intended files in both repositories;
the generated tsconfig.tsbuildinfo is not an implementation change. This report
does not confirm a remote push or deployment succeeded.

## Provider callbacks and open test jobs

- **Meta:** read-only verification shows business-account override and
  application both `https://rider-agent.ordelo.app/`. Owner restored this; no
  additional Meta action is needed on this evidence.
- **ELAS Stripe TEST Ordelo callback:** endpoint
  `we_1SIzY19Ci6shntN1CMsGX6xn` still targets
  `https://rider-agent-test.ordelo.app/payment-hooks/payment-complete`.
  Restore its recorded original
  `https://rider-agent.ordelo.app/payment-hooks/payment-complete` after dealing
  with payable test sessions and confirming deployed R3 handling. Keep enabled,
  test-only and subscribed to checkout.session.completed.
- **Payment-service callback:** endpoint `we_1SItMu9Ci6shntN1jw81tGYb` remains
  `https://hjgttc1wpj.execute-api.eu-west-2.amazonaws.com/prod/webhook/elai`.
  Do not repoint it to Ordelo; it owns payment persistence.
- **Unpaid GZBU-24:** Stripe TEST session
  `cs_test_a1OsJG79fwhGPe0nAqW1ch7cUTtJNSAO3YlLSKQ0MdLia3axPnWYb7wwvu`
  remained **open/unpaid** at 14:47, despite the 14:41 Ordelo cutoff. Expire it
  through the authorised test-provider workflow before closing the old local
  ingress, or retain correct R3 late-payment handling until it expires. The
  agent did not expire it.
- **Authorised RNRX-25:** Stripe TEST intent
  `pi_3UM6ZH9Ci6shntN10glZ8rYB` remains requires_capture (£27.90), with no queued
  release job. Explicitly reconcile/release this failed test order; moving app
  URLs or deploying the provider fix does not repair its missing stored record.
  The agent did not capture/cancel it or alter its status.
- **LXGM-26:** completed and test-captured; no outstanding delivery was observed.

Stripe restoration is independent of ordelo_config. No LIVE Stripe endpoint
was changed by this session, and no live destination is inferred from the test
account. After configuration, allow for the 60-second flags/frontend URL cache
and longer backend dashboard URL cache; restart affected processes if needed.
Stop local processes only after their remaining ingress/jobs are resolved.

## Release sequence

1. **Configuration done at 15:39 local:** before values saved, new web checkout
   paused and test-payment allowlist restored. Resolve the open/unpaid and
   authorised test jobs above; their last financial inspection was 14:47.
   Do not drop R3 tables.
2. Commit/review both repos, add production env-copy wiring, and provision the
   production backend key/frontend secrets. Deploy code while checkout remains
   paused. Verify normal WhatsApp ordering and deployed callback reachability.
3. Restore the remaining ELAS Stripe TEST callback and verify it with a fresh
   provider read; both app URLs and Meta are already production. Finish local
   restoration and stop only this session's servers when appropriate.
4. Inspect/release the existing payment-service manual-collection fix and run a
   new paid test session; verify persistence, capture and one receipt. Complete
   the remaining R3 gates. Existing sessions need their own reconciliation.
5. Enable the configured/verified price audit and change only
   WEB_ORDERING_ENABLED_REST_REFS from empty to `ELAS` for the first public
   restaurant. Keep the late guard/inbox/order RPC/notifier enabled. The web
   production frontend must be rebuilt with mode `live` and its server env.

Rolling back **new checkout** uses the empty web allowlist; keep tracking,
in-flight fulfilment and financial reconciliation available.

## Server shutdown

On the owner's request, the session-owned Ordelo server/reloader on port 3100
and frontend server/launchers on port 3000 were stopped. At **15:42
Europe/London (14:42 UTC)**, both ports had no listeners and all identified
session-owned processes had exited. Ordelo logged completed application shutdown.
The existing Cloudflare tunnel remained running.

No Stripe destinations or financial test jobs were changed by shutdown. The
last verified ELAS Stripe TEST Ordelo destination was still the local test
hostname, so that destination is unavailable with Ordelo stopped. Its
production restoration and the outstanding test-session/authorisation cleanup
remain separate tasks; shutdown does not imply either was completed.
