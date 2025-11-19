# Restaurant Confirmation Touchpoint - Implementation Progress

**Started:** 2025-11-18  
**Approach:** Option A (Status-Based Flow)

---

## Implementation Checklist

### Phase 1: Database Layer (SQL Files - User will execute)
- [x] `migrations/add_restaurant_confirmation_fields.sql` - Migration script with all DB changes
- [x] `jobs_n_functions/job_restaurant_confirmation_timeout.sql` - Create timeout job (with rest_ref support)
- [x] `jobs_n_functions/handle_restaurant_confirmation.sql` - Create confirmation handler

### Phase 2: Application Layer (Code changes)
- [x] Update `delivery_pymodels.py` - Add new fields to `DeliverySummary`
- [x] Update `delivery_hooks.py` - Add `/restaurant-confirmation-request` endpoint
- [x] Update `on_callback_wa_handler.py` - Add restaurant confirmation callback handler
- [x] Register callback handler in `fapp_ordelo_agent.py`
- [x] Update module docstrings

### Phase 3: Documentation
- [x] Create implementation progress tracker
- [x] Add comments for new functionality

---

## Changes Log

### 2025-11-18 14:35 - Starting Implementation

**Modifications from original proposal:**
1. ✅ Remove prep_time validation from `handle_restaurant_confirmation()`
2. ✅ Add `rest_ref` parameter to timeout job with fallback logic:
   - Check for `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT`
   - Fallback to `RESTAURANT_CONFIRMATION_TIMEOUT`
3. ✅ Keep FastAPI endpoint and callback handler as proposed

### 2025-11-18 15:00 - Phase 1 Complete

**SQL Files Created:**
- ✅ `ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql`
  - Adds 3 new columns to delivery_summary
  - Updates status CHECK constraint
  - Creates restaurant_confirmation_whook() trigger function
  - Creates trigger on INSERT with status='restaurant_unconfirmed'
  - Adds default config value

- ✅ `ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql`
  - Supports optional rest_ref parameter
  - Restaurant-specific timeout lookup: `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT`
  - Falls back to `RESTAURANT_CONFIRMATION_TIMEOUT` config
  - Defaults to 5 minutes if no config found
  - Returns detailed action logs

- ✅ `ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql`
  - No validation on prep_time_minutes (as requested)
  - Updates delivery_summary and transitions to 'unassigned'
  - Calls process_delivery() to trigger dispatch flow
  - Returns boolean for success/failure

### 2025-11-18 15:15 - Phase 2 Complete

**Application Code Changes:**
- ✅ `ordelo_datamodels/delivery_pymodels.py`
  - Added 3 optional fields to DeliverySummary model
  - rest_confirmed_at, rest_prep_time_minutes, rest_confirmation_method

- ✅ `watomation/routers/delivery_hooks.py`
  - Added `/restaurant-confirmation-request` endpoint
  - Fetches restaurant admin from restaurant_master
  - Sends WhatsApp message with 3 button options (5/15/25 min)
  - Includes timeout warning in message
  - Updated module docstring

- ✅ `watomation/on_callback_wa_handler.py`
  - Added handle_restaurant_confirmation() function
  - Calls Supabase RPC to handle_restaurant_confirmation
  - Sends confirmation or error messages back to restaurant
  - Updated module docstring

- ✅ `watomation/fapp_ordelo_agent.py`
  - Imported handle_restaurant_confirmation
  - Added IS_RESTAURANT_CONFIRMATION filter
  - Registered CallbackButtonHandler for restaurant confirmations

---

## Current Status: COMPLETE ✅

All code changes implemented. Ready for database migration execution.

---

## Files Created

### SQL Files (For Database Execution)
1. `ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql` - Complete migration script
2. `ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql` - Timeout job function
3. `ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql` - Confirmation handler function
4. `ordelo_datamodels/jobs_n_functions/init_delivery_changes_needed.md` - Guide for init_delivery changes

### Documentation Files
5. `.specify/design/restaurant_confirmation_touchpoint_proposal.md` - Original design proposal
6. `.specify/design/restaurant_confirmation_implementation_progress.md` - This file
7. `.specify/design/restaurant_confirmation_summary.md` - Complete implementation summary with monitoring queries

---

## Next Steps for User

1. **Execute Database Migration:**
   ```sql
   -- Run this file to add columns, trigger, and config
   \i ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql
   ```

2. **Deploy SQL Functions:**
   ```sql
   -- Deploy timeout job function
   \i ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql
   
   -- Deploy confirmation handler
   \i ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql
   ```

3. **Schedule pg_cron Job:**
   ```sql
   -- Schedule timeout job to run every minute
   SELECT cron.schedule(
     'job_restaurant_confirmation_timeout',
     '* * * * *',
     $$SELECT * FROM job_restaurant_confirmation_timeout()$$
   );
   ```

4. **Update init_delivery() Function:**
   - Change status from 'unassigned' to 'restaurant_unconfirmed' on line 137
   - Comment out or remove the PERFORM process_delivery() call on line 142
   - This ensures orders wait for restaurant confirmation before dispatch

5. **Optional: Add Restaurant-Specific Timeouts:**
   ```sql
   -- Example: Set 3-minute timeout for WREN restaurant
   INSERT INTO ordelo_config (config_key, config_value, description)
   VALUES ('WREN_RESTAURANT_CONFIRMATION_TIMEOUT', '3', 'Custom timeout for WREN restaurant');
   ```

6. **Test the Flow:**
   - Create a test order via init_delivery()
   - Verify restaurant receives WhatsApp message with buttons
   - Test manual confirmation (click button)
   - Test timeout scenario (wait 5+ minutes)
   - Verify dispatch flow continues after confirmation/timeout

---

## Lint Warnings (Non-Critical)

The following unused imports exist in the codebase but are not related to this feature:
- `delivery_hooks.py`: AsyncConnectionPool, asyncio (line 36-37)
- `on_callback_wa_handler.py`: pg_settings (line 23)
- `fapp_ordelo_agent.py`: logger, process_byteloop_agent (line 31, 44)

These can be cleaned up separately if desired.
