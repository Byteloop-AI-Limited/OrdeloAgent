# Fly.io Deployment Guide — SFCS Agent

Practical runbook for deploying this FastAPI app (the ELAI WhatsApp agent) to Fly.io.

> ⚠️ **Status check (verified 2026-09-03): two prerequisites this guide assumes are
> not present in the OrdeloAgent repo.**
>
> - **There is no `fly.toml` in this repo.** Sections below that say the repo
>   "already ships a `fly.toml`" (§2, §3) are not true here — you must author one
>   before `fly deploy` will work. Treat §3 as a specification for the file to
>   create, not a description of an existing one.
> - **There is no `/healthz` route.** `watomation/fapp_ordelo_agent.py` exposes
>   `/details`, `/restaurant-details/{rest_ref}`, `/internal/cache/reset`,
>   `/threads`, `/echo`, `/debug-state` and `/debug-state-by-thread` — no liveness
>   endpoint. A `[[http_service.checks]]` block pointing at `/healthz` will fail
>   its health check until such a route is added.
>
> `Dockerfile`, `start.sh`, `gunicorn_conf.py`, `utils/aws_setting.py`,
> `ordelo_datamodels/fly_config.sql` and
> `ordelo_datamodels/jobs_n_functions/fly_post.sql` **do** exist as described.
> Note also that this runbook is written for an app named `sfcs-agent` / "the ELAI
> WhatsApp agent"; adapt the app name and the `AWS_SETTINGS_SECRET_NAME` value
> before using it for a different deployment.

**Target shape** (to be encoded in a `fly.toml` you create — see §3): one always-on `shared-cpu-1x` / `1gb` Machine in London (`lhr`), one Gunicorn worker, Dockerfile-based build, app listens on port **8080**, health check at **`/healthz`** (route not yet implemented, see the note above). Application state stays in the external Supabase/Postgres — no Fly volume.

---

## 0. TL;DR (first deploy)

```bash
# 1. Install + log in (connects the CLI to your Fly account)
brew install flyctl
fly auth login

# 2. Create the app and link this repo to it (no build yet)
fly apps create sfcs-agent            # pick a globally-unique name
#   -> then set  app = "sfcs-agent"   in fly.toml

# 3. Set the AWS bootstrap secrets — import raw bytes from .env (no paste/quoting pitfalls)
#    (overrides the wrong AWS_SETTINGS_SECRET_NAME that .env ships)
{ grep -E '^AWS_SETTINGS_(KEY_ID|ACCESS_KEY|REGION)=' .env; \
  echo 'AWS_SETTINGS_SECRET_NAME=elai-agent-env'; } | tr -d '\r' | fly secrets import
#    -> this also triggers the deploy, so you can skip step 4's `fly deploy` on the first run

# 4. Validate + deploy a single Machine (remote build — no local Docker needed)
fly config validate
fly deploy --ha=false

# 5. Enforce exactly one Machine in lhr and verify
fly scale count 1 --region lhr
fly status && fly scale show && fly logs
curl --fail https://sfcs-agent.fly.dev/healthz     # -> {"status":"ok"}
```

> ⚠️ **`AWS_SETTINGS_SECRET_NAME` must be `elai-agent-env`** — that is the AWS secret this app reads in production. Your local `.env` currently sets it to `ordelo-agent-env` (which was dead code before, because the old code hard-coded `elai-agent-env`). Do **not** copy the `.env` value into Fly. If you ever point it elsewhere, the app will boot with different/missing config or crash-loop on the new fail-fast check.

---

## 1. How your Fly.io account is connected

Fly is driven entirely by the `flyctl` CLI (the commands are `fly …`; `flyctl …` is the same binary).

### Install flyctl
```bash
# macOS
brew install flyctl
# or the universal installer
curl -L https://fly.io/install.sh | sh
```

### Authenticate (interactive / your laptop)
```bash
fly auth login       # opens a browser, you log in, the CLI stores a token
fly auth whoami      # prints the logged-in email — confirms you're connected
fly orgs list        # shows the organizations your account can deploy into
```

