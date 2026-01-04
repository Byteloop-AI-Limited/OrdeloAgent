# Edge Functions (Supabase/Deno)

This directory contains Deno-based edge functions used within the Ordelo ecosystem. These functions are designed to run in Supabase Edge Functions but can be tested and run locally using the Deno runtime.

## Existing Edge Functions

### 1. App Runner Manager (`edge_app_runner_manager.ts`)
Manages AWS App Runner services.
- **Endpoint Pattern**: `/{service}/{action}`
- **Supported Actions**: `pause`, `resume`
- **Mechanism**: Dynamically resolves the AWS ARN from environment variables based on the `{service}` name (e.g., `ORDELO_APP_RUNNER_SERVICE_ARN`).
- **Required Env Vars**:
  - `AWS_REGION`
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `{SERVICE}_APP_RUNNER_SERVICE_ARN`

### 2. OwnTracks Webhook (`edge_owntracks-webhook.ts`)
Ingests location data from OwnTracks.
- **Mechanism**: Receives a JSON payload and pushes it to the `owntracks` queue in PostgreSQL using `pgmq_public.send`.
- **Required Env Vars**:
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`

---

## Local Development & Execution

### 1. Install Deno
```bash
curl -fsSL https://deno.land/x/install/install.sh | sh
```

### 2. Configuration
Create a `.env` file in this directory with the required variables listed above.

### 3. Running Locally
Deno requires explicit permissions for network and environment access.

**Run App Runner Manager:**
```bash
deno run --allow-net --allow-env --env-file=.env edge_app_runner_manager.ts
```

**Run OwnTracks Webhook:**
```bash
deno run --allow-net --allow-env --env-file=.env edge_owntracks-webhook.ts
```

### 4. Testing
You can use the provided Python scripts to test these endpoints while they are running locally:
- `test_app_runner.py`
- `test_owntracks_webhook.py`
