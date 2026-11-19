# Telegram portal links and the restaurant operations dashboard

Implementation handoff · 18 November 2026 · **plan only, nothing built**. Both repos are on `docs/glossary-updaet`. OrdeloAgent
baseline is `7cd530c`, restaurant-frontend baseline is `35b5065`. Links resolve from this file (`../` = OrdeloAgent,
`../../restaurant-frontend/` = frontend, `../../restaurant-agents/` = restaurant-agents). Symbols marked *(new)* are proposals.
Line numbers are from the baselines; re-check them before editing.

> **Parallel draft.** [telegram-portals-and-restaurant-dashboard.md](./telegram-portals-and-restaurant-dashboard.md) covers the
> same scope and was still being edited by another session while this was written. This plan keeps that draft's findings. Its
> decisions follow the owner's answers given in *this* session (§0). Choose one file before implementing and delete the other.

---

## 0. Owner decisions (18 Nov 2026)

| # | Decision |
|---|---|
| O1 | **Rider bot**: keeps `/my_jobs` and gains a **`/portal` alias**. Both send the same one-time rider-portal link. |
| O2 | **Restaurant bot, `/manage`**: stays restaurant-only. It sends one "Manage &lt;restaurant&gt;" link per restaurant on the admin's roster. |
| O3 | **Restaurant bot, `/sysadmin`** *(new)*: sends the sys-admin portal link. It works only for a phone in `ordelo_config.overwatch_list`. Only those people see it in the command menu, through a per-chat scoped menu (`BotCommandScopeChat`). |
| O4 | **Overwatch people can link to the restaurant bot even when they admin no restaurant.** They share their own phone number, as admins do. An overwatch-only person gets only the sys-admin option. |
| O5 | **Build every "Coming soon" item**: Reports, pickup time + auto-accept, notification preferences (channels + pause), closed dates and menu visibility. |
| O6 | **Edit rights**: any admin on the restaurant's `admins[]` list may change that restaurant's settings. **Every change is audited** (who, when, via what, old → new). Sys-admin can see each change and undo it. |
| O7 | **Hidden menu items** are enforced on the web storefront, by the menu API / WhatsApp ordering, and by an order-creation guard in `create_food_order_with_items`. |
| O8 | **Closed dates block all new orders**: web, WhatsApp and order creation. Existing orders are not affected. |
| O9 | **Reports** = financial reports: revenue, order counts and your-cut by day and by month, delivery vs takeaway, and a CSV export. These come from the existing `v_admin_orders_daily` / `_monthly` views. Operational timings (acceptance time, pickup lateness) are a later phase (§12). |

### Revision 19 Nov 2026: later owner decisions adopted (they override O3, O8, O9 above where they differ)

These decisions were confirmed on 19 Nov in the parallel plan. They are newer than the 18 Nov answers, so they win.

- **O3′**: overwatch members get **both** a `/sysadmin` command (scoped menu) **and** a "System dashboard" button under `/manage`. Restaurant links in `/manage` must still work if the sys-admin check fails.
- **O8′ (closures = service hours)**: managers close early at a London local time, or mark a whole date as a holiday. These are stored as **date overrides inside `restaurant_master.service_hours_json`**, beside the weekly schedule. The all-day marker is exactly `[["00:00","00:01"]]`. A date override is resolved before the weekday rule, and clearing it restores the weekly rule. An early close keeps the earlier intervals, truncates the interval containing the chosen time, and drops later intervals. Every reader recognises the all-day marker before converting it: frontend `utils/openingHours.ts`, backend `availability.py`, restaurant-agents `schedule.py`. A closed date also suppresses overnight spill-over from the previous day. The separate `restaurant_closure` table in §10 is **replaced** by this, and §10 is rewritten accordingly.
- **O9′ (Reports)**: start with **operational** measures:
  - manual acceptance time, with manual accepted, configured auto-accept, timeout fallback and declines counted separately
  - delivery pickup: minutes from creation to verified rider pickup, and minutes early/late against both the **original** and the **latest** promised pickup (example: collection 18:45, original promise 18:30, latest promise 18:50 → +15 and −5)

  This needs forward-captured milestones (§12 is promoted into scope). The cheap financial view from §7 is kept as a second section of the page.
- **O7′**: a hidden item stays hidden until an authorised admin of that restaurant explicitly restores it. The existing stock status still applies.
- **Relink revocation (confirmed)**: when a phone moves to a different Telegram account, revoke every rest_admin and sys_admin session and unused link for that phone in the same transaction. A repeat contact share from the same account changes nothing.

### Differences from the parallel draft

- Draft: put a "System dashboard" button under `/manage`; its latest edit has both a button and a scoped menu. **Here**: `/sysadmin` command plus scoped menu only, and `/manage` stays restaurant-only (O2, O3).
- Draft: keep `/my_jobs` only. **Here**: add `/portal` (O1).
- Draft: no audit. **Here**: an audit table is written by every settings RPC, with a sys-admin view and undo (O6).
- Draft: Reports start with operational metrics. **Here**: financial reports first, operational metrics in §12 (O9).
- Same in both: GET-safe activation for the admin roles, re-checking authority on every request, explicit session binding for tenant writes, and treating the `MENU_API_URL` owner as unknown.

---

## 1. What already exists (do not rebuild)