`fly auth login` writes an auth token to `~/.fly/config.yml`. Every subsequent `fly` command uses that token. There's nothing to "connect" per-repo beyond the `app = "…"` line in `fly.toml`, which ties this working copy to a named app that lives under one of your orgs.

### Authenticate (CI / non-interactive)
Use a token instead of a browser login:
```bash
fly tokens create deploy -x 999999h        # create a scoped deploy token (recommended)
# or, broader:
fly auth token                             # print your personal token
```
Then expose it to the CLI as an env var — no `fly auth login` needed:
```bash
export FLY_API_TOKEN='<token>'
fly deploy --ha=false
```
This is how you'd wire it into GitHub Actions (store the token as a repo secret, export `FLY_API_TOKEN`).

### Where things live
- **Account/org** — created at fly.io; billing and members live here.
- **App** — a named unit (`sfcs-agent`) inside an org. Globally unique name. Gets a default hostname `https://<app>.fly.dev`.
- **Machine(s)** — the Firecracker VMs that actually run your container. We run exactly one.
- **`fly.toml`** — the repo's deploy config; `app = "<name>"` is the link between this code and the app.

---

## 2. One-time app creation

You have two options. Because this repo **already ships a `fly.toml`**, prefer the explicit path so `fly launch` doesn't rewrite your config.

### Option A — create the app, keep our fly.toml (recommended)
```bash
fly apps create sfcs-agent --org <your-org>   # omit --org if you have only one
```
Then edit `fly.toml`:
```toml
app = "sfcs-agent"
```
That's it — `fly deploy` will use the existing `fly.toml` and `Dockerfile`.

### Option B — `fly launch`
`fly launch` scaffolds an app and can generate a `fly.toml`. Since we already have one, run it in a mode that won't clobber your settings, and skip the immediate deploy:
```bash
fly launch --no-deploy --ha=false --region lhr --copy-config --name sfcs-agent
```
- `--no-deploy` — create the app but don't build yet.
- `--ha=false` — don't create a second standby Machine.
- `--copy-config` — reuse the existing `fly.toml` instead of regenerating it.
- After it runs, re-check `fly.toml` against this repo's version (region `lhr`, `auto_stop_machines = "off"`, `kill_timeout = "300s"`, the `[[http_service.checks]]` block, and the `[[vm]]` size) and fix anything `launch` changed.

---

## 3. Understanding `fly.toml`

`fly.toml` is the deploy manifest Fly reads on every `fly deploy`. It lives in the repo root and is committed (it holds no secrets). Here's what each key in *this* app's config does and why it's set the way it is.

### Top level

| Key | Value | Meaning |
|-----|-------|---------|
| `app` | `"sfcs-agent"` | The Fly app this repo deploys to. Globally unique; also gives the default hostname `https://sfcs-agent.fly.dev`. This line is the link between the code and your Fly account/org. |
| `primary_region` | `"lhr"` | Default region for Machines — London. New Machines land here unless told otherwise. |
| `kill_signal` | `"SIGTERM"` | Signal Fly sends to begin a graceful shutdown (on deploy, restart, or stop). Gunicorn/Uvicorn treat SIGTERM as "drain and exit". |
| `kill_timeout` | `"300s"` | How long Fly waits after `kill_signal` before force-killing — Fly's max, 5 minutes. This is the drain window for in-flight background tasks, deliberately paired with Gunicorn's `graceful_timeout = 290` (just under it) so Gunicorn exits cleanly first. |

### `[build]`

| Key | Value | Meaning |
|-----|-------|---------|
| `dockerfile` | `"Dockerfile"` | Build the image from our `Dockerfile` (rather than a buildpack or a prebuilt image). Applies to both remote and local builds. |

### `[env]` — non-secret runtime environment

These become plain environment variables in the container. **They are not secrets** (secrets go through `fly secrets`). Most are read by `gunicorn_conf.py` and `start.sh`, so `fly.toml` is the single place to tune the server without touching code.

