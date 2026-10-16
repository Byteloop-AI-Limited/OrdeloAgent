-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Applied: every object it creates exists live (checked 2026-10-16).
-- Current definitions now live in: core/restaurant_master.sql
-- Purpose: Order cut-off minutes before closing on restaurant_master (also in ordelo_agg_r3.sql).
-- The feature files above are the current truth; this file only records the one-off change.

-- Run with the coordinated restaurant-agents release; does not alter venue hours.
alter table restaurant_master
  add column if not exists delivery_order_cutoff_minutes integer not null default 0,
  add column if not exists takeaway_order_cutoff_minutes integer not null default 0;
