# Configuration profiles and restoration

The table is `public.ordelo_config`, with `config_key`, `config_value`,
`description`, `created_at` and `updated_at`; there is no `rest_ref` column.
The scripts upsert by the existing unique `config_key` and preserve descriptions
on existing rows. They require no new tables or migrations.

## SQL files

- [production-restore.sql](production-restore.sql): restore the documented
  production routing and the production **before R1b rollout** profile.
- [test-enable.sql](test-enable.sql): recreate the successful ELAS/BNAT local
  R1b/R2 profile. Narrow both allowlists for a single-restaurant test if requested.
- [inspect-order.sql](inspect-order.sql): read-only checks for one full order
  number, resolving the payment service's short ID automatically.

These are manual, transactional SQL-editor files. Merely preparing them does not
apply them. Run/export the initial SELECT separately before running a profile, then
verify the after results. On a future test, restore its recorded before values;
an established production pilot must not be disabled just because this older
pre-rollout profile says false.

| Key | Production before R1b rollout | Successful local ELAS/BNAT profile |
| --- | --- | --- |
| `ORDELO_APP_URL` | `https://rider-agent.ordelo.app` | `https://rider-agent-test.ordelo.app` |
| `RESTAURANT_MENU_APP_URL` | `https://restaurant.ordelo.app` | `https://restaurant-test.ordelo.app` |
| `PAYMENT_INBOX_ENABLED` | `true` | `true` |
| `ORDER_CREATE_RPC_ENABLED` | `true` | `true` |
| `ENABLE_PAYMENT_TEST_ROUTES` | `false` | `false` |
| `CUSTOMER_NOTIFIER_ENABLED` | `false` | `true` |
| `CUSTOMER_NOTIFIER_REST_REFS` | `BNAT` | `ELAS,BNAT` |
| `TEST_PAYMENT_REST_REFS` | `BNAT` | `BNAT,ELAS` |

The first two URLs come from the local runbook. R1a true and BNAT-only test-payment
eligibility are the plan's 2026-10-01 production baseline. Notifier false is the
predeployment choice for the locally implemented R1b release, not a claim that
every future production environment must have the notifier disabled. A BNAT
pilot is a separate rollout: after the deployed code is verified, explicitly
enable the notifier with `CUSTOMER_NOTIFIER_REST_REFS=BNAT`.

An empty/missing notifier allowlist means **all restaurants** when the flag is
on. Do not use an empty string to mean disabled; use the flag itself. Test-payment
eligibility needs `test_payment:true` as well; the URL flag alone does not force
Stripe test mode. For WhatsApp the overwatch rule also applies.

## Settings outside these eight keys

Current source and live reads on 2026-10-02 showed BNAT, ELAS and SFCS already
using `https://bnat-agent.fly.dev/`, `https://elas-agg.ordelo.app` and
`https://sfcs-agent.fly.dev`. Those restaurant-agent URLs were not changed by
R2 and are not rewritten by these scripts. Existing switch files disagree on
some restaurant destinations; do not replace a working URL by guessing a hostname.

`WREN_APP_URL=https://wren-agg-test.ordelo.app` predates this run (its recorded
update is in 2025). No verified production replacement was established here.
The production script reads it back and leaves it unchanged; it restores this
test's settings rather than claiming to migrate every restaurant to production.
For a requested WREN migration, establish its actual deployed endpoint first.

The global and ELAS delivery timeouts were already five minutes. R2 did not
change them. Keep existing timeouts, cron schedules, rider availability,
restaurant admins/addresses, overwatch list and `PAYMENT_INIT_RECONCILER_SINCE`
unchanged unless the requested test specifically requires and authorizes a
change. Record and restore their before values if they are changed.

## Frontend environment

In `restaurant-frontend/.env.local`, for the fixture town UI:

```dotenv
NEXT_PUBLIC_WEB_ORDERING_MODE=fixtures
RIDER_AGENT_URL=https://rider-agent-test.ordelo.app
```

The backend fallback is used only when the DB lookup fails. `MENU_API_URL` is
separate; read its current authorized value rather than inventing one. Restart
Next.js after environment changes. The town slug is from `config/restaurants.ts`;
the ELAS fixture town is `/town/salisbury`, not `/town/orpington`.

Before production web wiring is approved, keep the production web-ordering mode
disabled per `lib/web/mode.ts` (absent/`off` currently fails closed). Setting
`live` is not a substitute for implementing/accepting R3. Restore any frontend
environment changes to their recorded before values; never overwrite other env
entries or print secrets. Public Next.js flags may require a production rebuild.

## Meta and Stripe ingress are independent

Changing `ORDELO_APP_URL` does not move provider webhook registrations.

- Meta/WhatsApp callbacks must reach the intended Ordelo instance for rider
  acceptance and messages. Read the business phone's webhook configuration through
  the existing WA client; record its exact before values. Change it only within
  the user's approved scope and restore it after the test. The R2 run's Meta
  change was made by the user; no before snapshot was captured by this skill.
- For each restaurant Stripe account under test, inspect the TEST Ordelo endpoint
  and its subscribed events. It must deliver `checkout.session.completed` to
  the intended `/payment-hooks/payment-complete`. The payment-service endpoint
  must stay registered too: it persists the PI used by capture/cancel.
- Use the test key from the authorized AWS secret; verify `sk_test_` and
  `livemode=false`. Record endpoint ID, original URL, status and events without
  exposing the key or webhook signing secret. Never change a live endpoint as
  part of a Stripe test-mode check.
- A temporary approved URL change must be restored to the **exact original** URL
  and verified with a fresh GET; preserve status/events. Do not guess a
  production URL for another account from ELAS's example.

During the reference ELAS R2 run, test endpoint `we_1SIzY19Ci6shntN1CMsGX6xn`
was temporarily routed to `https://rider-agent-test.ordelo.app/payment-hooks/payment-complete`,
then restored to `https://rider-agent.ordelo.app/payment-hooks/payment-complete`.
The payment-service endpoint `we_1SItMu9Ci6shntN1jw81tGYb` was unchanged. These
are historical identifiers to re-check, not universal account defaults.

## Caches and closing the window

Flags/allowlists and the frontend Ordelo URL cache have a 60-second TTL.
Restaurant-base/dashboard URL lookups can cache for an hour; inspect current
`config/params.py` for reset routes. Resetting a helper in a separate Python
process does not clear the running server's memory. Restart affected local
processes or use their documented reset endpoint, and account for production
consumer expiry/restarts. Check restored routing before stopping local servers.

Record database restoration, frontend env restoration, Meta restoration, each
Stripe account restoration and remaining test jobs separately. A successful SQL
execution alone is not full production restoration. Preparing this skill and
its SQL does not authorize or perform a Git push/deployment.
