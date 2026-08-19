# ADR 0001: Resolve configured auto-accept in the database

## Status

Accepted

## Decision

Use a shared database acceptance-policy module for delivery and takeaway summary
initialization. It reads `restaurant_master.auto_accept`, resolves the pickup
configuration, and produces the pickup timestamp in the same transaction as the
summary insert.

Configured auto-accept orders store `rest_confirmation_method='configured_auto'`.
Notification suppression therefore follows the order's creation-time policy,
instead of the cached restaurant row or the overloaded `auto_accept` confirmation
status used by timeout fallback.

## Consequences

- Delivery and takeaway use one configuration interface while retaining their
  distinct lifecycle statuses.
- Missing/invalid restaurant configuration falls back to the global key; an
  invalid/missing global key fails the auto-accept order initialization.
- Auto-accepted takeaways need an INSERT pickup trigger to retain payment/print
  and restaurant webhook processing.
