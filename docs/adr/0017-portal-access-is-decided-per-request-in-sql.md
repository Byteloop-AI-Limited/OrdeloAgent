# ADR 0017: Portal access is decided per request in SQL

## Status

Accepted 19 Nov 2026 (owner decisions of 18-19 Nov 2026). Built, applied to the live database and tested live on 19 Nov; the code is not deployed yet (`docs/to-do.md`). What the restaurant dashboard can change is [ADR 0018](0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md).

## Context

The rider portal, restaurant dashboard and system (sys-admin) dashboard were reached by WhatsApp magic links (`/login`, `/sysadmin`); on Telegram only `/manage` and the rider's `/my_jobs` existed. Each link path copied its own minting code, the restaurant and system links were consumed on GET (a chat link preview could use them up), and the frontend never re-checked overwatch or restaurant membership after sign-in.

## Decision

One verified identity per phone, with permissions derived on every request:

- **Identity.** A Telegram account proves its phone by sharing its own contact (`contact.user_id == from_user.id`); a WhatsApp sender is proved by Meta (`wa_id`). An overwatch phone may link to the restaurant bot even when it admins no restaurant (`t_admin_profile` result `ops_only`).
- **Permissions.** Restaurant rights come from `restaurant_master.admins` (`admin_roster`). System rights come from `is_overwatch()`, which reads `ordelo_config.overwatch_list` fresh every time. Alert channels and pauses never grant or remove portal access.
- **Issuance.** `ordelo/dashboard_links.py` is the one place that makes portal links. The SQL mint (`rest_admin_dashboard_mint`, `sys_admin_dashboard_mint`, `rider_dashboard_mint`) re-checks authority and stores the hashed token in the same transaction.
- **Activation and use.** A link opens a non-consuming page; the browser's same-origin POST consumes it. `admin_dashboard_touch` re-checks roster or overwatch membership on every protected request, and every restaurant-dashboard write passes the session id to SQL, which re-derives phone and restaurant (`rest_admin_session_actor`).
- **Revocation.** Moving a phone to another Telegram account, or unlinking it, revokes every rest_admin and sys_admin session and unused link of that phone, for all its restaurants and whichever channel issued them, in the same transaction. An open browser must request a fresh link on its next request. Sharing the contact again from the same account changes nothing. Rider sessions are not affected.
- **Entry points.**
  - The rider bot's `/my_jobs` gains a `/portal` alias.
  - The restaurant bot's `/manage` sends one link per restaurant on the admin's roster. An overwatch member also gets a **System dashboard** button, which mints its link only when tapped and re-checks overwatch then.
  - `/sysadmin` sends the system dashboard link directly.
  - WhatsApp `/login` sends one link per restaurant (formerly only the first), and `/sysadmin` stays.
  - `/manage` keeps working if the overwatch lookup fails.
- **Alias restaurants.** A restaurant that shares another's orders and settings (`config.params._REST_REF_ALIAS_MAP`, CHKS → ELAS) gets no separate link when the person admins the canonical restaurant; a person on the alias's list only keeps an alias link.
- **Menus are guidance only.** `/sysadmin` appears only in overwatch members' private chats, through a per-chat command menu (`BotCommandScopeChat`); for an overwatch member who admins no restaurant, the menu shows only `/start`, `/sysadmin`, `/help`, `/whoami`. Menus are reconciled on `/start`, linking, `/help`, `/whoami`, `/manage` and `/sysadmin`. Every handler re-checks; a stale menu entry or an old button gets "operations only".

## Consequences

- Removing someone from a restaurant's admins list or from overwatch takes effect on their next click, not after their 4-hour session.
- Dashboard links survive Telegram and WhatsApp link previews.
- The restaurant dashboard can safely offer writes (acceptance policy, closed dates, alerts, hidden items), each audited in `restaurant_settings_audit` with sys-admin undo.

## Considered and rejected

- A "System dashboard" permission column on the admin record: duplicates the overwatch list and drifts from it.
- Frontend-only checks of membership: the payout backend already had to re-check, and other pages did not.
- Activating links on GET: link previews used them up.

## Implementation and verification (19 Nov 2026)

- **SQL** (`admin_dashboard/auth_sessions.sql`, `restaurant_admin/admin_roster.sql`; applied with `migrations/telegram_portals_p1.sql`): `is_overwatch`, `portal_access`, `rest_admin_dashboard_mint`, `sys_admin_dashboard_mint`, `admin_dashboard_activate`, `admin_dashboard_touch`, `rest_admin_session_actor`, `auth_sessions_revoke_phone`.
- **Python:** `ordelo/dashboard_links.py` is the only issuer. The bots use `channels/telegram/rest_admin/{manage,sysadmin,menu}.py` and `channels/telegram/rider/dashboard.py`; WhatsApp uses `watomation/on_message_wa_handler.py`.
- **Frontend:** `lib/dashboard-activation.ts` handles every portal's activation; `lib/admin-session-rpc.ts` is used by the restaurant and system session libraries.
- **Tests:**
  - `tests/sql/test_admin_dashboard_sql.py`
  - `tests/ordelo/test_dashboard_links.py`
  - `tests/channels/telegram/test_rest_admin_manage.py`
  - `tests/channels/telegram/test_rider_dashboard.py`
  - `tests/watomation/test_wa_dashboard_commands.py`
  - frontend `lib/dashboard-activation.test.ts`
  - frontend `lib/admin-session-rpc.test.ts`
- **Verified live on 19 Nov, through the local services and the production bots** (the verification loop is in `agents.md`):
  - `/manage`, the System dashboard button, `/sysadmin`, the scoped menu, `/portal` and `/my_jobs`.
  - Links survive GET, HEAD and a foreign-origin POST, and are refused on a second open.
  - The owner confirmed Telegram taps and access removal.
  - Still to test: WhatsApp `/login` and `/sysadmin` (`docs/to-do.md`).

