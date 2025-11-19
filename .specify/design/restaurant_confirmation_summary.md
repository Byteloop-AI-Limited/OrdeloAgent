# Restaurant Confirmation Touchpoint - Implementation Summary

**Date:** 2025-11-18  
**Status:** ✅ COMPLETE - Ready for Database Migration

---

## What Was Implemented

A new touchpoint in the delivery workflow where restaurants confirm food preparation time **before** rider dispatch begins. This prevents premature rider assignments and ensures riders are only dispatched when food is ready.

---

## Files Created/Modified

### SQL Files (You will execute these)

1. **`ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql`**
   - Adds 3 new columns to `delivery_summary`
   - Updates status constraint to include `restaurant_unconfirmed`
   - Creates trigger function and trigger for webhook
   - Adds default config value

2. **`ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql`**
   - Timeout job with restaurant-specific timeout support
   - Looks up `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT` first
   - Falls back to `RESTAURANT_CONFIRMATION_TIMEOUT`
   - Defaults to 5 minutes

3. **`ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql`**
   - Processes manual restaurant confirmation
   - No validation on prep_time (as requested)
   - Calls `process_delivery()` to continue workflow

### Python Files (Already updated)

4. **`ordelo_datamodels/delivery_pymodels.py`**
   - Added 3 optional fields to `DeliverySummary` model

5. **`watomation/routers/delivery_hooks.py`**
   - Added `/restaurant-confirmation-request` endpoint
   - Sends WhatsApp with 5/15/25 minute buttons

6. **`watomation/on_callback_wa_handler.py`**
   - Added `handle_restaurant_confirmation()` callback handler

7. **`watomation/fapp_ordelo_agent.py`**
   - Registered restaurant confirmation callback handler

---

## How It Works

### New Workflow

```
1. Order Created (init_delivery)
   ↓ status = 'restaurant_unconfirmed'
   ↓ DB trigger fires
   
2. Restaurant Receives WhatsApp
   ↓ "How long until food is ready?"
   ↓ [5 min] [15 min] [25 min]
   
3a. Restaurant Clicks Button
    ↓ handle_restaurant_confirmation()
    ↓ status → 'unassigned'
    ↓ process_delivery() called
    
3b. OR 5 Minutes Pass (timeout)
    ↓ job_restaurant_confirmation_timeout()
    ↓ status → 'unassigned', prep_time = 25
    ↓ process_delivery() called
    
4. Normal Dispatch Flow Continues
   ↓ job_create_dispatch()
   ↓ Rider receives dispatch
```

### Key Features

- ✅ Restaurant-specific timeout values supported
- ✅ Automatic fallback to 25 minutes on timeout
- ✅ WhatsApp button interface (no typing required)
- ✅ Follows existing webhook + trigger pattern
- ✅ Minimal schema changes (3 new columns)
- ✅ No validation on prep_time (flexible for future use)

---

## Your Action Items

### 1. Run Database Migration

```bash
# Connect to your database
psql -U your_user -d your_database

# Execute migration
\i ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql

# Deploy functions
\i ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql
\i ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql
```

### 2. Schedule pg_cron Job

```sql
SELECT cron.schedule(
  'job_restaurant_confirmation_timeout',
  '* * * * *',  -- Every minute
  $$SELECT * FROM job_restaurant_confirmation_timeout()$$
);
```

### 3. Update init_delivery() Function

You need to modify `ordelo_datamodels/jobs_n_functions/init_delivery.sql`:

**Line 137:** Change status
```sql
-- OLD:
'unassigned',

-- NEW:
'restaurant_unconfirmed',
```

**Line 141-142:** Comment out process_delivery
```sql
-- OLD:
-- kick off process_delivery; May be add condition on pickup_time
PERFORM process_delivery();

-- NEW:
-- process_delivery will be called after restaurant confirmation
-- PERFORM process_delivery();
```

### 4. (Optional) Add Restaurant-Specific Timeouts

```sql
-- Example: 3-minute timeout for WREN restaurant
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('WREN_RESTAURANT_CONFIRMATION_TIMEOUT', '3', 'Custom timeout for WREN');

-- Example: 7-minute timeout for ELAI restaurant
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ELAI_RESTAURANT_CONFIRMATION_TIMEOUT', '7', 'Custom timeout for ELAI');
```

### 5. Test the Flow

```sql
-- Create a test order
SELECT init_delivery('test_customer_id', 'WREN-TEST123');

-- Check status
SELECT order_number, status, rest_confirmed_at, rest_prep_time_minutes 
FROM delivery_summary 
WHERE order_number = 'WREN-TEST123';

-- Verify restaurant receives WhatsApp message
-- Click a button or wait for timeout
-- Verify status changes to 'unassigned'
-- Verify dispatch flow continues
```

---

## Configuration Reference

### Default Config (Already Added by Migration)

```sql
config_key: 'RESTAURANT_CONFIRMATION_TIMEOUT'
config_value: '5'
description: 'Default minutes to wait for restaurant confirmation'
```