| Journey | Today | Code |
|---|---|---|
| Rider → rider portal (Telegram) | `/my_jobs` mints a 30-min one-time link. The link opens a non-consuming page that auto-POSTs to activate it. | [rider/dashboard.py `cmd_my_jobs`](../channels/telegram/rider/dashboard.py), [ordelo/rider_dashboard.py `issue_link`](../ordelo/rider_dashboard.py), RPC `rider_dashboard_mint` in [auth_sessions.sql](../ordelo_datamodels/admin_dashboard/auth_sessions.sql), [frontend activation GET/POST](../../restaurant-frontend/app/rider/activate/%5Btoken%5D/route.ts), [lib/rider-session.ts](../../restaurant-frontend/lib/rider-session.ts) (RPCs `rider_dashboard_activate`/`_touch`, lines 42/51) |
| Restaurant admin → dashboard (Telegram) | `/manage` sends one URL button per restaurant | [rest_admin/manage.py `cmd_manage`](../channels/telegram/rest_admin/manage.py) → [admin_links.profile](../channels/telegram/admin_links.py) (RPC `t_admin_profile`) → [`mint_dashboard_session_for`](../watomation/routers/rest_admin_auth_session.py) (plain table insert) |
| Restaurant admin → dashboard (WhatsApp) | `/login` sends a link for the **first** matching restaurant only | [`handle_login_wa_msg`](../watomation/on_message_wa_handler.py) (line ~339) → `mint_dashboard_session` |
| Overwatch → sys-admin (WhatsApp) | `/sysadmin` | [`handle_sysadmin_wa_msg`](../watomation/on_message_wa_handler.py) (line ~360) → [`create_sys_admin_dashboard_session`](../watomation/routers/sys_admin_auth_session.py) → `_ensure_sys_admin` (reads `overwatch_list`, splits on commas, strips `+`) |
| Sys-admin portal | Riders in shift, payouts, restaurants (+ admins card, config editor) | [app/sys-admin/*](../../restaurant-frontend/app/sys-admin), [SysAdminBottomNav](../../restaurant-frontend/components/sys-admin/SysAdminBottomNav.tsx) |
| Restaurant portal | Orders (real), Actions (5 stubs), Reports ("Coming soon", **not in the bottom nav**), More | [actions/page.tsx `STUBS`](../../restaurant-frontend/app/rest-admin/actions/page.tsx), [reports/page.tsx](../../restaurant-frontend/app/rest-admin/reports/page.tsx), [RestAdminBottomNav `TABS`](../../restaurant-frontend/components/rest-admin/RestAdminBottomNav.tsx) (Orders/Actions/More) |
| Session gates | Middleware validates the cookie per role and stamps context headers | [middleware.ts](../../restaurant-frontend/middleware.ts) (`PUBLIC_*_PATHS`, matcher at ~187), [lib/rest-admin-session.ts](../../restaurant-frontend/lib/rest-admin-session.ts), [lib/sys-admin-session.ts](../../restaurant-frontend/lib/sys-admin-session.ts) |

### Defects and gaps this plan fixes along the way

1. **Admin links are consumed on GET.** [rest-admin activate](../../restaurant-frontend/app/rest-admin/activate/%5Btoken%5D/route.ts) and [sys-admin activate](../../restaurant-frontend/app/sys-admin/activate/%5Btoken%5D/route.ts) activate on GET. A link-preview fetch (Telegram or WhatsApp) can therefore burn the link before the person taps it. `manage.py` works around this by turning previews off. The rider route already uses GET → auto-POST.
2. **The frontend sys-admin gate never re-checks overwatch.** `lib/sys-admin-session.ts` checks only cookie, role, user agent and expiry. Only the payout backend's `require_sys_admin` re-checks the list. A person removed from overwatch keeps up to 4 h of read/write on the restaurants and config pages.
3. **The rest-admin gate never re-checks roster membership.** An admin removed from `restaurant_master.admins` keeps their session.
4. **The tenant client does not scope RPCs.** `getRestAdminSupabaseClient()` scopes only the tables in `TENANT_SCOPED_TABLES` (line ~28). Every new write must therefore be an RPC that derives the tenant itself (§3, M6).
5. **Mint logic is copied in three places** (token, sha256, URL, insert): `rest_admin_auth_session.py`, `sys_admin_auth_session.py` and `ordelo/rider_dashboard.py`. The admin two use `client_ordelo`. CLAUDE.md requires `client_ordelo_service` for server-only objects.
6. WhatsApp `/login` silently picks the first restaurant. The Telegram `/manage` handles multiple restaurants.
7. The restaurant portal's More page labels the phone "WhatsApp" ([more/page.tsx](../../restaurant-frontend/app/rest-admin/more/page.tsx)). It should read "Linked phone".

---

## 2. Pre-flight checks (read-only, before any code)

Use the `database-operations` skill with **read-only** queries and record the results in this file.

- [ ] **P-1**: Is the admin roster live? [admin_roster.sql](../ordelo_datamodels/restaurant_admin/admin_roster.sql) says "NOT YET APPLIED", and [docs/to-do.md](../docs/to-do.md) line ~72 says P1 is "built but unapplied". `/manage` depends on `t_admin_profile`. Run `select proname from pg_proc where proname in ('t_admin_link','t_admin_profile','admin_set_channels')` and `select to_regclass('public.restaurant_admin')`. **If the roster is not live, Phases 1–2 wait for P1** (`migrations/admin_roster_p1.sql`).
- [ ] **P-2**: Live grants on `auth_sessions`: is anon revoked (rider cutover, [docs/rider-dashboard-rollout.md](../docs/rider-dashboard-rollout.md))? Which key does `pg_settings.client` use ([config/pg_setting.py:126](../config/pg_setting.py))? This decides whether today's admin mints work only because `client_ordelo` happens to be service-keyed. Check it; don't assume.
- [ ] **P-3**: Format of `overwatch_list`: comma-separated, with or without `+`, any spaces. Record one masked sample.
- [ ] **P-4**: Item key per menu table. `elas_menu` has **no `sku` column** ([core/menus.sql](../ordelo_datamodels/core/menus.sql) ~line 87). For each `<rest>_menu`, record whether `sku` is non-null and unique. Also record what the web basket (`Item.sku`) and the WhatsApp basket ([order_service.py](../utils_common/order_management/order_service.py) `_insert_order_rpc`, ~205) send as `sku`.
- [ ] **P-5 (owner question, blocks Phase 8 WhatsApp)**: Who owns and deploys the `MENU_API_URL` service (restaurant.byteloop.ai)? It is in no connected repo ([plans/ordelo-agg-plan-cc.md](./ordelo-agg-plan-cc.md) line ~206). Does any restaurant also publish a native WhatsApp (Meta) catalogue?

---

## 3. Module design (deep modules, seams, adapters)

The vocabulary is from the codebase-design skill. Each item names the module, its **interface** (what callers learn) and what it hides.

### M1 `is_overwatch(p_phone text) -> boolean` *(new SQL)*

The **one** overwatch membership rule. It splits `overwatch_list` on commas, keeps digits only via `admin_phone_digits()`, and compares exactly. It reads the row fresh and has no cache, because this is authorisation. The alerts cache in `get_overwatch_list()` ([config/params.py:167](../config/params.py)) is not.
- Location: [core/ordelo_config.sql](../ordelo_datamodels/core/ordelo_config.sql), the table it reads. **Inline the digits rule** (`regexp_replace(p, '\D', '', 'g')` plus an 8–15 length check) instead of calling `admin_phone_digits`. `admin_roster.sql` must `REQUIRES core/ordelo_config.sql`, because `t_admin_profile` is `LANGUAGE sql` and its body is checked when it is created. A reverse dependency would make a cycle. Add a GOTCHA in both files that the two digit rules must stay identical, and a SQL test asserting they agree.
- Callers: `t_admin_link`, `t_admin_profile`, `portal_access`, `sys_admin_dashboard_mint`, `admin_dashboard_session`, and Python `_ensure_sys_admin` (via `rpc('is_overwatch')`, replacing its own split in [sys_admin_auth_session.py](../watomation/routers/sys_admin_auth_session.py)).
- Deletion test: without it, three copies of the comma-split, `+`-strip rule drift apart, and WhatsApp, Telegram and the payout guard disagree.

### M2 Portal access + issuance *(SQL in [admin_dashboard/auth_sessions.sql](../ordelo_datamodels/admin_dashboard/auth_sessions.sql), Python in `ordelo/dashboard_links.py` (new))*

**SQL interface.** All functions are service-role only, follow the `rider_dashboard_mint` pattern (hash in, actor check + insert in one transaction), and take **exactly one** of `p_tuid` / `p_phone`. That gives two adapters (Telegram actor, WhatsApp actor) at one seam, so the seam is real.

```sql
portal_access(p_tuid bigint, p_phone text) -> jsonb
  -- {result: ok | not_linked, phone, restaurants:[{rest_ref, rest_name}], sys_admin: bool}
  -- tuid -> restaurant_admin.tuid -> phone; phone (WhatsApp wa_id) used as-is after admin_phone_digits().
  -- restaurants from admin_roster; sys_admin = is_overwatch(phone). ok even when restaurants = [] and sys_admin.
rest_admin_dashboard_mint(p_tuid bigint, p_phone text, p_rest_ref text, p_token_hash text) -> jsonb
  -- {result: ok | not_linked | not_allowed}; re-checks admin_roster membership for p_rest_ref under lock; inserts
  -- auth_sessions(role 'rest_admin', principal_id = phone, scope_ref = rest_ref, wa_number = phone, 30 min).
sys_admin_dashboard_mint(p_tuid bigint, p_phone text, p_token_hash text) -> jsonb
  -- {result: ok | not_linked | not_allowed}; is_overwatch(phone) checked in the same transaction.
```

**Python interface.** `ordelo/dashboard_links.py` absorbs [ordelo/rider_dashboard.py](../ordelo/rider_dashboard.py).

```python
Portal = Literal["rider", "rest_admin", "sys_admin"]

@dataclass(frozen=True)
class Actor:                       # exactly one field set
    tuid: int | None = None        # Telegram from_user.id (proved by contact share)
    wa_phone: str | None = None    # WhatsApp wa_id (proved by Meta)

@dataclass(frozen=True)
class PortalAccess:                # what this actor may open; also drives menus and help
    result: str                    # ok | not_linked
    restaurants: tuple[AdminRestaurant, ...] = ()
    sys_admin: bool = False

@dataclass(frozen=True)
class PortalLink:
    label: str                     # "Manage Strikers", "System dashboard", "Open my jobs"
    url: str
    rest_ref: str | None = None

@dataclass(frozen=True)
class Issued:
    result: str                    # ok | not_linked | not_allowed
    links: tuple[PortalLink, ...] = ()

async def access(actor: Actor) -> PortalAccess
async def issue(portal: Portal, actor: Actor) -> Issued   # raises only when the store or config is unavailable
```

- **Hidden behind `issue`**: token generation (`secrets.token_urlsafe(32)`), sha256, the per-portal RPC, the HTTPS-origin validation now in `rider_dashboard.issue_link` (extended to all roles), the per-role URL path (`/rider|/rest-admin|/sys-admin/activate/<token>`), per-restaurant fan-out for `rest_admin` (it calls `portal_access`, then one mint per restaurant), and logging that never prints a URL or token. The rider portal keeps calling `rider_dashboard_mint(p_tuid, …)` (live and verified).
- **Callers after the change** (each is a few lines): `cmd_my_jobs` / `/portal`, `cmd_manage`, `cmd_sysadmin` *(new)*, `handle_login_wa_msg`, `handle_sysadmin_wa_msg`.
- **Deleted**: `mint_dashboard_session` and `mint_dashboard_session_for` (in [rest_admin_auth_session.py](../watomation/routers/rest_admin_auth_session.py); delete the module if nothing else uses its router), `create_sys_admin_dashboard_session` and `CreateSysAdminSessionResponse` (in [sys_admin_auth_session.py](../watomation/routers/sys_admin_auth_session.py)), and `ordelo/rider_dashboard.py` (move its caller and test in the same change). Update every docstring and SQL header `CALLED BY` that names them.
- **Test surface**: one fake RPC client covering every `result` value, plus real token/URL assertions. Tests go through `issue`/`access` only.

### M3 Restaurant-bot capability menu *(new: `channels/telegram/rest_admin/menu.py`)*

```python
async def sync_admin_menu(bot, chat_id: int, access: PortalAccess) -> None
def help_text(access: PortalAccess | None) -> str
```
This is the twin of [`set_inflight_menu` / `sync_rider_menu`](../channels/telegram/rider/commands.py). It holds three command lists, defined beside `REST_ADMIN_COMMANDS` in [rest_admin/commands.py](../channels/telegram/rest_admin/commands.py):
- `REST_ADMIN_COMMANDS` (published default, unchanged; no `/sysadmin`)
- `ADMIN_AND_OPS_COMMANDS` = default + `/sysadmin` (admin who is also overwatch)
- `OPS_ONLY_COMMANDS` = `/start`, `/sysadmin`, `/help`, `/whoami` (overwatch, no restaurant, so no `/manage`, `/channels`, `/off`, `/on`)

`bot.set_my_commands(..., scope=BotCommandScopeChat(chat_id=chat_id))` is used for the two privileged lists. `bot.delete_my_commands(scope=...)` falls back to the default. **The menu is guidance, not authority** (precedent: [ADR 0013](../docs/adr/0013-pauses-have-a-mandatory-end-and-are-computed.md) Amendment 2): every handler re-checks through `access()`. Menu failures are logged and never fail the command.

Reconcile points: after `_link_contact` succeeds, then on `/start`, `/help`, `/whoami`, `/sysadmin` (a denied call clears the scope) and `/manage`. There is no cron. A person removed from overwatch keeps a stale menu entry until their next command, and the handler still refuses them. Optional rollout step: a one-off notebook cell that syncs every currently linked overwatch `tcid`.

### M4 Shared admin activation *(new: `restaurant-frontend/lib/dashboard-activation.ts`)*

```ts
export type DashboardRole = 'rider' | 'rest_admin' | 'sys_admin'
export function activationPage(role: DashboardRole, token: string): NextResponse          // GET/HEAD: non-consuming auto-POST page
export async function activateFromPost(role: DashboardRole, req: NextRequest, token: string): Promise<NextResponse>
```
This generalises the [rider route](../../restaurant-frontend/app/rider/activate/%5Btoken%5D/route.ts): token shape check (`^[A-Za-z0-9_-]{43}$`), the CSP with the script hash, the `Origin` check against the configured HTTPS origin (`RESTAURANT_MENU_APP_URL` row), private/no-store headers, 303 redirect, cookie set. A per-role table supplies the cookie name, landing path (`/rider/jobs`, `/rest-admin/orders`, `/sys-admin`), expired path, the activate function, and the re-request hint ("Send /portal or /my_jobs", "Send /manage, or /login on WhatsApp", "Send /sysadmin"). The three `activate/[token]/route.ts` files shrink to two exported functions each. Port [rider route.test.ts](../../restaurant-frontend/app/rider/activate/%5Btoken%5D/route.test.ts) to a table-driven test over all three roles.

### M5 Admin session RPCs *(new SQL in [auth_sessions.sql](../ordelo_datamodels/admin_dashboard/auth_sessions.sql))*

```sql
admin_dashboard_activate(p_role text, p_token_hash text, p_cookie_hash text, p_ua_hash text) -> jsonb  -- ok{session_id} | invalid
admin_dashboard_session(p_role text, p_cookie_hash text, p_ua_hash text) -> jsonb
  -- ok{session_id, principal_id, scope_ref, rest_name?} | invalid | not_authorised
  -- rest_admin: principal still on admin_roster for scope_ref. sys_admin: is_overwatch(principal_id).
admin_dashboard_touch(p_role text, p_cookie_hash text, p_ua_hash text) -> jsonb  -- same as session + last_seen_at bump
```
`p_role` must be `rest_admin` or `sys_admin`, else `invalid`. These mirror `rider_dashboard_*` (30-min link, 60-min idle, 4-h hard cap, single use, UA binding). [lib/rest-admin-session.ts](../../restaurant-frontend/lib/rest-admin-session.ts) and [lib/sys-admin-session.ts](../../restaurant-frontend/lib/sys-admin-session.ts) replace their direct `auth_sessions` table reads and updates (`activateToken`, `validateCookieAndTouch`) with these RPCs, the same way `lib/rider-session.ts` does. Logout (`revokeBySessionId` / `revokeByCookie`) may stay as direct service-role updates. `not_authorised` redirects to `/…/expired?reason=not_authorised` and revokes the row. The rider RPCs stay untouched.

### M6 Tenant-bound settings RPCs *(pattern for every new write)*

Every restaurant-portal read/write RPC takes **`p_session_id uuid`**, never a `rest_ref` or phone from the browser. Inside, an internal helper (not granted to any role) resolves and re-checks the session:

```sql
rest_admin_session_actor(p_session_id uuid) -> TABLE(phone text, rest_ref text)
  -- RAISES 'not_authorised' unless the session is rest_admin, activated, unrevoked, unexpired and phone is still on
  -- admin_roster for rest_ref. Called first by every rest_admin_* RPC below (each catches it -> {result:'not_authorised'}).
```
The frontend passes `getRestAdminContext().id` (stamped by [middleware](../../restaurant-frontend/middleware.ts); inbound copies are overwritten by `buildRestAdminContextHeaders`). A thin typed module `restaurant-frontend/lib/rest-admin-rpc.ts` *(new)* holds one function per RPC and maps `result` values to HTTP codes (`ok` 200, `not_authorised` 401, `stale` 409, `bad_*`/`needs_*` 400). It uses the server-only service client (`rawClient()` in `rest-admin-session.ts`; export it or move it to a shared server-only module).

### M7 Settings audit *(new SQL `ordelo_datamodels/restaurant_admin/restaurant_settings.sql`)*

```sql
table restaurant_settings_audit(id bigserial PRIMARY KEY, rest_ref text NOT NULL, setting text NOT NULL,
                                old_value jsonb, new_value jsonb, by_phone text, via text NOT NULL
                                /* dashboard | sys-admin | telegram | operator */, session_id uuid,
                                created_at timestamptz NOT NULL DEFAULT now(), reverted_by bigint REFERENCES restaurant_settings_audit(id))