| Key | Value | Meaning |
|-----|-------|---------|
| `PORT` | `"8080"` | Port the app binds inside the container. Must match `internal_port` below and `EXPOSE` in the Dockerfile. |
| `HOST` | `"0.0.0.0"` | Bind on all interfaces so Fly's proxy can reach it. |
| `WEB_CONCURRENCY` | `"1"` | Number of Gunicorn workers. `gunicorn_conf.py` **hard-refuses** any value other than 1 for this single-Machine design. |
| `WORKER_CLASS` | `"uvicorn_worker.UvicornWorker"` | The async worker class (from the maintained `uvicorn-worker` package). |
| `GRACEFUL_TIMEOUT` | `"290"` | Gunicorn's graceful-shutdown budget (seconds) — just under `kill_timeout` so it wins the race. |
| `TIMEOUT` | `"600"` | Gunicorn worker-silence timeout. Generous because LLM/graph calls can be slow. **Not** an HTTP request timeout on the Fly edge. |
| `KEEP_ALIVE` | `"5"` | Seconds to hold idle keep-alive connections open. |
| `LOG_LEVEL` | `"info"` | Log verbosity for both Gunicorn and the app's loguru sink. |

### `[http_service]` — how Fly's proxy routes traffic

| Key | Value | Meaning |
|-----|-------|---------|
| `internal_port` | `8080` | Port Fly's proxy forwards to inside the Machine. **Must equal `PORT`.** |
| `force_https` | `true` | Redirect plain HTTP to HTTPS at the edge. |
| `auto_stop_machines` | `"off"` | Never auto-stop the Machine when idle. This is what keeps the app **always-on** so in-process background tasks can finish. |
| `auto_start_machines` | `true` | Start a stopped Machine on incoming traffic (a safety net; with auto-stop off it rarely triggers). |

### `[[http_service.checks]]` — HTTP health check

Fly polls this endpoint to decide whether the Machine is healthy and whether a new release is good; it gates traffic during deploys.

| Key | Value | Meaning |
|-----|-------|---------|
| `interval` | `"15s"` | Poll every 15 seconds. |
| `timeout` | `"3s"` | Fail the check if no response within 3 seconds. |
| `grace_period` | `"60s"` | Wait 60s after a Machine starts before checking — covers app import/startup time. |
| `method` / `path` | `GET /healthz` | Hit our lightweight liveness route, which returns `{"status":"ok"}` without touching the DB/AWS/WhatsApp/LLM. |

### `[[vm]]` — Machine size

`[[vm]]` is a table-array (note the double brackets) — one entry per Machine spec. We define exactly one.

| Key | Value | Meaning |
|-----|-------|---------|
| `size` | `"shared-cpu-1x"` | 1 shared vCPU — the smallest shared preset. |
| `memory` | `"1gb"` | 1 GB RAM. Bump later with `fly scale memory 2048` if monitoring shows pressure — no `fly.toml` edit strictly required. |

### How the pieces line up
- `PORT` (8080) = `internal_port` (8080) = Dockerfile `EXPOSE 8080` — all three must agree.
- `kill_timeout` (300s) > `GRACEFUL_TIMEOUT` (290) so Gunicorn drains before Fly force-kills.
- `[env]` values are consumed by `gunicorn_conf.py` / `start.sh`, so tuning the server means editing `fly.toml`, not code.
- `auto_stop_machines = "off"` + one `[[vm]]` + `fly scale count 1` = a single, always-on Machine.

Validate any change before deploying:
```bash
fly config validate
```

---

## 4. Ways to package & deploy

All methods use our `Dockerfile` (declared via `[build] dockerfile = "Dockerfile"` in `fly.toml`). Pick based on whether you want Fly to build for you or to build locally. **`.dockerignore` already excludes `.env`, so no secrets enter the build context in any method.**

