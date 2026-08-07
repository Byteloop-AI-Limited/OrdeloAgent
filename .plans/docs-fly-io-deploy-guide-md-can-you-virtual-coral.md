# Plan: Supabase-triggered Fly.io Machine scheduling (cost-saving boot/shutdown)

## Context

The SFCS agent runs one always-on `shared-cpu-1x`/`1gb` Fly Machine in `lhr` (see
`docs/fly.io-deploy-guide.md`). It bills 24/7 compute even though the food-delivery
service is largely idle overnight. Fly bills no CPU/RAM while a Machine is `stopped`
or `suspended`, so stopping it for a nightly window (~6h) saves roughly 25% of the
Machine's compute cost (storage/volumes still bill).

We are **not** using GitHub Actions or pg_cron for the schedule — the trigger lives
**outside Postgres** and is the user's concern. Our job is to build the in-database
primitives it will call:

- a **`fly_config`** table holding the Fly API token, app name, and machine id, and
- a **`fly_post(app_name, action)`** function that issues the Fly Machines REST call
  (`start` / `stop` / `suspend`) using a stored, app-scoped token.

Plus a new **guide section** in `docs/fly.io-deploy-guide.md` documenting the whole
setup. Outcome: an external scheduler can `SELECT fly_post('sfcs-agent','stop')` at
night and `...'start'` in the morning, with the sensitive token kept server-side.

### Decisions locked with the user (via grill-me)

| Decision | Choice |
|---|---|
| `fly_config` shape | **Per-app row**, keyed by `app_name` (not a KV table) |
| `fly_post` actions | Validate against **`start` / `stop` / `suspend`** (action = endpoint path) |
| Machine target | **Single stored `machine_id`** per row (app is single-Machine) |
| Scheduler / timezone | **Out of scope** — external, non-Postgres. No pg_cron, no TZ logic |
| Token protection | Plaintext in `fly_config`, but **RLS deny-all + REVOKE + `SECURITY DEFINER`** function |
| Overnight traffic | **Best-effort** — leave `auto_start_machines = true`; no `fly.toml` change |

### Patterns reused (do not reinvent)

- `ordelo_datamodels/jobs_n_functions/ordelo_post.sql` — the sibling HTTP helper:
  config lookup → build URL → `http_post` → `RETURNS TABLE(status int, content text)`.
- `ordelo_datamodels/jobs_n_functions/job_awsrunner_switch.sql` — closest analogue:
  validates an action param, calls an external infra on/off API, `DROP` + `CREATE OR REPLACE`.
- `ordelo_datamodels/ordelo_config.sql` — the config-table template (column style, timestamptz defaults).

---

## Deliverable 1 — `ordelo_datamodels/fly_config.sql` (new file)

Per-app config table + Supabase API lockdown. Mirror `ordelo_config.sql`'s comment/column style.

```sql
-- Per-app Fly.io control config (token + target machine), keyed by app_name.
-- Holds a secret (api_token) that can stop/start production Machines, so it is
-- locked out of the PostgREST/anon API; only fly_post() (SECURITY DEFINER) reads it.
CREATE TABLE IF NOT EXISTS fly_config (
    app_name     VARCHAR(100) PRIMARY KEY,   -- = FLY_APP_NAME, e.g. 'sfcs-agent'
    api_token    TEXT NOT NULL,              -- = FLY_API_TOKEN (app-scoped deploy token)
    machine_id   TEXT NOT NULL,              -- = FLY_MACHINE_ID
    region       TEXT,                       -- optional, informational (e.g. 'lhr')
    description  TEXT,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    -- NOTE: updated_at is NOT auto-maintained (matches ordelo_config; set it by hand on UPDATE).
);

-- Lock down: no policies + RLS enabled => deny-all; then revoke table grants from API roles.
ALTER TABLE fly_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON fly_config FROM anon, authenticated;

-- One-time row insert (fill in real values; token from the fly tokens step in the guide):
-- INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
-- VALUES ('sfcs-agent', '<FLY_MACHINE_ID>', 'lhr', '<FLY_API_TOKEN>', 'nightly stop/start');
```