restaurant_setting_revert(p_audit_id bigint, p_by text) -> jsonb  -- ok | not_found | changed_since | already_reverted | not_revertible
```
The audit is written **only** inside the settings RPCs (acceptance policy, closed dates, menu visibility, dashboard channel/pause changes), in the same transaction as the change, so it cannot be skipped. `setting` values: `auto_accept`, `delivery_pickup_minutes`, `collection_pickup_minutes`, `closure`, `menu_hidden`, `alert_channels`, `alert_pause`. `revert` re-applies `old_value` only when the current value still equals `new_value`, and audits the revert itself. Pauses are `not_revertible` because they expire on their own. RLS is on; the table is service-only. Sys-admin reads it.

### M8 Ordering guard *(new SQL `ordelo_datamodels/ordering/order_intake_guard.sql`)*

```sql
order_intake_block(p_rest_ref text, p_at timestamptz, p_item_keys text[]) -> jsonb
  -- {result: ok | closed_date | hidden_items, closed_on?, reopens_on?, hidden:[item_key...]}
```
This is the single decision for closures (O8) and hidden items (O7). It is called by:
- `create_food_order_with_items` (authoritative). On a block it raises with a distinct `SQLSTATE` (`P0C01` closed, `P0C02` hidden) and a JSON `DETAIL`. Both callers (`order_service.py` ~205, `web_checkout.py` ~444) map these to typed errors.
- the web pre-checks in [availability.py `available()`](../utils_common/web_ordering/availability.py) (~102) and [web_checkout.py `start()`/`create()`](../utils_common/web_ordering/web_checkout.py) (~105/~313), so the customer gets an actionable message before payment.
- restaurant-agents (through an RPC wrapper), so WhatsApp refuses early.

---

## 4. Phase 1: overwatch identity on the restaurant bot (O4)

**SQL**: [admin_roster.sql](../ordelo_datamodels/restaurant_admin/admin_roster.sql) and [core/ordelo_config.sql](../ordelo_datamodels/core/ordelo_config.sql)
1. Add M1 `is_overwatch`. REVOKE from PUBLIC, anon, authenticated; grant to service_role.
2. `t_admin_link` (~line 224): change the guard at ~240 from `NOT EXISTS (admin_roster …)` to `NOT EXISTS (admin_roster …) AND NOT is_overwatch(v_phone)`. Return `not_on_roster` only when the phone is on neither list. Add `'sys_admin', is_overwatch(v_phone)` to every success payload.
   - **First-link channels**: an overwatch-only person still gets `channels = {telegram}`. This is harmless because `admin_roster` is a join on restaurant lists, so with no restaurant they receive nothing. If they are later added to a restaurant, their alerts go to Telegram (D6 behaviour). Document this in the header GOTCHAS.
3. `t_admin_profile` (~291): add `'sys_admin', is_overwatch(ra.phone)`. Add a new result **`ops_only`**: a linked record that is on no roster but is overwatch. Existing `ok` keeps its meaning ("admin of ≥1 restaurant"), so every `is_admin` caller is unaffected. `not_on_roster` now means neither list.
4. **Revoke stale credentials on relink or unlink.** When `t_admin_link` returns `relinked`, and when `admin_unlink_telegram` succeeds, set `revoked = true, revoked_reason = 'relinked' | 'unlinked'` on that phone's unexpired `auth_sessions` rows (`role IN ('rest_admin','sys_admin')`, `principal_id = phone`), in the same transaction. This is deliberately conservative: sessions don't record which channel minted them, so WhatsApp-minted sessions for that phone are revoked as well. Test that an old link fails after a relink.
5. Check every other `restaurant_admin` consumer for zero-restaurant safety: `admin_recipients`, `admin_for_tuid`, `t_order_card_destinations`, `t_alert_destinations`, `t_admin_restaurants`, `admin_roster_status`. They all go through `admin_roster`, so expect no change. Prove it with a test row that has no roster entry.
6. Update the 13-section header: OBJECTS, LIFECYCLE result vocabulary, CALLED BY, TESTS.

**Python**: [admin_links.py](../channels/telegram/admin_links.py)
- `AdminLink.sys_admin: bool = False` and `AdminProfile.sys_admin: bool = False`. Add a property `AdminProfile.is_ops_only` (`result == "ops_only"`). Keep `LINKED_RESULTS` unchanged. Update the module docstring.

**Router**: [rest_admin/router.py](../channels/telegram/rest_admin/router.py)
- `_link_contact` (~115): on success with `out.restaurants == ()`, reply `OPS_LINKED` *(new copy)*: "✅ Linked as Ordelo operations. Send /sysadmin for the system dashboard." Skip the "Order alerts: … /channels" line. On every success call `sync_admin_menu`. Keep the `not_on_roster` ops alert; it now fires only for phones on neither list.
- `linked_text` (~72): append "System dashboard: /sysadmin" when `out.sys_admin`.
- `cmd_start` (~79): add an `elif prof.is_ops_only` branch before `not_on_roster`. Call `sync_admin_menu`.
- `cmd_whoami` (~169): add a line "Sys-admin: yes/no" and an ops-only link line.
- [channels.py](../channels/telegram/rest_admin/channels.py) (~58, ~105): ops-only gets "You don't admin a restaurant, so there are no order alerts to route." Don't show `NOT_LINKED` with a contact keyboard.
- [pauses.py](../channels/telegram/rest_admin/pauses.py) (~61 `not_admin`, ~74/~134 `NOT_LINKED`): use the same ops-only copy.
- [manage.py](../channels/telegram/rest_admin/manage.py) `cmd_manage`: ops-only gets "You don't admin a restaurant. For the system dashboard send /sysadmin."

**Tests**
- [tests/sql/test_admin_roster_sql.py](../tests/sql/test_admin_roster_sql.py) (+ [regression](../tests/sql/test_admin_roster_regression_sql.py)):
  - overwatch-only links (`linked`, `sys_admin=true`, restaurants `[]`)
  - a phone on neither list stays `not_on_roster`
  - `ops_only` profile
  - overwatch removed → `not_on_roster`
  - dual role → `ok` + `sys_admin`
  - `+44…` and spaced list entries match
  - destinations empty for an ops-only row
- [test_rest_admin_router.py](../tests/channels/telegram/test_rest_admin_router.py), [test_rest_admin_channels.py](../tests/channels/telegram/test_rest_admin_channels.py), [test_rest_admin_pauses.py](../tests/channels/telegram/test_rest_admin_pauses.py), [test_admin_links.py](../tests/channels/telegram/test_admin_links.py): add the `ops_only` / `sys_admin` fields to the fakes and assert the copy.

---

## 5. Phase 2: issuance, `/sysadmin`, scoped menu, `/portal` (O1–O3)

**SQL** (M2): add `portal_access`, `rest_admin_dashboard_mint` and `sys_admin_dashboard_mint` to [auth_sessions.sql](../ordelo_datamodels/admin_dashboard/auth_sessions.sql). Update its header (OBJECTS, CALLED BY, PYTHON MODEL → `ordelo/dashboard_links.py`, TESTS, and remove "LIVE CHECK … proposed" once applied). Tests: `tests/sql/test_admin_dashboard_sql.py` *(new; precedent [test_rider_dashboard_sql.py](../tests/sql/test_rider_dashboard_sql.py))* covering:
- each `result` value
- tuid vs phone actor
- membership removed between `portal_access` and mint → `not_allowed`
- bad hash raises
- grants: anon/authenticated denied

**Python**
1. Create `ordelo/dashboard_links.py` (M2) and move `issue_link`'s body in. Delete `ordelo/rider_dashboard.py` in the same change and update [tests/channels/telegram/test_rider_dashboard.py](../tests/channels/telegram/test_rider_dashboard.py).
2. `channels/telegram/rest_admin/sysadmin.py` *(new)*, modelled on [manage.py](../channels/telegram/rest_admin/manage.py):
   - `cmd_sysadmin`: private only, then `access(Actor(tuid=…))`, then `issue("sys_admin", actor)`, then one URL button "Open system dashboard" with `LinkPreviewOptions(is_disabled=True)`. Fall back to a text link on `TelegramBadRequest`, as `manage.py` does.
   - Denied: "This is for Ordelo operations only." Then `sync_admin_menu(...)` to clear any stale scope. Log without the URL.
   - Export `build_sysadmin_router()`. Include it in `build_router()` ([router.py](../channels/telegram/rest_admin/router.py) ~215) **before** the `last` fallback router.
3. [manage.py](../channels/telegram/rest_admin/manage.py): replace `admin_links.profile` + `mint_dashboard_session_for` with `issue("rest_admin", Actor(tuid=…))`. Keep `manage_keyboard` / `links_as_text` and the copy. Call `sync_admin_menu` after.
4. `channels/telegram/rest_admin/menu.py` *(new)* (M3), plus the lists in [commands.py](../channels/telegram/rest_admin/commands.py). `cmd_help` (router.py ~165) becomes `help_text(await access(...))`, falling back to the static `HELP_TEXT` on error.
5. Rider bot `/portal`:
   - [rider/dashboard.py](../channels/telegram/rider/dashboard.py): `router.message.register(cmd_my_jobs, Command("my_jobs", "portal"))`. Change the copy "Send /my_jobs" to "Send /portal or /my_jobs". Switch to `issue("rider", Actor(tuid=…))`.
   - [rider/commands.py](../channels/telegram/rider/commands.py): add `BotCommand(command="portal", description="Open your rider portal (jobs, earnings, payouts)")` to `RIDER_COMMANDS` (`INFLIGHT_COMMANDS` keeps it automatically). Update the module docstring.
6. WhatsApp ([on_message_wa_handler.py](../watomation/on_message_wa_handler.py) ~336–380):
   - `handle_login_wa_msg` → `issue("rest_admin", Actor(wa_phone=msg.from_user.wa_id))`, sending **one line per restaurant** (fixes gap 6).
   - `handle_sysadmin_wa_msg` → `issue("sys_admin", …)`. Remove the `HTTPException` coupling.
   - Registration in [fapp_ordelo_agent.py](../watomation/fapp_ordelo_agent.py) ~206 is unchanged.
7. [sys_admin_auth_session.py](../watomation/routers/sys_admin_auth_session.py): `_ensure_sys_admin` → `client_ordelo_service.rpc('is_overwatch', {'p_phone': …})`. Keep the 503 (store unavailable) vs 403 (not authorised) split. Delete `create_sys_admin_dashboard_session`. Update the module docstring's "Database objects" block.
8. Publish menus: [notebooks/telegram/tgram_setup_bot.py](../notebooks/telegram/tgram_setup_bot.py) (~38, ~85) republishes the default lists for both bots (rider gains `/portal`). Scoped overwatch menus are set by `sync_admin_menu`. Add a **required** cell `sync_overwatch_menus()`: for every linked `restaurant_admin` row, compute `access()` and sync its chat. Run it at rollout and after every edit to `overwatch_list`, so removed members lose the entry before their next command. Add this step to the `database-operations` skill's overwatch section.

**Tests**
- [test_rest_admin_manage.py](../tests/channels/telegram/test_rest_admin_manage.py): patch `dashboard_links.issue`; cover multi-restaurant, ops-only reply and button fallback.
- `tests/channels/telegram/test_rest_admin_sysadmin.py` *(new)*: allowed, denied (scope cleared), group chat, store error → TROUBLE, URL never logged, menu still showing but removed from overwatch → denied.
- `tests/channels/telegram/test_rest_admin_menu.py` *(new)*: three lists, set vs delete scope, failure swallowed, `help_text` per access.
- [test_rider_dashboard.py](../tests/channels/telegram/test_rider_dashboard.py): `/portal` behaves exactly like `/my_jobs`, and the menu contains `portal`.
- `tests/ordelo/test_dashboard_links.py` *(new)*: every portal × actor × result, HTTPS origin rejection, URL path per role, rest_admin fan-out with a partial `not_allowed`.
- [test_rest_admin_auth_session.py](../tests/watomation/routers/test_rest_admin_auth_session.py) and [test_sys_admin_auth_session.py](../tests/watomation/routers/test_sys_admin_auth_session.py): retarget to `issue`; keep the `require_sys_admin` tests.
- Use the [telegram-vertification-loop skill](../.claude/skills/telegram-vertification-loop/SKILL.md) for dispatcher, webhook and live evidence.

**Acceptance matrix**

| Person | Rider bot | Restaurant bot `/manage` | `/sysadmin` | Menu shows `/sysadmin` |
|---|---|---|---|---|
| Rider only | `/my_jobs`, `/portal` → rider link | not linked | denied | no |
| Admin of A, B | n/a | 2 buttons | denied | no |
| Overwatch only | n/a | "no restaurant, use /sysadmin" | link | yes (ops-only list) |
| Admin + overwatch | n/a | buttons | link | yes |
| Removed from overwatch after menu set | n/a | (as admin) | denied, scope cleared | cleared on that call |
| Forwarded contact, group chat, unlinked, stale callback | refused | refused | refused | no |
| `/sysadmin` or `/manage` typed to the **rider** bot (wrong bot) | unknown command (rider fallback) | n/a | n/a | n/a |
| Admin with alerts paused or WhatsApp-only channels | n/a | links as normal (alert settings never affect portal access) | as per overwatch | as per overwatch |

Also test that two people who are both allowed cannot mint for each other: the actor always comes from `from_user.id` or `wa_id` and never from text. A failure for one user must never send their links to another chat.

---

## 6. Phase 3: frontend activation and session gates (gaps 1–3)

1. Add `lib/dashboard-activation.ts` (M4) and rewrite three routes:
   - [app/rider/activate/[token]/route.ts](../../restaurant-frontend/app/rider/activate/%5Btoken%5D/route.ts) (behaviour identical)
   - [app/rest-admin/activate/[token]/route.ts](../../restaurant-frontend/app/rest-admin/activate/%5Btoken%5D/route.ts) (GET → page, POST → activate)
   - [app/sys-admin/activate/[token]/route.ts](../../restaurant-frontend/app/sys-admin/activate/%5Btoken%5D/route.ts) (same)

   Already-sent WhatsApp and Telegram URLs keep working because the path is unchanged. Only the first request becomes a page.
   Known limit: a link-preview fetcher that runs JavaScript could still submit the form. The Origin check and the 30-minute single-use token keep that risk small, and previews stay off on every send.
2. Sessions and middleware:
   - In [lib/rest-admin-session.ts](../../restaurant-frontend/lib/rest-admin-session.ts) and [lib/sys-admin-session.ts](../../restaurant-frontend/lib/sys-admin-session.ts), `activateToken` and `validateCookieAndTouch` call the M5 RPCs.
   - Add `'not_authorised' | 'unavailable'` to `ValidateFailure` and handle both in [middleware.ts](../../restaurant-frontend/middleware.ts). `unavailable` returns 503, as the rider gate already does.
   - Keep the cookie names `__Host-radash` / `__Host-sdash` so live sessions survive.
   - **Await** the touch RPC and check its result. Today's direct `.update(last_seen_at)` must not become fire-and-forget; follow `rider_dashboard_touch`.
3. Expired pages:
   - [rest-admin/expired](../../restaurant-frontend/app/rest-admin/expired/page.tsx): "Send /manage to the Ordelo restaurant bot on Telegram, or /login on WhatsApp."
   - [sys-admin/expired](../../restaurant-frontend/app/sys-admin/expired/page.tsx): "/sysadmin on Telegram or WhatsApp."
   - [rider/expired](../../restaurant-frontend/app/rider/expired/page.tsx) (~25): "/portal or /my_jobs."
   - Add copy for `not_authorised` ("You no longer have access…").
4. [more/page.tsx](../../restaurant-frontend/app/rest-admin/more/page.tsx): change "WhatsApp" to "Linked phone" and show the restaurant name.
5. Tests:
   - table-driven `lib/dashboard-activation.test.ts`: GET/HEAD don't consume, POST with a bad Origin → 403, reuse → expired, race (two POSTs, one cookie), wrong-role cookie
   - middleware tests for `not_authorised` and `unavailable`
   - run vitest with `NODE_OPTIONS=--no-experimental-webstorage` (Node 26)
   - a tenant-A cookie calling tenant-B actions → refused
   - authorised manual smoke tests: open a link in Telegram's in-app browser and in a normal browser launched from WhatsApp, on iOS and Android, and confirm the auto-POST works and the cookie sticks

**Order**: deploy Phase 3 **before** advertising `/sysadmin`. GET-safe links are what make Telegram previews harmless.

---

## 7. Phase 4: Reports (O9)

Data already exists: `v_admin_orders_daily(day, type, count, gross, your_cut)` and `v_admin_orders_monthly(month, type, count, gross, your_cut)` in [v_admin_orders.sql](../ordelo_datamodels/admin_dashboard/v_admin_orders.sql) (~145, ~164). Both are in `TENANT_SCOPED_TABLES`, so reads stay on the scoped client. **No SQL change.**

1. `app/api/rest-admin/reports/route.ts` *(new)*: `GET ?from&to&grain=day|month&type=all|delivery|takeaway`. Returns rows plus totals and a delivery/takeaway split. Validate dates and cap the range at 366 days. Model it on [orders/summary/route.ts](../../restaurant-frontend/app/api/rest-admin/orders/summary/route.ts).
2. `app/api/rest-admin/reports/export/route.ts` *(new)*: the same query as `text/csv` with `Content-Disposition: attachment; filename=<rest_ref>-<from>-<to>.csv`. Share the row builder in `app/rest-admin/reports/_lib/rows.ts` *(new)*.
3. [reports/page.tsx](../../restaurant-frontend/app/rest-admin/reports/page.tsx):
   - reuse [DateRangeChips](../../restaurant-frontend/app/rest-admin/orders/DateRangeChips.tsx) (`rangeBounds`) and [TypeFilter](../../restaurant-frontend/app/rest-admin/orders/TypeFilter.tsx)
   - Day/Month toggle, KPI strip (orders, gross, your cut, delivery vs takeaway), a bar chart of your-cut per period (load the `dataviz` skill first), a table, and a "Download CSV" button
   - empty and error states
4. [RestAdminBottomNav](../../restaurant-frontend/components/rest-admin/RestAdminBottomNav.tsx): add a **Reports** tab, giving Orders, Reports, Actions and More. [RestAdminTopBar](../../restaurant-frontend/components/rest-admin/RestAdminTopBar.tsx) already has the label at line 9.
5. Tests: route unit tests (tenant scoping, range cap, CSV escaping) plus a Playwright smoke at 390 px width.

---

## 8. Phase 5: Actions, acceptance policy and audit (O5, O6)

**SQL**: `ordelo_datamodels/restaurant_admin/restaurant_settings.sql` *(new; REQUIRES core/restaurant_master.sql, core/ordelo_config.sql, admin_dashboard/auth_sessions.sql, restaurant_admin/admin_roster.sql)*
- M6 helper `rest_admin_session_actor`, M7 table + `restaurant_setting_revert`.
- `restaurant_default_pickup_minutes(p_rest_ref, p_kind) -> TABLE(minutes int, inherited bool)` *(new)*: the restaurant-key-then-global lookup now inlined in [resolve_initial_restaurant_acceptance](../ordelo_datamodels/restaurant_admin/resolve_initial_restaurant_acceptance.sql) (~60–64). Change `resolve_initial_restaurant_acceptance` to call it, so the dashboard and order creation can't disagree.
- `rest_admin_acceptance_get(p_session_id) -> {result, auto_accept, delivery_minutes, collection_minutes, delivery_inherited, collection_inherited, version}`.
- `rest_admin_acceptance_set(p_session_id, p_auto_accept, p_delivery_minutes, p_collection_minutes, p_version)` → `ok | stale | bad_minutes | needs_defaults | not_authorised`:
  - Minutes are whole numbers from 1 to 180. `NULL` means "inherit" and deletes the restaurant's own key.
  - `needs_defaults` when auto-accept would be on without both effective defaults. ADR 0001 says init would RAISE in that case.
  - Writes `restaurant_master.auto_accept` and upserts or deletes the two `<REST>_DEFAULT_*_PICKUP_TIME` rows in `ordelo_config`, plus one audit row per changed setting (`via='dashboard'`). All in one transaction.
  - `version` = max `updated_at` of the three, for optimistic concurrency.
- Existing orders are unaffected: the policy is read at creation ([ADR 0001](../docs/adr/0001-configured-restaurant-auto-accept.md)).
- Check the effect against [init_delivery](../ordelo_datamodels/delivery/init_delivery.sql), [init_takeaway](../ordelo_datamodels/takeaway/init_takeaway.sql), the confirmation timeout ([job_restaurant_confirmation_timeout.sql](../ordelo_datamodels/restaurant_admin/job_restaurant_confirmation_timeout.sql)) and the silence policy ([ADR 0014](../docs/adr/0014-restaurant-silence-policy-is-decided-in-sql.md)). Changing defaults must not change a pickup time an admin picked by hand on an existing order, or the reminders for orders still awaiting a response.

**Frontend**
- `lib/rest-admin-rpc.ts` *(new, M6)*. `app/api/rest-admin/settings/acceptance/route.ts` *(new)* (GET, PATCH).
- [actions/page.tsx](../../restaurant-frontend/app/rest-admin/actions/page.tsx): replace `STUBS` with sections, each a client component under `app/rest-admin/actions/_components/` *(new)*. First is `AcceptanceCard`:
  - auto-accept switch
  - two minute inputs showing "inherits N min", with "Reset to default"
  - help text: "applies to new orders only"
  - on 409, reload and show "Another admin changed this"

**Sys-admin view and undo (O6)**
- `app/api/sys-admin/restaurants/[rest_ref]/changes/route.ts` *(new)*: GET lists the audit, newest first. `.../changes/[id]/revert/route.ts` *(new)*: POST → `restaurant_setting_revert(id, 'sys-admin:<phone>')`.
- [sys-admin/restaurants/page.tsx](../../restaurant-frontend/app/sys-admin/restaurants/page.tsx): add a "Recent changes" card per restaurant with an Undo button.
- The sys-admin config PATCH ([config/route.ts](../../restaurant-frontend/app/api/sys-admin/restaurants/%5Brest_ref%5D/config/route.ts)) writes arbitrary keys without an audit. When it edits `auto_accept` or the two pickup keys, route the change through a sys-admin variant of the acceptance RPC (`restaurant_acceptance_set_by_operator(p_rest_ref, …, p_by)`) so it is audited too.

**Tests**: `tests/sql/test_restaurant_settings_sql.py` *(new)*:
- authorisation: removed admin, another tenant's session, revoked session
- stale, needs_defaults, inherit/reset
- audit rows; revert, changed_since, already_reverted
- `init_delivery` / `init_takeaway` still resolve the same minutes

Also frontend route and component tests.

---

## 9. Phase 6: Actions, My alerts (notification preferences)

This replaces the "Notification preferences" stub with **My alerts**.

**SQL**: `ordelo_datamodels/restaurant_admin/rest_admin_dashboard_alerts.sql` *(new)*
- `rest_admin_alerts_get(p_session_id) -> {result, channels, telegram_linked, paused_until, pause_options}`. Reads `restaurant_admin`, `pause_current('rest_admin', phone, rest_ref)` and `pause_options('rest_admin')`.
- `rest_admin_alerts_set_channels(p_session_id, p_channels)` → wraps `admin_set_channels(phone, channels, 'dashboard')` (results `ok | not_found | bad_channels | not_linked`) and audits.
- `rest_admin_alerts_pause(p_session_id, p_duration)` and `rest_admin_alerts_resume(p_session_id)`:
  - wrap `pause_start` / `pause_end` from [availability/pauses.sql](../ordelo_datamodels/availability/pauses.sql) with `p_via='dashboard'`
  - keep the last-admin guard (`not_allowed`, ADR 0013 Amendment 1)
  - audit the change

**Frontend**
- `app/api/rest-admin/settings/alerts/route.ts` *(new)*.
- `AlertsCard`:
  - channel picker: WhatsApp / Telegram / both. When Telegram isn't linked, the option is greyed out with "Open the Ordelo restaurant bot and send /start first".
  - pause chips taken from `pause_options`
  - note: "Channels apply to all your restaurants; pausing applies to this restaurant."

**Round-trip test**: a dashboard change appears in Telegram `/channels` and `/off` status on the next read, and the reverse. Extend [test_rest_admin_channels.py](../tests/channels/telegram/test_rest_admin_channels.py), [test_rest_admin_pauses.py](../tests/channels/telegram/test_rest_admin_pauses.py) and [test_admin_pauses_sql.py](../tests/sql/test_admin_pauses_sql.py).

---

## 10. Phase 7: closed dates (O8)

**SQL**: `ordelo_datamodels/restaurant_admin/restaurant_closures.sql` *(new)*
- Table `restaurant_closure(rest_ref text, closed_on date, note text, created_by text, created_at timestamptz, PRIMARY KEY (rest_ref, closed_on))`. RLS on, service-only.
- `restaurant_closed_on(p_rest_ref text, p_at timestamptz) -> boolean` uses the London local date (`(p_at AT TIME ZONE 'Europe/London')::date`). An order belongs to the date it is placed, including during overnight hours. Document this and test 23:59 vs 00:01 and both DST changes.
- `rest_admin_closures_list(p_session_id)`, `rest_admin_closures_add(p_session_id, p_from date, p_to date, p_note)` and `rest_admin_closures_remove(p_session_id, p_dates date[])`. Add accepts ≤ 60 days and no past dates. All three are audited.
- M8 `order_intake_block` reads `restaurant_closed_on`.

**Enforcement** (all three surfaces go through M8)
1. `create_food_order_with_items` ([ordering/create_food_order_with_items.sql](../ordelo_datamodels/ordering/create_food_order_with_items.sql)) calls `order_intake_block(v_rest_ref, now(), keys)` before its inserts.
   - **`p_order` has no restaurant key today**: `food_order` stores none, and the function reads only `order_id`, `order_number`, `seq_id` and so on. Add an explicit `rest_ref` key to `p_order` in both callers: `order_service._insert_order_rpc` (~205; the caller already has `rest_ref`) and `web_checkout.create` (~440). During the transition, fall back to `upper(split_part(p_order->>'order_number', '-', 1))`. Verify that the order-number prefix equals `rest_ref` for every onboarded restaurant. Once both callers send it, remove the fallback and RAISE when it is missing.
   - `keys` = the `item_key` expression (§11) over `p_items` (`sku`, else `product_name`).
   - Map the new SQLSTATEs in `order_service._insert_order_rpc` and `web_checkout.create`.
   - An **idempotent web retry** is already handled in Python before the insert: `web_checkout.create` looks up `web_order_request` by `idempotency_key` (~357) and returns the stored order. Keep that ordering, so a closure added later never breaks the retry. No idempotency logic goes into the SQL function.
   - Update the header: CALLED BY, GOTCHAS, and the SECURITY note (it is executable by PUBLIC today; flag it in [docs/to-do.md](../docs/to-do.md) rather than changing grants silently).
2. Web:
   - [availability.py](../utils_common/web_ordering/availability.py): `available()` (~102) returns closed with `reopens_on`, and `opening()` (~45) skips closed dates when it computes the next opening. `eligibility()` (~297) reports a closed restaurant through its per-restaurant status. Same check in `web_checkout.start()` (~105). A stale "open" page must still get an actionable closed message when the customer submits.
   - Storefront: check which pages use the backend availability and which read `service_hours_json` directly ([lib/restaurantHours.ts](../../restaurant-frontend/lib/restaurantHours.ts), [utils/openingHours.ts](../../restaurant-frontend/utils/openingHours.ts)). Add the closure to the direct readers.
3. WhatsApp (restaurant-agents):
   - [WeeklySchedule](../../restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/service_hours/schedule.py) and its operational lookup cache ([tests](../../restaurant-agents/tests/services/test_operational_lookup_cache.py)) treat a closure as closed for that day.
   - [agent_wa_senders.py](../../restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/rest_agent/agent_wa_senders.py) sends no menu link that day.
   - WhatsApp menu checkout goes through [frontend checkout](../../restaurant-frontend/app/api/checkout/route.ts) → [order_hooks.py](../watomation/routers/order_hooks.py) → `order_service`. Map the guard's typed rejection to customer copy at each hop.
   - Support and payment for an order created **before** the closure keep working.
   - Follow [restaurant-agents/CONSTITUTION.md](../../restaurant-agents/CONSTITUTION.md) for that repo's release rules.
   - Guard 1 is the safety net, so this step is a UX improvement.

**Frontend**: `app/api/rest-admin/settings/closures/route.ts` *(new)* and a `ClosuresCard` with a range picker and a list of dates with remove buttons.

**Tests**:
- SQL: date edges, DST, tenant isolation, audit
- [test_web_contract.py](../tests/utils_common/web_ordering/test_web_contract.py) and `tests/utils_common/order_management/test_order_service.py`
- a live run with the [live order harness](../docs/live-order-test-harness.md) on a `STRK-TEST` restaurant with a closure: web refuses, WhatsApp refuses, and removing the closure reopens it

---

## 11. Phase 8: menu visibility (O7). Blocked on P-4 and P-5

**SQL**: `ordelo_datamodels/ordering/menu_item_visibility.sql` *(new)*
- Table `menu_item_hidden(rest_ref text, item_key text, title text, hidden_by text, hidden_at timestamptz, PRIMARY KEY (rest_ref, item_key))`. An item with no row is visible. The table is separate from `<rest>_menu`, so it survives a bulk menu refresh.
- `item_key` = `sku` where P-4 shows it is reliable for that restaurant, otherwise the normalised `title`. Record the rule per restaurant in the header. Use the same expression in `order_intake_block`.
- `rest_admin_menu_list(p_session_id, p_search text)`:
  - reads `<rest>_menu` via `format('%I', lower(rest_ref) || '_menu')`, only after a `to_regclass` check
  - **never** takes a table name from the browser
  - returns items with a `hidden` flag
- `rest_admin_menu_set_hidden(p_session_id, p_item_keys text[], p_hidden bool)`: idempotent and audited.
- `menu_hidden_keys(p_rest_ref) -> text[]`, used by the readers below.

**Enforcement**
1. Order creation: M8 returns `hidden_items`. Web `create()` maps it to a 409 listing the affected lines. The basket lets the customer remove them before any payment session starts.
2. Web storefront: [app/api/menu/route.ts](../../restaurant-frontend/app/api/menu/route.ts) filters the `MENU_API_URL` response by `menu_hidden_keys` (service client, 30–60 s cache). The basket/checkout server path checks as well.
3. Menu API / WhatsApp: **depends on P-5**. If the menu service can be changed, it filters by `menu_hidden_keys`. If not, restaurant-agents' menu tools filter after fetching. The order guard (1) is the backstop either way. If a Meta catalogue exists, its publisher must sync visibility before WhatsApp parity is claimed.

**Frontend**: `app/api/rest-admin/settings/menu/route.ts` *(new)* and a `MenuVisibilityCard` (search, a toggle per item, a "Hidden (n)" filter).

**Tests**:
- hide and unhide
- a stale cart
- the same key at another tenant
- a menu refresh keeps the hidden state
- a title-keyed table like elas
- an out-of-stock item that is hidden and then unhidden comes back still out of stock (hiding never touches `availability`)
- cached menu feeds: the web cache and the menu service cache
- a menu link sent on WhatsApp before the item was hidden
- duplicate display names and brand variants mapping to one `item_key`
- historical order lines and receipts still show the item

---

## 12. Later (not in this build): operational reports

Kept from the parallel draft for when the owner asks. The metrics:
- median minutes to manual acceptance
- actual pickup vs promised pickup

They need **forward-captured immutable milestone timestamps**, because `restaurant_update_dtts` and `status_update_dtts` are overwritten. Use a small `order_milestone(order_number, milestone, at)` table with a unique key. Stamp it at the authoritative transitions: [restaurant_order_decision.sql](../ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql) and the `pickedup` write in [rider_agent.py](../ordelo/agents/rider_agent.py). Mark when coverage starts, do no backfill, and exclude test orders via [order_has_test_item](../ordelo_datamodels/ordering/order_has_test_item.sql).

---

## 13. Cross-cutting rules for every phase (CLAUDE.md)

- **SQL standard** ("ordelo_datamodels SQL standard" in [agents.md](../agents.md)):
  - every file: the 13-section header, idempotent, RLS on, `REVOKE ALL … FROM PUBLIC, anon, authenticated`, service-role grants
  - after a header change, run `python scripts/datamodels/build_guide.py`; after applying, run `python scripts/datamodels/drift_check.py`
  - run the isolated SQL tests with the `ordelo-sql-test-db` skill
- **Cross-references in the same change**:
  - Python wrapper docstring ↔ SQL header `CALLED BY`
  - [docs/telegram-layer.md](../docs/telegram-layer.md): §6 rows for every new RPC and table, plus the change log and the [HTML companion](../docs/telegram-layer.html)
  - restaurant-agents feature guide, for the closure and hidden-item behaviour on WhatsApp
  - [GLOSSARY.md](../GLOSSARY.md): add **Portal link**, **Sys-admin (overwatch member)**, **Closed date**, **Hidden item**, **Settings audit**, and keep "Restaurant dashboard session" (~403) consistent
- **Fakes**: every new RPC gets a fake covering all `result` values (pattern: `FakeInviteDb`).
- **Async**: Supabase calls go through `asyncio.to_thread`, using only `client_ordelo_service` for these RPCs.
- **Logs**: never log a URL, token, cookie or full phone; use `mask()` from [ops_alerts.py](../channels/telegram/ops_alerts.py).
- **ADR** *(new)*: `docs/adr/0017-portal-access-is-decided-per-request-in-sql.md`. It records one verified identity per phone, with permissions derived on every request (roster → restaurant, overwatch → system). Menus are guidance only. Activation is GET-safe.

---

### Verification commands

- OrdeloAgent (venv active, `PYTHONPATH="$PWD"`, `.env` loaded per [local-testing-runbook](../docs/local-testing-runbook.md)):
  - `pytest tests/channels/telegram tests/watomation/routers tests/ordelo tests/utils_common/web_ordering tests/utils_common/order_management tests/test_datamodels_standard.py`
  - `ruff check .`
  - isolated SQL tests: `ordelo-sql-test-db` skill (`pytest tests/sql`)
- restaurant-frontend:
  - `npm run lint`
  - `NODE_OPTIONS=--no-experimental-webstorage npm test`
  - `npm run build`
  - `BASE_URL=http://localhost:3000 npm run test:e2e`
