# Local setup and testing runbook

> Current test-order policy: new orders use Stripe test only with an exact `TEST3100` item. Test delivery offers go only to eligible overwatch riders. See [test-orders.md](test-orders.md) for the fixed payment environment and deployment cutover.

Run OrdeloAgent and restaurant-frontend locally, expose them through the existing Cloudflare Tunnel, and route shared services to these local instances during a maintenance window.

## Payment endpoint selection

Local versus deployed application routing is independent of Stripe mode. For every new web/WhatsApp order, only an exact `TEST3100` product name selects Wren: `ms_settings.stripe_url_test` → `wrenPayment`. Other new baskets use `ms_settings.stripe_url` → `payment`, including overwatch customers. Capture and cancellation reuse the stored mode. No browser toggle, restaurant list or test application hostname selects it. Keep the priced marker on the receipt; test delivery requires a normally eligible overwatch rider. See [the endpoint and lifecycle table](test-orders.md#retained-payment-and-wren-services).

## Projects and ports

| Project / service | Local address | Test hostname |
| --- | --- | --- |
| `/Users/basavaraj/bloop/OrdeloAgent` — rider FastAPI service | `http://localhost:3100` | `https://rider-agent-test.ordelo.app` |
| `/Users/basavaraj/bloop/restaurant-frontend` — Next.js frontend | `http://localhost:3000` | `https://restaurant-test.ordelo.app` |
| Separate restaurant/aggregator backend | `http://localhost:3101` | `https://rest-agent-test.ordelo.app`, `https://elas-agg-test.ordelo.app` |

**Port clarification:** `uv run watomation/fapp_ordelo_agent.py` starts OrdeloAgent on **3100**, as defined in that file's `__main__` block. Port **3101** belongs to the separate restaurant/aggregator service in the tunnel configuration; its startup is outside this two-project runbook.

## 1. Prepare the Python shell

Use **zsh**. Before running any Python script or Python-based command, change to its project root, activate its virtual environment, set `PYTHONPATH`, and load its `.env`. Repeat this in each new terminal; environment changes do not carry between terminals.

`envLoad` should already be available from `~/.zsh_functions`, preloaded by `~/.zshrc`. Check with:

```zsh
type envLoad
```

If unavailable, define it in the current shell using this function:

```zsh
envLoad() {
    local env_file="${1:-.env}"
    local line key value line_number=0

    if [[ ! -f "$env_file" ]]; then
        printf 'envLoad: environment file not found: %s\n' "$env_file" >&2
        return 1
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        line_number=$((line_number + 1))
        line=${line%$'\r'}
        [[ -z "${line//[[:space:]]/}" || "$line" == \#* || "$line" == [[:space:]]#* ]] && continue
        [[ "$line" == export[[:space:]]* ]] && line=${line#export }

        if [[ "$line" != *=* ]]; then
            printf 'envLoad: invalid entry at %s:%s (expected KEY=VALUE)\n' "$env_file" "$line_number" >&2
            return 1
        fi

        key=${line%%=*}
        value=${line#*=}
        if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            printf 'envLoad: invalid variable name at %s:%s\n' "$env_file" "$line_number" >&2
            return 1
        fi

        if [[ ${#value} -ge 2 && "$value" == \"*\" ]]; then
            value=${value:1:${#value}-2}
        elif [[ ${#value} -ge 2 && "$value" == \'*\' ]]; then
            value=${value:1:${#value}-2}
        fi

        export "$key=$value"
    done < "$env_file"
}
```

Then prepare the OrdeloAgent terminal:

```zsh
cd /Users/basavaraj/bloop/OrdeloAgent

if [[ -d "venv" ]]; then
    source venv/bin/activate
elif [[ -d ".venv" ]]; then
    source .venv/bin/activate
else
    echo "No virtual env found"
fi

export PYTHONPATH="$PWD"
[[ -f ".env" ]] && envLoad
```

If the block prints `No virtual env found`, stop before running Python. For a fresh checkout, create the environment with `uv venv .venv --python 3.11` (the project requires Python 3.11 or newer), then repeat the preparation block. Install dependencies after activation and environment loading:

```zsh
uv sync --active
```

The activation block deliberately prefers `venv` over `.venv`. UV normally uses the project's `.venv`; when using `venv`, pass `--active` to UV so dependency installation and execution use the activated environment.

The local `.env` supplies the AWS settings used to retrieve application secrets from AWS Secrets Manager:

- `AWS_SETTINGS_KEY_ID`
- `AWS_SETTINGS_ACCESS_KEY`
- `AWS_SETTINGS_REGION`
- `AWS_SETTINGS_SECRET_NAME`

Loading `.env` prepares the process environment; application imports retrieve the application secrets. Use the existing authorized credentials and database configuration. Keep secret values out of documentation and terminal output. `envLoad` preserves spaces and strips matching surrounding quotes; use one `KEY=VALUE` entry per line and separate comment lines.

## 2. Start OrdeloAgent — terminal A

After completing section 1 in this terminal:

```zsh
uv run watomation/fapp_ordelo_agent.py
```

If the activated environment is `venv` rather than `.venv`, use:

```zsh
uv run --active watomation/fapp_ordelo_agent.py
```

Leave the process running. It starts Uvicorn with reload enabled on `0.0.0.0:3100`. Open `http://localhost:3100/docs` to check that FastAPI is serving.

## 3. Start restaurant-frontend — terminal B

```zsh
cd /Users/basavaraj/bloop/restaurant-frontend
# On first setup, or when dependencies change:
npm ci

npm run dev
```

Leave the process running on **3000**. If Next.js selects another port because 3000 is occupied, resolve the conflict and restart: the tunnel still forwards to 3000.

Configure the project's existing `.env.local` with its authorized values. Next.js loads it automatically. Current code uses:

- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SECRET_KEY` (server only)
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `RIDER_AGENT_URL` (fallback when the `ORDELO_APP_URL` database lookup fails)
- `MENU_API_URL` (menu upstream URL)

For local testing, set the fallback `RIDER_AGENT_URL=https://rider-agent-test.ordelo.app`. A successful database lookup takes precedence over this fallback. `MENU_API_URL` is configured separately; the two SQL updates below do not switch it. Restart Next.js after changing environment files.

Open `http://localhost:3000/restaurant/elas` or the restaurant under test.

## 4. Expose the services — terminal C

The existing `~/.cloudflared/config.yml` contains these ingress mappings:

```yaml
ingress:
  - hostname: rest-agent-test.ordelo.app
    service: http://localhost:3101
  - hostname: elas-agg-test.ordelo.app
    service: http://localhost:3101
  - hostname: rider-agent-test.ordelo.app
    service: http://localhost:3100
  - hostname: restaurant-test.ordelo.app
    service: http://localhost:3000
```

This is the relevant excerpt, not a replacement configuration. Preserve the existing tunnel identity, credentials, other ingress entries, and final catch-all rule.

If the configured tunnel is already running, reuse it. Otherwise, with the existing tunnel credentials available:

```zsh
cloudflared tunnel --config "$HOME/.cloudflared/config.yml" ingress validate
cloudflared tunnel --config "$HOME/.cloudflared/config.yml" run
```

The `run` command uses the tunnel defined in the configuration. Keep it running and check:

- `https://rider-agent-test.ordelo.app/docs`
- `https://restaurant-test.ordelo.app/restaurant/elas`

These checks confirm reachability. Exercise the actual menu/API flow to verify service-to-service routing.

## 5. Switch shared routing to local testing

`ordelo_config.config_key` identifies each service URL. Both local and production consumers reading the same database see these shared values. **Switch during the maintenance window:** production consumers will also route to the test hostnames while these values are set, which is the accepted operating model for this workflow.

In the SQL editor for the database used by these services, first record the current values. Expect one row for each key; resolve missing or duplicate rows before applying updates:

```sql
SELECT config_key, config_value
FROM ordelo_config
WHERE config_key IN ('ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL');
```

Once both local servers and the tunnel are reachable, apply:

```sql
BEGIN;

UPDATE ordelo_config
SET config_value = 'https://rider-agent-test.ordelo.app'
WHERE config_key = 'ORDELO_APP_URL';

UPDATE ordelo_config
SET config_value = 'https://restaurant-test.ordelo.app'
WHERE config_key = 'RESTAURANT_MENU_APP_URL';

COMMIT;
```

Repeat the SELECT to confirm both values.

| Key | Consumer / purpose | Test value | Production value |
| --- | --- | --- | --- |
| `ORDELO_APP_URL` | Frontend backend calls via `lib/config.ts` | `https://rider-agent-test.ordelo.app` | `https://rider-agent.ordelo.app` |
| `RESTAURANT_MENU_APP_URL` | OrdeloAgent dashboard links via `config/params.py` | `https://restaurant-test.ordelo.app` | `https://restaurant.ordelo.app` |

**Cache timing:** the database update commits immediately, but consumers may retain old URLs. The frontend caches `ORDELO_APP_URL` for **60 seconds**; OrdeloAgent caches dashboard URLs for **one hour**. Restart the affected local processes to use fresh values immediately. Production consumers can retain their cached values too; allow the relevant expiry or restart affected production processes through their established operating procedure. Running a cache-reset function in a separate Python process does not clear a running server's memory.

Restaurant-specific backend URLs such as `ELAS_APP_URL` are separate lookups in `config/params.py` (also cached for one hour). These two updates do not change the backend served on 3101, restaurant-specific routes, or external webhook registrations.

## 6. Verify the local flow

1. Confirm both SQL values point to the test hostnames.
2. Restart local processes after switching, keeping their prepared environment intact.
3. Open the frontend through `restaurant-test.ordelo.app` and load the restaurant menu.
4. Exercise the intended API flow and check both terminal logs: calls to OrdeloAgent should reach the local process on 3100. Frontend config logs show the fetched or cached `ORDELO_APP_URL`.
5. Verify any generated dashboard links use `restaurant-test.ordelo.app`.

Menu rendering alone does not prove backend routing; a menu can come from the separate `MENU_API_URL` upstream.

## 7. Restore production before ending the maintenance window

Apply the normal production values:

```sql
BEGIN;

UPDATE ordelo_config
SET config_value = 'https://rider-agent.ordelo.app'
WHERE config_key = 'ORDELO_APP_URL';

UPDATE ordelo_config
SET config_value = 'https://restaurant.ordelo.app'
WHERE config_key = 'RESTAURANT_MENU_APP_URL';

COMMIT;
```

Repeat the SELECT from section 5. If the recorded pre-test values differed from these standard production values, reconcile that difference before ending maintenance.

Account for the same cache expiry/restart behavior on restoration. Verify production frontend calls and dashboard links use production URLs before stopping local services; otherwise cached consumers may still call the local tunnel. Then stop the local servers with `Ctrl+C`. Stop the tunnel only if you started it for this session and its other mappings are no longer needed.

## Troubleshooting

| Symptom | Check / action |
| --- | --- |
| `envLoad` unavailable | Use zsh; check `.zshrc` loads `.zsh_functions`, or paste the fallback function above. |
| `No virtual env found` | Create the environment, then repeat activation, `PYTHONPATH`, and `.env` loading before Python commands. |
| Missing imports | After shell preparation, run `uv sync --active`; confirm UV is using the activated environment. |
| AWS secret retrieval fails | Check required variable names are set, credentials are valid, and Secrets Manager is reachable. |
| Tunnel returns an origin connection error | Confirm the corresponding local server is running on the mapped port. |
| Frontend uses the wrong backend | Check the shared database value, 60-second cache, server logs, and `RIDER_AGENT_URL` fallback. |
| Dashboard links still use an old hostname | Allow the one-hour cache to expire or restart the affected OrdeloAgent process. |
| Menu fetch fails | Check `MENU_API_URL` and its upstream independently of `ORDELO_APP_URL`. |

Source references: [`fapp_ordelo_agent.py`](../watomation/fapp_ordelo_agent.py), [`config/params.py`](../config/params.py), and the sibling frontend's `package.json`, `lib/config.ts`, `lib/supabase.ts`, and `app/api/menu/route.ts`. Tunnel mappings were checked against the local Cloudflare configuration when this guide was written.

## Reusable order-testing skill and configuration SQL

Invoke `$ordelo-local-automatic-orders` for browser/Swagger order tests with
database and Stripe test evidence. The repository source is
[Ordelo Local Automatic Orders](../.claude/skills/ordelo-local-automatic-orders/SKILL.md).
Its [configuration guide](../.claude/skills/ordelo-local-automatic-orders/references/configuration.md)
explains the flags and the separate frontend, Meta and Stripe restoration steps.

- [Restore production routing before R1b rollout](../.claude/skills/ordelo-local-automatic-orders/references/production-restore.sql)
- [Enable local ELAS/BNAT R1b/R2 testing](../.claude/skills/ordelo-local-automatic-orders/references/test-enable.sql)
- [Inspect one order and its notification/payment records](../.claude/skills/ordelo-local-automatic-orders/references/inspect-order.sql)

These profiles retain deployed R1a flags. The production profile disables the
local R1b pilot pending an approved deployment/rollout; future tests should
restore their own before snapshot if production settings have advanced.