Place alongside `ordelo_config.sql` in `ordelo_datamodels/`.

---

## Deliverable 2 — `ordelo_datamodels/jobs_n_functions/fly_post.sql` (new file)

Sibling to `ordelo_post.sql`. Same return shape, but adds two things the repo has never
done: (a) an `Authorization: Bearer` header, via the extended `http((...)::http_request)`
form (`pgsql-http` — confirmed by the repo's synchronous `http_post`/`http_get`/`http_response`
usage, not `pg_net`); (b) `SECURITY DEFINER` so it can read the RLS-locked `fly_config`.

```sql
-- ============================================================
-- Helper: POST a lifecycle action to the Fly Machines REST API.
-- Reads the app-scoped token + machine id from fly_config (SECURITY DEFINER),
-- so callers never hold the token. Actions map 1:1 to the Fly endpoint path.
-- Usage: SELECT * FROM fly_post('sfcs-agent', 'stop');   -- start | stop | suspend
-- ============================================================
DROP FUNCTION IF EXISTS fly_post(text, text);
CREATE OR REPLACE FUNCTION fly_post(
    p_app_name text,
    p_action   text
)
RETURNS TABLE (status integer, content text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions   -- see VERIFY-1: http ext schema
AS $$
DECLARE
    v_token      text;
    v_machine_id text;
    v_url        text;
    resp         http_response;
BEGIN
    IF p_action NOT IN ('start', 'stop', 'suspend') THEN
        RAISE EXCEPTION 'Invalid action "%". Must be start | stop | suspend', p_action;
    END IF;

    SELECT api_token, machine_id
      INTO v_token, v_machine_id
      FROM fly_config
     WHERE app_name = p_app_name;

    IF v_token IS NULL OR v_machine_id IS NULL THEN
        RAISE EXCEPTION 'fly_config has no usable row for app "%"', p_app_name;
    END IF;

    v_url := 'https://api.machines.dev/v1/apps/' || p_app_name
             || '/machines/' || v_machine_id || '/' || p_action;

    -- No body / no content-type, mirroring the working `curl -X POST` (no -d).
    SELECT * INTO resp
      FROM http((
        'POST',
        v_url,
        ARRAY[http_header('Authorization', 'Bearer ' || v_token)],
        NULL,   -- content_type: none (empty body)
        NULL    -- content: none
      )::http_request);

    RETURN QUERY SELECT resp.status, resp.content::text;
END;
$$;

-- CRITICAL: a SECURITY DEFINER function in public is auto-exposed as a PostgREST RPC
-- and EXECUTE defaults to PUBLIC (anon/authenticated). Without this, anyone with the
-- anon key could stop prod, and the table RLS would NOT help (function reads as owner).
REVOKE EXECUTE ON FUNCTION fly_post(text, text) FROM public, anon, authenticated;
GRANT  EXECUTE ON FUNCTION fly_post(text, text) TO service_role;

-- Usage:
-- SELECT * FROM fly_post('sfcs-agent', 'stop');    -- nightly shutdown
-- SELECT * FROM fly_post('sfcs-agent', 'start');   -- morning boot
```

**Implementation must verify before shipping** (see Verification): the `http` extension's
schema, and that a no-body POST is accepted by Fly (fallback: `''`/`''` for content_type/content).

---

## Deliverable 3 — New section in `docs/fly.io-deploy-guide.md`

Insert a new section titled **"11. Scheduled shutdown to save costs (Supabase-triggered Fly REST)"**
after the current section 10 (Reference), or renumber so it lands before Reference — keep
Reference last. It should cover, concisely and in the doc's existing voice/table style:

1. **Why / savings** — no CPU/RAM billing while `stopped`/`suspended`; ~25% compute saving
   for a ~6h nightly stop; storage/volumes still bill; `stop` = cold boot on start. One line
   on `stop` vs `suspend` (we default to `stop`; `suspend` resumes warmer but has eligibility limits).