- restaurant-agents: the shared-runtime tests and each affected app's offline contract tests.

Report offline results, isolated SQL results and authorised live evidence separately. Never apply frozen `migrations/` files, and never reset a shared schema to verify.

### Live verification loop (Telegram via computer use + local services via Cloudflare Tunnel)

**Environment facts (checked 19 Nov 00:17)**
- One Supabase database: the production one (`restaurant_admin` roster is live; 10 restaurants).
- The local `.env` uses the **production** bots @OrdeloRestaurantBot and @ByteloopRidersBot. Their webhooks point at `rider-agent.ordelo.app`.
- `ORDELO_APP_URL` and `RESTAURANT_MENU_APP_URL` point at production.
- Live testing is therefore the runbook's **maintenance window** ([local-testing-runbook.md](../docs/local-testing-runbook.md) §4–7).

**Loop**, run once per feature:

1. **Offline gates** (all must pass, compared with the baselines below):
   - `pytest tests --ignore=tests/sql`
   - isolated `pytest tests/sql`
   - frontend `vitest`, `lint`, `build`
2. **Apply the SQL** for that feature to the database: additive only, compatible with the deployed production code, applied before the code that calls it. Then run `drift_check.py`.
3. **Start the local services**:
   - OrdeloAgent: `uv run watomation/fapp_ordelo_agent.py` on port 3100
   - frontend: `npm run dev` on port 3000
   - tunnel: `cloudflared tunnel run`
   - Check `https://rider-agent-test.ordelo.app/docs` and `https://restaurant-test.ordelo.app/rest-admin/expired` both answer.
