# Ordelo Domain Context

## Configured auto-accept

A restaurant-level policy stored as `restaurant_master.auto_accept`. When true,
new delivery and takeaway summaries receive a configured pickup time at creation
and bypass manual restaurant confirmation.

## Timeout auto-accept

The existing fallback for an otherwise manually confirmed order that reaches the
restaurant-confirmation timeout. It shares `restaurant_confirmation_status` of
`auto_accept` but is not a configured auto-accept order.

## Configured-auto order

An order created while configured auto-accept is enabled. It stores
`rest_confirmation_method='configured_auto'`, which keeps later notification
policy deterministic even if restaurant configuration changes.