### 3a. Remote build — **recommended default**
Fly uploads the build context to a remote builder and builds there. No local Docker required.
```bash
fly deploy --ha=false
# force remote explicitly if you like:
fly deploy --ha=false --remote-only
```
Best choice here because it needs no local Docker daemon and sidesteps the macOS `fork()`/Objective-C crash you hit running the prefork server locally (that's a macOS-only artifact; the Linux container is unaffected).

### 3b. Local build, then push
Build the image with your **local** Docker, push it to Fly's registry, and release it:
```bash
fly deploy --ha=false --local-only
```
Requires Docker Desktop running. The build itself works fine on macOS — only *running* the prefork server locally triggers the objc fork crash, which does not affect image builds or the Linux runtime.

### 3c. Build the image yourself, deploy a prebuilt image
Useful if you want full control of the build (or to reuse an image from CI):
```bash
fly auth docker                                   # configure docker to auth to registry.fly.io
docker build -t registry.fly.io/sfcs-agent:$(git rev-parse --short HEAD) .
docker push registry.fly.io/sfcs-agent:$(git rev-parse --short HEAD)
fly deploy --ha=false --image registry.fly.io/sfcs-agent:$(git rev-parse --short HEAD)
```
`fly deploy --image <ref>` skips building entirely and just releases the referenced image. The image can live in `registry.fly.io` or any registry Fly can pull from (private registries need their own auth configured).

### 3d. Build only (no release)
Produce/push the image without deploying — handy in CI to separate build from release:
```bash
fly deploy --build-only --push --remote-only
# later, release what was built:
fly deploy --image <ref-printed-above> --ha=false
```

### Deploy strategy (for updates, not the first deploy)
Since we run a **single** Machine, a rolling deploy briefly takes the app down while the new Machine replaces the old one. That's acceptable for this best-effort service. If you want the shortest interruption:
```bash
fly deploy --ha=false --strategy immediate
```
For zero-downtime you'd need a second Machine (out of scope for this single-Machine design).

---

## 5. Setting secrets

Two kinds of configuration reach the app:

| Kind | Where it goes | Example |
|------|---------------|---------|
| **Non-secret runtime config** | `[env]` in `fly.toml` (committed) | `PORT`, `WEB_CONCURRENCY`, `LOG_LEVEL` |
| **Secrets** | `fly secrets` (encrypted, never in git) | the four `AWS_SETTINGS_*` values |

This app only needs **four bootstrap secrets** on Fly. Everything else (Supabase, Stripe, WhatsApp tokens, LLM keys, …) is pulled at runtime from **AWS Secrets Manager** using these four.

### Method A — `fly secrets import` (recommended)

`import` reads `KEY=VALUE` lines from **stdin** and stores each value as raw bytes — the shell never parses them, so there's no way to mangle a long AWS key by mis-quoting or a partial paste. This is the reliable way to set secrets.

Because this repo already keeps the four bootstrap values in `.env`, feed them straight in — overriding only the secret name to the production one (`.env` ships the wrong `AWS_SETTINGS_SECRET_NAME`):

```bash
{ grep -E '^AWS_SETTINGS_(KEY_ID|ACCESS_KEY|REGION)=' .env; \
  echo 'AWS_SETTINGS_SECRET_NAME=elai-agent-env'; } | tr -d '\r' | fly secrets import
```

Or from a hand-written file of `KEY=VALUE` lines (never commit it):

```bash
fly secrets import < fly.secrets.env
```

### Method B — `fly secrets set` (quick, but easy to corrupt)

Here each value is a **shell argument**, so quoting matters (see below):

```bash
fly secrets set \
  AWS_SETTINGS_KEY_ID='AKIAxxxxxxxxxxxxxxxx' \
  AWS_SETTINGS_ACCESS_KEY='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY' \
  AWS_SETTINGS_REGION='eu-west-2' \
  AWS_SETTINGS_SECRET_NAME='elai-agent-env'
```

### Quoting the values (this is what silently breaks credentials)

- **Single-quote every value by default:** `AWS_SETTINGS_KEY_ID='...'`. Single quotes pass the value through literally — the shell interprets nothing inside.
- **Unquoted is fine only for plain letters/digits.** `AWS_SETTINGS_KEY_ID=F9090FAKIA123` works bare, but the moment a value contains a space, `$`, `` ` ``, `!`, `*`, `?`, `~`, `#`, `&`, `|`, `;`, `<`, `>`, `(`, `)` the shell mangles it. AWS **secret access keys** are 40-char base64 and can contain `+` and `/` (harmless), so they *usually* survive bare — but one stray space from a paste is all it takes.
- **Never use double quotes `"..."` for secrets** — they still expand `$VAR` and `` `cmd` ``.
- **The most common corruption isn't quoting at all — it's a truncated or space-padded paste.** That's the whole reason to prefer Method A: nothing is retyped.

### Notes
- Both `set` and `import` **trigger a new release/restart** by default so the Machine picks up the values. Add `--stage` to store them *without* deploying — but then they only apply on your next `fly deploy` (a staged-only change leaves the running Machine on the old values).
- Fly injects secrets as **environment variables** into the container at runtime. Our code reads `AWS_SETTINGS_*` via `utils/aws_setting.py`.
- The AWS secret itself stays in **`eu-west-2`** even though the Machine runs in `lhr` — `AWS_SETTINGS_REGION` points at the secret's region, not the Machine's.

### Manage them
```bash
fly secrets list           # names + digests only, never values
fly secrets unset SOME_KEY # remove one (also triggers a release)
```

### Troubleshooting: worker fails to boot on secret load

Check `fly logs`. The `RuntimeError` names the AWS error code, which tells you exactly what's wrong:

| Log shows | Meaning | Fix |
|-----------|---------|-----|
| `UnrecognizedClientException` / "security token included in the request is invalid" | The **credentials** stored in Fly are wrong (truncated/space-padded paste, or an inactive/incorrect key) — the secret *name* is fine | Re-set via Method A from `.env`, then redeploy |
| `AccessDeniedException` | Credentials are valid but the IAM key can't read that secret | Fix the IAM policy (see below) |
| `ResourceNotFoundException` | Wrong `AWS_SETTINGS_SECRET_NAME` | Set it to `elai-agent-env` |

A crash-loop on secret load leaves the Machine `stopped` with a failing health check. Starting it (`fly machine start <id>`) won't help until the secret is fixed — re-setting the secret (Method A) both fixes it and redeploys.

### IAM scope for the AWS key
The IAM principal behind `AWS_SETTINGS_KEY_ID` should be allowed to read **only** the one secret:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:GetSecretValue"],
    "Resource": "arn:aws:secretsmanager:eu-west-2:<account-id>:secret:elai-agent-env*"
  }]
}
```
Avoid `secretsmanager:*` or account-wide access.

---

## 6. Enforce a single Machine

Fly may create a standby Machine for HTTP apps. We want exactly one:
```bash
fly deploy --ha=false            # don't create a second Machine on deploy
fly scale count 1 --region lhr   # hard-set the count
fly scale show                   # must show 1 Machine in lhr
```
`min_machines_running` is intentionally **not** set — it has no effect while `auto_stop_machines = "off"`.

---

## 7. Verify the deployment

```bash
fly status          # one Machine, region lhr, state "started", health passing
fly scale show      # exactly one shared-cpu-1x / 1gb in lhr
fly checks list     # the /healthz check should be passing
fly logs            # tail live logs (structured JSON to stdout)
curl --fail https://<app>.fly.dev/healthz     # -> {"status":"ok"}
```

Confirm in the logs:
- `Application startup complete` (from the lifespan handler).
- No `.env` / secret values printed at startup.
- The AWS secret loaded (the app reached "startup complete" without a `RuntimeError`).
- Gunicorn reports **one** worker (`"workers": 1` in the `GUNICORN_CONF=` line).

Then **repoint the Meta/WhatsApp webhook** to `https://<app>.fly.dev/...` and smoke-test one real message plus one rider/payment background workflow.

