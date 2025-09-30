# Thread Closure System Documentation

## Overview

The Ordelo system implements an automated thread closure mechanism that identifies and closes inactive WhatsApp conversation threads that haven't been accessed recently and are not marked for retention.

## System Components

### 1. Database Function: `job_close_thread()`

**Location**: `ordelo_datamodels/jobs_n_functions/job_close_thread.sql`

**Scheduled Execution**:
- Runs every 5 minutes via Supabase cron job
- Cron expression: `*/5 * * * *`

**Configuration**:
- `THREAD_INACTIVE_TIME_INTERVAL` - Minutes of inactivity before thread closure (default: 5)
- `ORDELO_APP_URL` - Base URL for webhook calls (default: https://rider-agent.ordelo.app)

**Logic Flow**:
1. Queries thread table for inactive threads
2. Filters: `last_access_dtts` older than interval AND `retain_thread = false`
3. Aggregates matching records as JSON array with thread_id, recipient, last_access_dtts, is_active, minutes_since_last_access
4. Makes HTTP POST to `/delivery-hooks/close-threads` webhook endpoint
5. Returns boolean indicating if threads were found and notified

**Webhook Integration**:
- Endpoint: `POST /delivery-hooks/close-threads`
- Payload: JSON array of thread records
- Triggers thread closure and goodbye message to recipients

### 2. FastAPI Endpoint: `/delivery-hooks/close-threads`

**Location**: `watomation/routers/delivery_hooks.py`

**Triggered by**: Supabase cron job running every 5 minutes
**Source Function**: `job_close_thread()` in `ordelo_datamodels/jobs_n_functions/job_close_thread.sql`

**Workflow**:
1. Receives JSON array of thread records to close
2. For each thread:
   - Marks thread as inactive using `ThreadHandler.make_threads_inactive()`
   - Sends goodbye message to recipient via WhatsApp
3. Returns success status with count of processed threads

**Payload Structure**:
```json
[
    {
        "thread_id": "uuid",
        "recipient": "phone_number",
        "last_access_dtts": "timestamp",
        "is_active": boolean,
        "minutes_since_last_access": number
    }
]
```

## Thread Management Components

### Database Schema

**Table**: `public.thread`
- `thread_id` (text) - Primary key
- `recipient` (varchar(12)) - Phone number
- `is_active` (boolean) - Thread status
- `retain_thread` (boolean) - Prevents automatic closure (default: false)
- `dt` (date) - Creation date
- `dtts` (timestamp) - Creation timestamp
- `last_access_dtts` (timestamp) - Last access timestamp

### Thread Handler Class

**Location**: `utils_common/thread_management/thread_handler.py`

**Key Methods**:
- `get_or_create_thread()` - Gets existing or creates new thread atomically
- `retain_thread()` - Sets retain_thread flag to true for active thread
- `make_threads_inactive()` - Marks threads as inactive for a recipient

### Database Functions

**Core Functions**:
- `get_active_thread()` - Gets active thread and updates last_access_dtts
- `create_thread()` - Creates a new thread
- `get_or_create_thread()` - Gets existing or creates new thread atomically
- `retain_thread()` - Sets retain_thread flag for active thread
- `make_threads_inactive()` - Marks threads as inactive

## Workflow Integration

1. **Thread Creation**: New threads created with `is_active = true`, `retain_thread = false`
2. **Thread Access**: `get_active_thread()` updates `last_access_dtts` on access
3. **Thread Retention**: `retain_thread()` sets `retain_thread = true` to prevent closure
4. **Scheduled Cleanup**: Cron job runs every 5 minutes calling `job_close_thread()`
5. **Thread Closure**: Inactive threads processed via webhook, marked inactive, and recipients notified

## Configuration Management

**Config Keys**:
- `THREAD_INACTIVE_TIME_INTERVAL`: Minutes before thread considered inactive
- `ORDELO_APP_URL`: Base URL for webhook endpoints

**Usage Example**:
```sql
-- Set thread retention for active thread
SELECT * FROM retain_thread('447448440754');

-- Run manual thread cleanup
SELECT job_close_thread();
```

## Error Handling

- Empty payloads handled gracefully in webhook endpoints
- Function returns boolean indicating success/failure
- Logging implemented for debugging and monitoring
- Fallback values for missing configuration