4. **Open the window** (record the "before" values first):
   - Switch `RESTAURANT_MENU_APP_URL` to `https://restaurant-test.ordelo.app` so dashboard links open the local frontend.
   - Switch `ORDELO_APP_URL` only when testing web ordering.
   - Point each bot's webhook at `https://rider-agent-test.ordelo.app` (setWebhook with the existing secret and `allowed_updates` = message, callback_query). Before this, check there are no inflight deliveries and no restaurant inside service hours.
5. **Drive Telegram desktop by computer use**:
   - Restaurant bot: `/start`, then `/manage` (buttons; System dashboard button for overwatch), `/sysadmin`, `/help` (menu), `/whoami`.
   - Rider bot: `/portal` and `/my_jobs`.
   - Tap each link: the GET page loads, the auto-POST lands on the right portal, and a second tap shows "expired".
   - In the portals, exercise each Actions card, Reports, and the sys-admin "Recent changes" undo.
6. **Check the database**: `auth_sessions` rows (role, scope, activated), audit rows, service-hours overrides, hidden items. Use read-only queries afterwards.
7. **Close the window**:
   - Restore both webhooks to `https://rider-agent.ordelo.app` and both config URLs.
   - Confirm with `getWebhookInfo` and a SELECT.
   - Revert any test data written to real restaurants (settings back to their before values via the audit/undo path, overrides cleared, items unhidden).
   - Use only the `STRK` test restaurant for writes where possible.