---

## 8. Day-2 operations

```bash
# Ship an update (rebuild + release)
fly deploy --ha=false

# Watch logs / a specific Machine
fly logs
fly logs -i <machine-id>

# Shell into the running container
fly ssh console

# Inspect Machines
fly machine list
fly machine status <machine-id>

# Restart without redeploying
fly machine restart <machine-id>
```

### Scaling (if 1 GB proves tight — see monitoring triggers)
```bash
fly scale memory 2048     # bump to 2 GB
fly scale show
```
Do **not** add a second Gunicorn worker just because memory increased — the deployment is intentionally `WEB_CONCURRENCY=1` and `gunicorn_conf.py` refuses any other value. Test CPU/latency/DB connections first.

### Rollback
```bash
fly releases                                   # list releases + image refs
fly deploy --ha=false --image <previous-ref>   # redeploy a known-good image
```

### Scheduled stop/start (cost saving)
To stop the Machine overnight and start it in the morning from an external scheduler, see **§10 — Scheduled shutdown to save costs**.

---

## 9. Gotchas specific to this project

- **Secret name:** `AWS_SETTINGS_SECRET_NAME=elai-agent-env` on Fly. The repo `.env` says `ordelo-agent-env` — ignore that value for Fly; it was unused before the migration.
- **Port 8080, non-root:** the container listens on 8080 (unprivileged) and runs as the non-root `app` user. `fly.toml`'s `internal_port = 8080` must match.
- **No volume, logs to stdout:** logging is stdout-only JSON; there is no `file.log` and no Fly volume. `fly logs` is your log source.
- **Best-effort background tasks:** FastAPI `BackgroundTasks` continue after the HTTP response but are dropped on deploy/crash/OOM. `kill_timeout = "300s"` gives in-flight tasks up to ~5 min to finish during a normal deploy. This is the accepted reliability model — no durable queue.
- **macOS local run:** running the prefork Gunicorn server on a Mac crashes with an Objective-C `fork()` error and requires `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`. This is macOS-only and irrelevant to the Linux container. Prefer remote builds; don't try to reproduce production locally on macOS.

