# ADR 0017: Portal access is decided per request in SQL

## Status

Accepted 19 Nov 2026 (owner decisions of 18-19 Nov; plans/telegram-portal-links-and-dashboard-plan.md).

## Decision

One verified identity per phone, with permissions derived on every request:

- **Identity.** A Telegram account proves its phone by sharing its own contact (`contact.user_id == from_user.id`); a WhatsApp sender is proved by Meta (`wa_id`). An overwatch phone may link to the restaurant bot even when it admins no restaurant (`t_admin_profile` result `ops_only`).
- **Permissions.** Restaurant rights come from `restaurant_master.admins` (`admin_roster`). System rights come from `is_overwatch()`, which reads `ordelo_config.overwatch_list` fresh every time. Alert channels and pauses never grant or remove portal access.
- **Issuance.** `ordelo/dashboard_links.py` is the one place that makes portal links. The SQL mint (`rest_admin_dashboard_mint`, `sys_admin_dashboard_mint`, `rider_dashboard_mint`) re-checks authority and stores the hashed token in the same transaction.
- **Activation and use.** A link opens a non-consuming page; the browser's same-origin POST consumes it. `admin_dashboard_touch` re-checks roster or overwatch membership on every protected request, and every restaurant-dashboard write passes the session id to SQL, which re-derives phone and restaurant (`rest_admin_session_actor`).
- **Revocation.** Moving a phone to another Telegram account, or unlinking it, revokes that phone's rest_admin and sys_admin sessions and unused links in the same transaction.
- **Menus are guidance only.** `/sysadmin` appears only in overwatch chats' scoped menus, but every handler re-checks.

## Consequences

- Removing someone from a restaurant's admins list or from overwatch takes effect on their next click, not after their 4-hour session.
- Dashboard links survive Telegram and WhatsApp link previews.
- The restaurant dashboard can safely offer writes (acceptance policy, closed dates, alerts, hidden items), each audited in `restaurant_settings_audit` with sys-admin undo.

## Considered and rejected

- A "System dashboard" permission column on the admin record: duplicates the overwatch list and drifts from it.
- Frontend-only checks of membership: the payout backend already had to re-check, and other pages did not.
- Activating links on GET: link previews used them up.