**Baselines (19 Nov, before any change)**
- Python: 3 failures (`test_master_pymodels::test_restaurant_master_get_admins_fetches_live_column`, `test_datamodels_standard::test_header_paths_exist[platform/fly_config.sql]`, `test_restaurant_decision::test_describe[auto_decline-None-auto-declined]`).
- SQL: 528 passed, with the 2 known `test_restaurant_notices_script_sql` failures.
- Frontend vitest: 339 passed.

## 14. Rollout order and rollback

1. Apply SQL additively, in phase order: M1 and the roster changes, then M2/M5, settings, alerts, closures, the guard, visibility. Each file goes live before the code that calls it.
2. Deploy frontend Phase 3 (activation and gates). It works with old links.
3. Deploy OrdeloAgent Phases 1–2 and republish both bot menus with `tgram_setup_bot.py`. Then ask overwatch members to `/start` the restaurant bot.
4. Release Reports, then each Actions group in its own small release. Enable closure and menu editing **only after** every consumer enforces the guard (§10, §11).
5. Rollback:
   - Remove `/sysadmin` from the router and clear the scoped menus; the default menu never had it.
   - Activation routes can be reverted on their own; sessions are unaffected.
   - If a closure or hidden item is active, keep the guard and clear the data rather than reverting the code.
   - The audit and closure tables are additive and stay.