2. **Create an app-scoped token** (least privilege, keep out of git):
   ```bash
   fly tokens create deploy -a sfcs-agent --name scheduled-machine-control --expiry 8760h
   fly machine list -a sfcs-agent    # to get FLY_MACHINE_ID
   ```
3. **`fly_config` table** — what it stores and the lockdown (RLS deny-all + REVOKE); the
   one-time `INSERT` with the token + machine id.
4. **`fly_post(app_name, action)`** — what it does, the `SECURITY DEFINER` + EXECUTE-grant
   note, and example calls (`SELECT * FROM fly_post('sfcs-agent','stop');`).
5. **How the external scheduler triggers it** (explicitly "your scheduler, outside Postgres"):
   - Direct SQL over a DB connection: `SELECT fly_post('sfcs-agent','stop');`
   - Supabase PostgREST RPC (must authenticate as **`service_role`**, not anon):
     ```bash
     curl -X POST "$SUPABASE_URL/rest/v1/rpc/fly_post" \
       -H "apikey: $SERVICE_ROLE_KEY" -H "Authorization: Bearer $SERVICE_ROLE_KEY" \
       -H "Content-Type: application/json" \
       -d '{"p_app_name":"sfcs-agent","p_action":"stop"}'
     ```
   - Note the source-conversation's GitHub Actions cron as one option for the external timer,
     but keep it clearly optional.
6. **`auto_start_machines` caveat (best-effort model we chose)** — `fly.toml` stays as-is
   (`auto_stop_machines="off"`, `auto_start_machines=true`); a nightly `stop` can be undone
   by an overnight WhatsApp webhook waking the Machine, so savings are partial. Document the
   **strict-outage variant** (`auto_start_machines=false` + `fly deploy`) as an alternative,
   with its trade-off: overnight messages aren't processed until the morning `start`.
7. **Security & verification** — token is app-scoped and stored only in the locked `fly_config`;
   confirm a stop/start with `fly machine status <id> -a sfcs-agent` and `fly logs`.

Cross-link: add one line under **§8 Day-2 operations** pointing to the new section.

---

## Security model (summary)

The token is powerful (can stop/start prod), so two independent locks, both required:

1. **Table**: `fly_config` has RLS enabled with no policies (deny-all) + `REVOKE ALL FROM anon, authenticated` → unreachable via the public PostgREST API.
2. **Function**: `fly_post` is `SECURITY DEFINER` (so it *can* read the table) but `EXECUTE` is revoked from `public/anon/authenticated` and granted only to `service_role` → only a trusted caller can invoke it. Without lock #2, lock #1 is moot.

---

## Verification

- **VERIFY-1 — `http` extension schema (gates whether `fly_post` runs at all).**
  ```sql
  SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'http';
  ```
  If `extensions` (typical on Supabase), keep `SET search_path = public, extensions`. If it
  resolves elsewhere, adjust the search_path or schema-qualify `http`/`http_header`/`http_request`.
  This also confirms `pgsql-http` (not `pg_net`) is installed.
- **VERIFY-2 — end-to-end, low-risk.** After creating the table + function and inserting the
  row, run `SELECT * FROM fly_post('sfcs-agent','stop');` and confirm `status` is `200`;
  cross-check `fly machine status <id> -a sfcs-agent` shows `stopped`; then
  `SELECT * FROM fly_post('sfcs-agent','start');` → `200` and Machine `started`; hit
  `curl --fail https://sfcs-agent.fly.dev/healthz`. If `stop` returns 400 on the empty body,
  switch the `http_request` content_type/content from `NULL,NULL` to `''`,`''`.
- **VERIFY-3 — access control.** Attempt the PostgREST RPC with the **anon** key → expect
  permission denied; with **service_role** → expect success. Confirms the EXECUTE grant.
- Use the `database-operations` skill (per repo conventions) to apply and exercise the SQL;
  do not hand-run raw psql outside it.

## Out of scope

- The scheduler / cron / timezone handling (external, non-Postgres — user's concern).
- Any `fly.toml` change (best-effort model keeps `auto_start_machines = true`).
- Multi-machine iteration, `suspend`-specific eligibility handling, Supabase Vault migration
  (documented as future options only).
