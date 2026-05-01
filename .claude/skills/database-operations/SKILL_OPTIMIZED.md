---
name: database-operations
description: Query, inspect, and modify the Ordelo Supabase/Postgres database. ALWAYS use this skill when the user asks to query table data, fetch records by ID/order_number/rider_id/cust_id, check database values, inspect ordelo_config, switch between test/prod environments, update rows, or perform any database operation — even if they don't explicitly say "database" or "query". Trigger phrases: "get details from delivery_summary", "check what's in the table", "look up rider info", "update rider status", "switch ELAS to prod", "how many orders have status X", or any request mentioning table names (rider_master, restaurant_master, ordelo_config, delivery_summary, delivery_dispatch, delivery_option, cust_rest_map). This skill provides both standard config-based access AND automatic fallback to direct Supabase client when AWS credentials are unavailable, so network/credential issues won't block you.
---

[Rest of SKILL.md remains the same as improved version above...]