## 15. Related, not in scope

- [docs/to-do.md](../docs/to-do.md) ~86, "Overwatch rider alerts never reach Telegram": Phase 1 gives overwatch members a `tcid`, which is the identity a Telegram ops-alert sink needs. Decide that separately.
- Admin roster P2/P3 ([plans/restaurant-admin-roster-onboarding-plan.md](./restaurant-admin-roster-onboarding-plan.md)).

---

## Implementation log (19 Nov 2026)

Each feature's evidence is labelled **offline** (pytest, vitest, tsc, eslint), **isolated SQL** (throwaway Postgres, `ordelo-sql-test-db`) or **live**. Live means local services through the tunnel, the production database, real Bot API sends to the owner's chat and a real browser.

Computer use was not available in this session, and `agent-desktop` lacks macOS Accessibility permission, so Telegram was driven by **injecting updates into the live webhook**. The tool is `scratchpad/tools/tg_inject.py`: the real secret header, the owner's tuid 7279908526 (`lohith`, phone …0754, admin + overwatch + rider). This covers ingress → dispatcher → handler → SQL → real Bot API send. The only thing it cannot exercise is a human tap on the Telegram client.

| Feature | Offline | Isolated SQL | Live |
|---|---|---|---|
| `is_overwatch`, overwatch-only linking, `ops_only` profile, relink/unlink revocation | `tests/channels/telegram` 528 ✓ | `test_admin_dashboard_sql.py` (35) ✓; suite 569 ✓ (2 known failures) | migration `telegram_portals_p1.sql` applied 00:2x, verified true / ok / not_linked |
| `/manage`: restaurant links + System dashboard button + scoped menu | ✓ | – | ✓ 5 links (CHKS, CRDO, CRMS, ELAS, STRK) + system button; 5 `rest_admin` rows |
| `/sysadmin` + `sa1:go` button | ✓ | – | ✓ both mint `sys_admin` rows. Found and fixed: the tap now acknowledges through `answer_quietly`, so a failed acknowledgement no longer blocks the link |
| `/help` and `/whoami` per capability | ✓ | – | ✓ handled (no errors) |
| Rider `/portal` alias + `/my_jobs` | ✓ | – | ✓ both mint `rider` rows |
| WhatsApp `/login` (all restaurants) and `/sysadmin` via `dashboard_links` | ✓ `test_wa_dashboard_commands.py` | – | not live (no WhatsApp client here) |
| GET-safe activation for rest_admin / sys_admin (`lib/dashboard-activation.ts`) | vitest ✓ (36 new) | `admin_dashboard_activate` / `_touch` ✓ | ✓ GET/HEAD/foreign POST leave the link unused; the browser lands on `/sys-admin/riders-inshift`, `/rest-admin/orders` (STRK) and `/rider/jobs`; re-use → `/sys-admin/expired?reason=not_found` with the new copy |
| Per-request authority re-check (roster / overwatch) | ✓ | ✓ (removed admin → `not_authorised`, session revoked) | ✓ sessions validated through `admin_dashboard_touch` |