---

## 10. Scheduled shutdown to save costs (Supabase-triggered Fly REST)

This app is always-on (`auto_stop_machines = "off"`), so it bills compute 24/7 even though delivery traffic is thin overnight. Fly charges **no CPU/RAM** while a Machine is `stopped` or `suspended`, so a nightly shutdown window (~6 h) trims roughly **25%** of the Machine's compute cost. What you **keep** paying: root-filesystem storage (~$0.15/GB/month while stopped) plus any volumes/snapshots — those bill regardless of Machine state.

The **timing** (what fires at, say, 01:00 and 07:00) lives **outside Postgres** — a scheduler you own (an external cron, a Supabase-side timer, GitHub Actions, …). Postgres just provides the button it presses: a `fly_config` table holding the credentials and a `fly_post(app_name, action)` function that calls Fly's Machines REST API.

### `stop` vs `suspend`

Default to **`stop`** — simplest, no eligibility rules. It cold-boots on the next `start` (the ephemeral rootfs is reset; our state is external in Supabase, so that's fine). `suspend` resumes warmer (preserves memory) but has restrictions (no swap, no GPU, ≤ 2 GB RAM, no Machine schedule) and resume isn't guaranteed. Both stop compute billing. `fly_post` accepts either.

### 10a. Create an app-scoped token

Least privilege: a token that can only touch this app. Keep it out of git.
```bash
fly tokens create deploy -a sfcs-agent --name scheduled-machine-control --expiry 8760h
fly machine list -a sfcs-agent    # note the Machine ID (FLY_MACHINE_ID)
```

### 10b. `fly_config` table

`ordelo_datamodels/fly_config.sql` — one row per app, keyed by `app_name`, storing the token, machine id, and region. Because the token can stop/start prod, the table is **locked out of the public API**: RLS is enabled with no policies (deny-all) and grants are revoked from `anon`/`authenticated`. Only `fly_post` (SECURITY DEFINER) reads it.

Seed the row (values from 10a):
```sql
INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
VALUES ('sfcs-agent', '<FLY_MACHINE_ID>', 'lhr', '<FLY_API_TOKEN>', 'nightly stop/start');
```

### 10c. `fly_post(app_name, action)` function

`ordelo_datamodels/jobs_n_functions/fly_post.sql` — validates `action ∈ {start, stop, suspend}`, looks up the token + machine id, and `POST`s to `https://api.machines.dev/v1/apps/<app>/machines/<id>/<action>` with an `Authorization: Bearer` header. Returns `(status, content)`.

```sql
SELECT * FROM fly_post('sfcs-agent', 'stop');    -- nightly shutdown
SELECT * FROM fly_post('sfcs-agent', 'start');   -- morning boot
```
A successful call returns HTTP `200`.

> **Security:** `fly_post` is `SECURITY DEFINER`, so it is auto-exposed as a PostgREST RPC and — critically — its `EXECUTE` grant is revoked from `public`/`anon`/`authenticated` and granted only to `service_role`. Locking the *table* alone is not enough: a definer function reads the token as owner, so an open `EXECUTE` grant would let anyone holding the anon key stop prod.

### 10d. Trigger it from your (external) scheduler

Point your scheduler at the function twice a day. It must authenticate as **`service_role`** (never anon):

- **Direct SQL** (a DB connection / a job that runs SQL):
  ```sql
  SELECT fly_post('sfcs-agent', 'stop');   -- at your night time
  SELECT fly_post('sfcs-agent', 'start');  -- at your morning time
  ```
- **Supabase PostgREST RPC** (HTTP):
  ```bash
  curl -X POST "$SUPABASE_URL/rest/v1/rpc/fly_post" \
    -H "apikey: $SERVICE_ROLE_KEY" \
    -H "Authorization: Bearer $SERVICE_ROLE_KEY" \
    -H "Content-Type: application/json" \
    -d '{"p_app_name":"sfcs-agent","p_action":"stop"}'
  ```

> **Timezone:** whatever fires this runs on *your* scheduler's clock — Fly doesn't care what local time it is. Pick the UTC/local instants that map to your intended London window, minding BST/GMT if you want an exact local time year-round.

### 10e. Interaction with `auto_start_machines` (best-effort model)

`fly.toml` is left **unchanged** (`auto_stop_machines = "off"`, `auto_start_machines = true`). Consequence: after a nightly `stop`, the **first incoming WhatsApp webhook wakes the Machine again** (Fly auto-starts on traffic). The overnight message is still handled, but the savings are **partial/variable** — you only save during genuinely idle stretches. No message loss. This is the chosen trade-off.

**Strict-outage variant** (only if overnight traffic is ~zero): set `auto_start_machines = false` and `fly deploy`. The Machine then stays down for the whole window and savings are a guaranteed ~6 h/night — but inbound messages during the window are **not processed until the morning `start`** (Meta retries webhooks for a while, but delivery isn't guaranteed).

### 10f. Verify

```bash
fly machine status <machine-id> -a sfcs-agent   # after 'stop' -> stopped; after 'start' -> started
fly logs -a sfcs-agent
curl --fail https://sfcs-agent.fly.dev/healthz  # after 'start' -> {"status":"ok"}
```
From SQL, check the returned `status` is `200`. If `fly_post` errors on the HTTP call, confirm the `http` extension's schema matches the function's `search_path`:
```sql
SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'http';  -- expect: extensions
```

---

## 11. Reference

- App configuration: https://fly.io/docs/reference/configuration/
- Deploy / builders: https://fly.io/docs/launch/deploy/
- Secrets: https://fly.io/docs/apps/secrets/
- Health checks: https://fly.io/docs/reference/health-checks/
- Machine scaling & availability: https://fly.io/docs/apps/scale-count/ , https://fly.io/docs/apps/app-availability/
- Access tokens (CI): https://fly.io/docs/security/tokens/
- Machines REST API (start/stop/suspend endpoints): https://fly.io/docs/machines/api/
- Machine states & lifecycle: https://fly.io/docs/machines/overview/
- Pricing (compute vs. stopped-Machine storage): https://fly.io/docs/about/pricing/
