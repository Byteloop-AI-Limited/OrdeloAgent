-- Run with the coordinated restaurant-agents release; does not alter venue hours.
alter table restaurant_master
  add column if not exists delivery_order_cutoff_minutes integer not null default 0,
  add column if not exists takeaway_order_cutoff_minutes integer not null default 0;