| Acceptance policy + audit + sys-admin undo | vitest route tests | `test_restaurant_settings_sql.py` (27) incl. agreement with live `resolve_initial_restaurant_acceptance` | ✓ STRK delivery 30→25 via the Actions card; stale edit 409; bad minutes 400; sys-admin "Recent changes" shows it; Undo restores 30, a second undo 409 |
| My alerts (channels + pause) | ✓ | `test_rest_admin_dashboard_alerts_sql.py` | ✓ pause 6h from the dashboard (`created_via=dashboard`) then resumed by the bot's `/on` (round trip); channels Telegram→both restored; bad input 400 |
| Closed dates (service_hours_json "dates") | backend `test_web_contract.py`, frontend `openingHours.dates.test.ts`, restaurant-agents `test_schedule.py` | `test_restaurant_service_hours_sql.py` | ✓ gate off → `disabled`; gate STRK-only → closed 29 Nov + early close 30 Nov from the card; SQL guard, backend `opening()` and restaurant-agents `WeeklySchedule` agree on the live row; sys-admin weekly save keeps the dates; both cleared; STRK hours identical to before; gate back to '' |
| Hidden items + order guard | `test_order_refusal.py` | `test_order_intake_guard_sql.py` | ✓ hiding "BBQ Cauliflower Bites" removed it from the storefront menu, showing restored it; live savepoint test: normal order created, hidden item refused P0C02, nothing left |
| Reports (operational + sales + CSV) | ✓ | `test_rest_admin_reports_sql.py` (owner example +15 / −5) | ✓ ELAS 90 days: 52 orders (13 manual, 6 configured auto, 33 timeout), median accept 0.5 min (9 measured), order→pickup 27 min (14), −2.0 vs first / −2.6 vs latest promise, 5 late; STRK shows 0 because all 53 STRK orders are TEST3100 (excluded); Reports tab in nav; CSV downloads |

SQL applied live (all additive except the noted function replacements, each verified before commit): `migrations/telegram_portals_p1.sql`, `restaurant_settings_p1.sql`, `rest_admin_alerts_p1.sql`, `order_intake_guard_p1.sql`, `rest_admin_reports_p1.sql`. A read-only comparison of all 47 new or changed functions found no drift (the full `drift_check.py` needs pgvector/PostGIS on the scratch server).

Final suites (19 Nov):
- OrdeloAgent: 1904 passed, with the same 3 baseline failures.
- isolated SQL: 647 passed, with the same 2 baseline failures.
- restaurant-frontend: vitest 385 passed; tsc and lint have no errors.
- restaurant-agents: 450 passed.
- Ruff on the changed files is clean apart from 2 findings that predate this work.

`next build` was not run because it would overwrite the `.next` folder of the running dev server.

Unrelated issue seen in the live backend log: `web_order_lookup` raises `UndefinedFunction` (the order-lookup feature's SQL is not applied live). It is not part of this work and has not been touched.

Found in the final review and fixed: CHKS is an alias of ELAS (`config/params.py` `_REST_REF_ALIAS_MAP`), and the old mint scoped CHKS links to ELAS. `dashboard_links.issue("rest_admin")` now skips the alias link when the person also admins the canonical restaurant; a CHKS-only admin keeps a CHKS link. Live `/manage` now sends CRDO, CRMS, ELAS and STRK (+system). Tests: `test_alias_restaurant_is_covered_by_its_canonical_link`, `test_alias_only_admin_keeps_the_alias_link`.

Deviations from this plan, as built:
- `is_overwatch` lives in `admin_roster.sql`, not `core/ordelo_config.sql`. That avoids a dependency cycle and keeps the digits rule shared.
- Hidden items are keyed by the normalised **title**, because `elas_menu` has no `sku`.
- The guard derives the restaurant from the order number's prefix, so neither caller had to change.
- Closures are stored as `service_hours_json.dates` (O8′). The separate closure table in §10 was not built.
- `resolve_initial_restaurant_acceptance` was left unchanged on live; an agreement test enforces that it matches `restaurant_default_pickup_minutes`.

## Comparison round 2 (19 Nov) with the parallel plan

The parallel plan now carries the owner's 19 Nov decisions, and this build follows them:
- `/manage` button plus `/sysadmin` with a scoped menu
- operational Reports with both pickup benchmarks
- closures stored as date overrides in `service_hours_json`
- hidden items stay hidden until explicitly restored
- relink revocation across scopes and channels

This file adds what the parallel plan still lacks:
- the pre-flight blockers it found (restaurant-agents `parse_week` crashes on a non-weekday key, so writes are gated; `order_item.sku` and `food_order.thread_id` are NOT NULL live; `elas_menu` has no `sku`)
- the audit and sys-admin undo (O6)
- the rider `/portal` alias
- the sales section and CSV next to the operational report
- the live verification loop and its results

The parallel plan still has unique value in its fixture ideas for operational reports (redispatch, cancellation, repeated events, DST), which `test_rest_admin_reports_sql.py` covers only partly (DST and cancellation are not fixtures yet).
