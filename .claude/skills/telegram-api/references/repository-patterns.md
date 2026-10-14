# Inspected FastAPI/aiogram repositories

Inspected 13 October 2026 using default-branch commit snapshots and the source files linked below. These are community examples, not aiogram 3.31.0 guarantees or production-readiness endorsements. Recheck dependency versions/licenses before adapting substantial code. The user's capability assessments are starting context; the observations here come from inspected files. No repository was installed or executed.

## hexfrost/fastapi-aiogram-template

[Repository](https://github.com/hexfrost/fastapi-aiogram-template), snapshot `c27faa4e150333a7601683a5dbd89de02a65f19c`.

- [App](https://github.com/hexfrost/fastapi-aiogram-template/blob/c27faa4e150333a7601683a5dbd89de02a65f19c/src/app.py): app and bot initialization separated; inspect lifecycle separation for small Ordelo integration.
- [Webhook route](https://github.com/hexfrost/fastapi-aiogram-template/blob/c27faa4e150333a7601683a5dbd89de02a65f19c/src/services/telegram/botfather/routing.py), [bot lifecycle/feed](https://github.com/hexfrost/fastapi-aiogram-template/blob/c27faa4e150333a7601683a5dbd89de02a65f19c/src/services/telegram/botfather/bot.py): minimal dispatcher handoff and session closure.
- [Dependencies](https://github.com/hexfrost/fastapi-aiogram-template/blob/c27faa4e150333a7601683a5dbd89de02a65f19c/pyproject.toml): broad aiogram range starting at 3.16, not pinned to 3.31.

Adapt the seam, adding secret-header verification, bot-bound update validation and Ordelo lifespan integration. The route lacks a secret check; the app uses old startup/shutdown decorators and permissive CORS. Do not copy the whole app configuration.

## mamashin/tg-bot-fastapi-aiogram

[Repository](https://github.com/mamashin/tg-bot-fastapi-aiogram), snapshot `e42f55f9bd26fc8c7f2fe3e01563d4eb199e0a43`.

- [Routes](https://github.com/mamashin/tg-bot-fastapi-aiogram/blob/e42f55f9bd26fc8c7f2fe3e01563d4eb199e0a43/routes.py): secret-header concept and dispatcher webhook handoff.
- [Bot](https://github.com/mamashin/tg-bot-fastapi-aiogram/blob/e42f55f9bd26fc8c7f2fe3e01563d4eb199e0a43/bot.py), [main](https://github.com/mamashin/tg-bot-fastapi-aiogram/blob/e42f55f9bd26fc8c7f2fe3e01563d4eb199e0a43/main.py), [Redis pool](https://github.com/mamashin/tg-bot-fastapi-aiogram/blob/e42f55f9bd26fc8c7f2fe3e01563d4eb199e0a43/redis_pool.py): configuration/lifespan and shared pool examples.

Correct `Bot(..., parse_mode=...)` to `DefaultBotProperties` for 3.31. Invalid secrets currently return an error body with HTTP success; use 403/401. Preserve pending updates rather than dropping them whenever the queue is nonempty. The shown lifespan does not demonstrate complete resource shutdown. Command-menu names should omit `/`. A Redis pool is not evidence of durable update ingestion.

## BushlanovDev/aiogram-fastapi-bot-template

[Repository](https://github.com/BushlanovDev/aiogram-fastapi-bot-template), snapshot `cdd432bf348168860e79798a5c6e00a45357534c`.

- [Main and registration](https://github.com/BushlanovDev/aiogram-fastapi-bot-template/blob/cdd432bf348168860e79798a5c6e00a45357534c/main.py): bot/defaults, dispatcher, command/FSM/callback registration and workflow-data injection.
- [Typed callback](https://github.com/BushlanovDev/aiogram-fastapi-bot-template/blob/cdd432bf348168860e79798a5c6e00a45357534c/bot/callbacks/callback.py), [keyboards](https://github.com/BushlanovDev/aiogram-fastapi-bot-template/blob/cdd432bf348168860e79798a5c6e00a45357534c/bot/keyboards/keyboards.py): useful small examples for rider actions and address Mini App launch.
- [Throttling](https://github.com/BushlanovDev/aiogram-fastapi-bot-template/blob/cdd432bf348168860e79798a5c6e00a45357534c/bot/middlewares/throttling.py): callback acknowledgment in throttled branches.

Retain Ordelo LangGraph for delivery, using FSM only for input collection. Correct missing webhook secret verification, unconditional update dropping, swallowed processing exceptions and absent explicit bot-session closure. In-memory FSM/throttling does not coordinate multiple workers or survive restart. The notification helper's message access needs inaccessible-message guards.

## MrConsoleka/aiogram-bot-template

[Repository](https://github.com/MrConsoleka/aiogram-bot-template), snapshot `7e98323bdc4095e3896a46afd522c5f9d05a3d4c` (branch `master`).

- [Server](https://github.com/MrConsoleka/aiogram-bot-template/blob/7e98323bdc4095e3896a46afd522c5f9d05a3d4c/source/factory/server.py): factory/lifespan, secret comparison and container handoff.
- [Dispatcher](https://github.com/MrConsoleka/aiogram-bot-template/blob/7e98323bdc4095e3896a46afd522c5f9d05a3d4c/source/factory/dispatcher.py): Redis FSM keys including bot ID, router/middleware/dialog setup.
- [Telegram error handler](https://github.com/MrConsoleka/aiogram-bot-template/blob/7e98323bdc4095e3896a46afd522c5f9d05a3d4c/source/telegram/handlers/errors/telegram.py), [auth middleware](https://github.com/MrConsoleka/aiogram-bot-template/blob/7e98323bdc4095e3896a46afd522c5f9d05a3d4c/source/telegram/middlewares/auth.py): error routing illustration; inspected auth middleware is a pass-through, not implemented access control.

Correct HTTP-success auth failure, `drop_pending_updates=True`, routine webhook deletion and unchecked callback message access. Do not inherit automatic schema creation, SQLAlchemy, Dishka or aiogram-dialog as migration requirements. Ordelo already owns persistence/checkpoint infrastructure.

## wakaree/aiogram_bot_template

[Repository](https://github.com/wakaree/aiogram_bot_template), snapshot `57c2b012ab56c1fda574f61bad5b1f209d131c38`.

- [FastAPI Telegram adapter](https://github.com/wakaree/aiogram_bot_template/blob/57c2b012ab56c1fda574f61bad5b1f209d131c38/app/presentation/fastapi/telegram.py): constant-time secret comparison, 401 rejection, tracked tasks and dispatch-result handling.
- [Lifespan service](https://github.com/wakaree/aiogram_bot_template/blob/57c2b012ab56c1fda574f61bad5b1f209d131c38/app/infrastructure/telegram/lifespan.py): explicit polling/webhook operations and configuration hashes.
- [Dispatcher provider](https://github.com/wakaree/aiogram_bot_template/blob/57c2b012ab56c1fda574f61bad5b1f209d131c38/app/providers/telegram/dispatcher.py): dependency scopes, Redis FSM and callback-answer middleware.

Useful reference for isolating transport from application logic. Task tracking is process-local, not durable acceptance; secret verification is optional if unconfigured. Callback middleware timing must suit long graph work. Avoid private dispatcher attributes and blindly trusting cached webhook registration across external changes. Adapt seams without importing its entire ORM/DI/flow architecture.

## Ralphcode-collab/aiogram3-bot-template

[Repository](https://github.com/Ralphcode-collab/aiogram3-bot-template), snapshot `8093b178355fbce64c646985d898755be695841d`.

- [Main](https://github.com/Ralphcode-collab/aiogram3-bot-template/blob/8093b178355fbce64c646985d898755be695841d/bot/main.py): webhook/polling separation, modern defaults, session cleanup and health route.
- [Middleware](https://github.com/Ralphcode-collab/aiogram3-bot-template/blob/8093b178355fbce64c646985d898755be695841d/bot/middlewares.py): inbound user rate limiter and ban guard.
- [Smoke tests](https://github.com/Ralphcode-collab/aiogram3-bot-template/blob/8093b178355fbce64c646985d898755be695841d/tests/test_smoke.py): offline wiring/rate limiter checks, not live Telegram/Postgres proof.

Replace token-in-URL webhook authentication with a dedicated path and secret header. Silent middleware rejection can leave callback spinners; acknowledge denied/throttled queries. Per-process rate buckets are not distributed outbound flood control. Ban lookup currently fails open on database errors; decide access policy for Ordelo admin/rider actions deliberately. Polling startup differs from FastAPI lifespan; do not assume database init runs in both modes.

## Choosing a pattern for Ordelo

Use hexfrost for the smallest handoff, BushlanovDev for callbacks/keyboards/registration, and wakaree for a richer transport adapter. Consult mamashin for configuration/header examples, MrConsoleka for scoped dependencies/storage keys, and Ralphcode for middleware/offline checks. This is a pattern selection from inspected files, not a ranking of full application quality.

Resolve conflicts with official aiogram 3.31.0 docs and current Ordelo code. For changes, prove domain authorization/idempotency, account linkage, webhook rejection and resource ownership. None of these source inspections establishes deployed service connectivity or live migration parity.