### Restaurant-Specific Config (Optional)

Pattern: `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT`

Examples:
- `WREN_RESTAURANT_CONFIRMATION_TIMEOUT` → 3 minutes
- `ELAI_RESTAURANT_CONFIRMATION_TIMEOUT` → 7 minutes
- `TACO_RESTAURANT_CONFIRMATION_TIMEOUT` → 10 minutes

If restaurant-specific config doesn't exist, falls back to default (5 minutes).

---

## Database Schema Changes

### New Columns in `delivery_summary`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `rest_confirmed_at` | TIMESTAMP WITH TIME ZONE | Yes | When restaurant confirmed |
| `rest_prep_time_minutes` | INTEGER | Yes | Confirmed prep time (5/15/25) |
| `rest_confirmation_method` | VARCHAR(20) | Yes | 'manual' or 'timeout' |

### Updated Status Values

Old: `'unassigned', 'timedout', 'assigned', 'completed'`

New: `'restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed'`

---

## Monitoring & Troubleshooting

### Check Pending Confirmations

```sql
SELECT order_number, rest_id, dtts, 
       EXTRACT(EPOCH FROM (NOW() - dtts))/60 AS minutes_waiting
FROM delivery_summary
WHERE status = 'restaurant_unconfirmed'
ORDER BY dtts DESC;
```

### Check Confirmation Rate

```sql
SELECT 
  rest_confirmation_method,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM delivery_summary
WHERE rest_confirmation_method IS NOT NULL
GROUP BY rest_confirmation_method;
```

### Check Average Response Time

```sql
SELECT 
  rest_id,
  COUNT(*) as total_confirmations,
  ROUND(AVG(EXTRACT(EPOCH FROM (rest_confirmed_at - dtts))/60), 2) as avg_minutes,
  ROUND(AVG(CASE WHEN rest_confirmation_method = 'manual' 
            THEN EXTRACT(EPOCH FROM (rest_confirmed_at - dtts))/60 END), 2) as avg_manual_minutes
FROM delivery_summary
WHERE rest_confirmed_at IS NOT NULL
GROUP BY rest_id
ORDER BY total_confirmations DESC;
```

### Check Timeout Rate by Restaurant

```sql
SELECT 
  rest_id,
  COUNT(*) as total,
  SUM(CASE WHEN rest_confirmation_method = 'timeout' THEN 1 ELSE 0 END) as timeouts,
  ROUND(SUM(CASE WHEN rest_confirmation_method = 'timeout' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as timeout_rate
FROM delivery_summary
WHERE rest_confirmation_method IS NOT NULL
GROUP BY rest_id
ORDER BY timeout_rate DESC;
```

---

## Rollback Plan (If Needed)

If you need to rollback:

```sql
-- 1. Remove trigger
DROP TRIGGER IF EXISTS trigger_restaurant_confirmation_request ON delivery_summary;

-- 2. Remove trigger function
DROP FUNCTION IF EXISTS restaurant_confirmation_whook();

-- 3. Remove job functions
DROP FUNCTION IF EXISTS job_restaurant_confirmation_timeout(VARCHAR);
DROP FUNCTION IF EXISTS handle_restaurant_confirmation(VARCHAR, INTEGER);

-- 4. Remove columns (CAUTION: This deletes data)
ALTER TABLE delivery_summary
  DROP COLUMN IF EXISTS rest_confirmed_at,
  DROP COLUMN IF EXISTS rest_prep_time_minutes,
  DROP COLUMN IF EXISTS rest_confirmation_method;

-- 5. Restore old status constraint
ALTER TABLE delivery_summary 
  DROP CONSTRAINT delivery_summary_status_check,
  ADD CONSTRAINT delivery_summary_status_check 
    CHECK (status IN ('unassigned', 'timedout', 'assigned', 'completed'));

-- 6. Remove config
DELETE FROM ordelo_config WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT';

-- 7. Unschedule cron job
SELECT cron.unschedule('job_restaurant_confirmation_timeout');
```

---

## Success Metrics to Track

After deployment, monitor:

1. **Confirmation Rate:** % of orders confirmed manually (target: >70%)
2. **Average Response Time:** Time from request to confirmation (target: <2 min)
3. **Timeout Rate:** % of orders that timeout (target: <30%)
4. **Rider Wait Time:** Time riders spend waiting at restaurants (should decrease)
5. **Order Completion Time:** End-to-end delivery time (should maintain or improve)

---

## Questions?

If you encounter issues:

1. Check logs in FastAPI for webhook errors
2. Check PostgreSQL logs for trigger/function errors
3. Verify restaurant has admin contacts in `restaurant_master.admins`
4. Verify WhatsApp Business account is active
5. Check `ordelo_config` for correct configuration values

---

**Implementation Complete!** 🎉

All code changes are done. You just need to run the database migrations and update `init_delivery()`.
