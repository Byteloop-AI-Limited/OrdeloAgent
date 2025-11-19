# Restaurant Confirmation Feature - Patterns Applied

**Feature:** Restaurant Confirmation Touchpoint  
**Date:** 2025-11-18  
**Purpose:** Real-world example of OrdeloAgent patterns in action

---

## Overview

This document shows how core OrdeloAgent patterns were applied to implement the restaurant confirmation feature. Use this as a reference when implementing similar features.

---

## Patterns Applied

### ✅ Pattern 1: Database-Triggered Webhook

**What:** When a new order is created with `status='restaurant_unconfirmed'`, trigger a webhook to send WhatsApp message to restaurant.

**Implementation:**

**SQL Trigger Function** (`ordelo_datamodels/migrations/add_restaurant_confirmation_fields.sql`):
```sql
CREATE OR REPLACE FUNCTION restaurant_confirmation_whook()
RETURNS TRIGGER AS $$
DECLARE
  response json;
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
BEGIN
  IF NEW.status = 'restaurant_unconfirmed' THEN
    -- Build payload
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'created_at', NEW.dtts
    ) INTO webhook_payload;
    
    -- Get URL from config with fallback
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
    
    -- HTTP POST
    response := (
      SELECT content FROM http_post(webhook_url, webhook_payload::text, 'application/json')
    );
    
    RAISE NOTICE 'Restaurant confirmation request sent for order %: %', NEW.order_number, response;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Trigger:**
```sql
CREATE TRIGGER trigger_restaurant_confirmation_request
AFTER INSERT ON delivery_summary
FOR EACH ROW
WHEN (NEW.status = 'restaurant_unconfirmed')
EXECUTE FUNCTION restaurant_confirmation_whook();
```

**FastAPI Endpoint** (`watomation/routers/delivery_hooks.py`):
```python
@router.post("/restaurant-confirmation-request")
async def restaurant_confirmation_request_hook(
    payload: dict = Depends(get_payload),
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """Webhook triggered when order needs restaurant confirmation."""
    try:
        order_number = payload.get("order_number")
        rest_id = payload.get("rest_id")
        
        # Get restaurant contact
        restaurant = client.table("restaurant_master")\
            .select("admins")\
            .eq("rest_id", rest_id)\
            .single()\
            .execute()
        
        admin_phone = restaurant.data["admins"][0]
        
        # Send WhatsApp with buttons
        # ... (see Pattern 2)
        
        return {"status": "success", "order_number": order_number}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"status": "error", "message": str(e)}
```

**Pattern Elements Used:**
- ✅ Row-level trigger with WHEN condition
- ✅ JSON payload construction with `json_build_object`
- ✅ Config lookup with fallback
- ✅ `http_post()` for webhook call
- ✅ FastAPI endpoint with error handling
- ✅ Logging at key points

---

### ✅ Pattern 2: WhatsApp Callback Buttons

**What:** Send WhatsApp message with 3 buttons (5/15/25 min) for restaurant to select prep time.

**Implementation:**

**Send Buttons** (`watomation/routers/delivery_hooks.py`):
```python
from pywa.types import Button
import json

# Create callback payloads
prep_time_buttons = [
    Button(
        title="5 minutes",
        callback_data=json.dumps({
            "command": "/restaurantConfirmation",
            "order_number": order_number,
            "prep_time_minutes": 5
        })
    ),
    Button(
        title="15 minutes",
        callback_data=json.dumps({
            "command": "/restaurantConfirmation",
            "order_number": order_number,
            "prep_time_minutes": 15
        })
    ),
    Button(
        title="25 minutes",
        callback_data=json.dumps({
            "command": "/restaurantConfirmation",
            "order_number": order_number,
            "prep_time_minutes": 25
        })
    ),
]

message_text = f"""
🔔 *New Delivery Order*

Order: {order_number}

How long until the food is ready for pickup?
⚠️ If no response in 5 minutes, we'll assume 25 minutes.
""".strip()

await _async_wa_client.send_message(
    to=admin_phone,
    text=message_text,
    buttons=prep_time_buttons
)
```

**Callback Handler** (`watomation/on_callback_wa_handler.py`):
```python
async def handle_restaurant_confirmation(wa: WhatsApp, msg: Message):
    """Handles restaurant confirmation callback."""
    try:
        sender = msg.sender
        callback_data: dict = json.loads(msg.data)
        
        order_number = callback_data.get("order_number")
        prep_time_minutes = callback_data.get("prep_time_minutes")
        
        # Call database function via Supabase RPC
        result = client_ordelo.rpc(
            "handle_restaurant_confirmation",
            {
                "p_order_number": order_number,
                "p_prep_time_minutes": prep_time_minutes
            }
        ).execute()
        
        if result.data:
            await wa.send_message(
                to=sender,
                text=f"✅ Confirmed! Food will be ready in {prep_time_minutes} minutes.\n\nDriver will be dispatched accordingly."
            )
        else:
            await wa.send_message(
                to=sender,
                text="⚠️ This order has already been confirmed or is no longer pending."
            )
    except Exception as e:
        logger.error(f"Error: {e}")
        await wa.send_message(to=msg.sender, text="❌ Error processing confirmation.")
```

**Register Handler** (`watomation/fapp_ordelo_agent.py`):
```python
# Import
from watomation.on_callback_wa_handler import handle_restaurant_confirmation

# Define filter
IS_RESTAURANT_CONFIRMATION = filters.contains("/restaurantConfirmation", ignore_case=False)

# Register
wa.add_handlers(
    handlers.CallbackButtonHandler(
        callback=handle_restaurant_confirmation,
        filters=IS_RESTAURANT_CONFIRMATION
    ),
)
```

**Pattern Elements Used:**
- ✅ Button creation with JSON callback_data
- ✅ Command-based routing (`/restaurantConfirmation`)
- ✅ Callback handler with try/except
- ✅ Supabase RPC call to database function
- ✅ Conditional response based on result
- ✅ Handler registration with filter

---

### ✅ Pattern 3: Configuration with Entity-Specific Fallback

**What:** Support restaurant-specific timeout values, falling back to global default.

**Implementation:**

**SQL Function** (`ordelo_datamodels/jobs_n_functions/job_restaurant_confirmation_timeout.sql`):
```sql
CREATE OR REPLACE FUNCTION job_restaurant_confirmation_timeout(p_rest_ref VARCHAR DEFAULT NULL)
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH timeout_config AS (
    SELECT 
      ds.order_number,
      ds.rest_id,
      COALESCE(
        -- Try restaurant-specific config first
        (SELECT config_value::INTEGER 
         FROM ordelo_config 
         WHERE config_key = SPLIT_PART(ds.order_number, '-', 1) || '_RESTAURANT_CONFIRMATION_TIMEOUT'
         LIMIT 1),
        -- Fallback to global config
        (SELECT config_value::INTEGER 
         FROM ordelo_config 
         WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT'
         LIMIT 1),
        -- Hardcoded fallback
        5
      ) AS timeout_minutes
    FROM delivery_summary ds
    WHERE ds.status = 'restaurant_unconfirmed'
      AND (p_rest_ref IS NULL OR SPLIT_PART(ds.order_number, '-', 1) = p_rest_ref)
  ),
  timed_out_orders AS (
    UPDATE delivery_summary ds
    SET 
      status = 'unassigned',
      rest_confirmed_at = NOW(),
      rest_prep_time_minutes = 25,
      rest_confirmation_method = 'timeout',
      pickup_time = NOW() + INTERVAL '25 minutes'
    FROM timeout_config tc
    WHERE ds.order_number = tc.order_number
      AND ds.status = 'restaurant_unconfirmed'
      AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts))/60) >= tc.timeout_minutes
    RETURNING 
      ds.order_number,
      'Order ' || ds.order_number || ' → timed out after ' || tc.timeout_minutes || ' minutes' AS action
  )
  SELECT action FROM timed_out_orders;
END;
$$ LANGUAGE plpgsql;
```

**Configuration Examples:**
```sql
-- Global default (5 minutes)
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('RESTAURANT_CONFIRMATION_TIMEOUT', '5', 'Default timeout');

-- Restaurant-specific (3 minutes for WREN)
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('WREN_RESTAURANT_CONFIRMATION_TIMEOUT', '3', 'WREN timeout');
```

**Pattern Elements Used:**
- ✅ COALESCE for multi-level fallback
- ✅ Entity-specific config key pattern: `{ENTITY}_KEY`
- ✅ Optional parameter for entity filtering
- ✅ Hardcoded fallback as last resort
- ✅ Type casting (::INTEGER)

---

### ✅ Pattern 4: CTE-Based Data Processing

**What:** Use CTEs to organize multi-step timeout processing logic.

**Implementation:**

```sql
WITH timeout_config AS (
  -- Step 1: Determine timeout value per order
  SELECT order_number, timeout_minutes FROM ...
),
timed_out_orders AS (
  -- Step 2: Update orders that have timed out
  UPDATE delivery_summary ds
  SET status = 'unassigned', ...
  FROM timeout_config tc
  WHERE ... AND time_elapsed >= tc.timeout_minutes
  RETURNING order_number, action
)
-- Step 3: Return action log
SELECT action FROM timed_out_orders;
```

**Pattern Elements Used:**
- ✅ Named CTEs for logical steps
- ✅ CTE chaining (timeout_config → timed_out_orders)
- ✅ RETURNING clause for action logging
- ✅ Final SELECT to return results

---

### ✅ Pattern 5: Idempotent Database Function

**What:** Ensure confirmation can only happen once per order.

**Implementation:**

**SQL Function** (`ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql`):
```sql
CREATE OR REPLACE FUNCTION handle_restaurant_confirmation(
  p_order_number VARCHAR,
  p_prep_time_minutes INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
  v_updated BOOLEAN;
BEGIN
  -- Update only if in correct state
  UPDATE delivery_summary
  SET 
    status = 'unassigned',
    rest_confirmed_at = NOW(),
    rest_prep_time_minutes = p_prep_time_minutes,
    rest_confirmation_method = 'manual',
    pickup_time = NOW() + (p_prep_time_minutes || ' minutes')::INTERVAL
  WHERE order_number = p_order_number
    AND status = 'restaurant_unconfirmed'  -- Idempotency check
  RETURNING TRUE INTO v_updated;
  
  IF v_updated THEN
    -- Success: trigger downstream processing
    PERFORM process_delivery();
    RETURN TRUE;
  ELSE
    -- Already processed or not found
    RETURN FALSE;
  END IF;
END;
$$ LANGUAGE plpgsql;
```

**Pattern Elements Used:**
- ✅ State check in WHERE clause (`status = 'restaurant_unconfirmed'`)
- ✅ RETURNING to capture success/failure
- ✅ Conditional downstream processing
- ✅ Boolean return for caller feedback
- ✅ PERFORM for calling void functions

---

### ✅ Pattern 6: Pydantic Model Extension

**What:** Add new optional fields to existing model without breaking compatibility.

**Implementation:**

**Before** (`ordelo_datamodels/delivery_pymodels.py`):
```python
class DeliverySummary(BaseModel):
    order_number: str = Field(..., max_length=100)
    rest_id: str = Field(..., max_length=12)
    # ... existing fields ...
    status: str
    rest_confirmation_code: int
    cust_confirmation_code: int
    pickup_time: datetime
    pickup_date: date
    dt: date
    dtts: datetime
```

**After:**
```python
class DeliverySummary(BaseModel):
    order_number: str = Field(..., max_length=100)
    rest_id: str = Field(..., max_length=12)
    # ... existing fields ...
    status: str
    rest_confirmation_code: int
    cust_confirmation_code: int
    rest_confirmed_at: Optional[datetime] = None  # NEW
    rest_prep_time_minutes: Optional[int] = None  # NEW
    rest_confirmation_method: Optional[str] = None  # NEW
    pickup_time: datetime
    pickup_date: date
    dt: date
    dtts: datetime
```

**Pattern Elements Used:**
- ✅ Optional[Type] for new fields
- ✅ Default value of None
- ✅ Backward compatibility (existing code still works)
- ✅ Fields match database column names

---

### ✅ Pattern 7: Scheduled Job with Early Exit

**What:** Job runs every minute but exits early if no work to do.

**Implementation:**

```sql
CREATE OR REPLACE FUNCTION job_restaurant_confirmation_timeout(...)
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH timeout_config AS (
    -- Find orders that need processing
    SELECT ... 
    FROM delivery_summary ds
    WHERE ds.status = 'restaurant_unconfirmed'  -- Only pending orders
  ),
  timed_out_orders AS (
    -- Process only if timeout_config has rows
    UPDATE ... FROM timeout_config ...
  )
  SELECT action FROM timed_out_orders;
  -- If no rows in timeout_config, returns empty result (efficient)
END;
$$ LANGUAGE plpgsql;
```

**Scheduling:**
```sql
SELECT cron.schedule(
  'job_restaurant_confirmation_timeout',
  '* * * * *',  -- Every minute
  $$SELECT * FROM job_restaurant_confirmation_timeout()$$
);
```

**Pattern Elements Used:**
- ✅ CTE filters for candidates first
- ✅ UPDATE only processes if CTE has rows
- ✅ No explicit IF check needed (CTE handles it)
- ✅ Returns empty table if no work (efficient)

---

### ✅ Pattern 8: Module Docstring Updates

**What:** Update module docstrings when adding new functions.

**Implementation:**

**Before** (`watomation/routers/delivery_hooks.py`):
```python
"""
Delivery webhook handlers for Ordelo delivery system
    . Processes delivery-related webhook events from database triggers
    . Manages delivery dispatch assignments and inflight tracking
  Functions/Classes:
    . delivery_dispatch_hook - Processes dispatch assignments
    . delivery_inflight_graph_init_hook - Initializes inflight tracking
"""
```

**After:**
```python
"""
Delivery webhook handlers for Ordelo delivery system
    . Processes delivery-related webhook events from database triggers
    . Manages delivery dispatch assignments and inflight tracking
    . Implements restaurant confirmation touchpoint before rider dispatch  # NEW
  Functions/Classes:
    . delivery_dispatch_hook - Processes dispatch assignments
    . delivery_inflight_graph_init_hook - Initializes inflight tracking
    . restaurant_confirmation_request_hook - Sends prep time confirmation request  # NEW
"""
```

**Pattern Elements Used:**
- ✅ Add feature description to bullet list
- ✅ Add new function to Functions/Classes section
- ✅ Keep format consistent
- ✅ Brief, action-oriented descriptions

---

## Summary of Patterns Used

| Pattern | Files Affected | Key Technique |
|---------|---------------|---------------|
| Database-Triggered Webhook | `migrations/*.sql`, `delivery_hooks.py` | Trigger → http_post → FastAPI |
| WhatsApp Callback Buttons | `delivery_hooks.py`, `on_callback_wa_handler.py`, `fapp_ordelo_agent.py` | Button → Callback → RPC |
| Config with Fallback | `job_restaurant_confirmation_timeout.sql` | COALESCE(entity, global, default) |
| CTE Processing | `job_restaurant_confirmation_timeout.sql` | Named CTEs with RETURNING |
| Idempotent Function | `handle_restaurant_confirmation.sql` | State check in WHERE |
| Pydantic Extension | `delivery_pymodels.py` | Optional[Type] = None |
| Scheduled Job | `job_restaurant_confirmation_timeout.sql` | pg_cron with early exit |
| Module Docstrings | All Python files | Bullet list + Functions section |

---

## Lessons Learned

1. **Follow existing patterns** - All patterns were already in use elsewhere in the codebase
2. **Configuration is key** - Entity-specific configs provide flexibility
3. **Idempotency matters** - Always check state before updating
4. **CTEs organize logic** - Multi-step operations are clearer with CTEs
5. **Error handling everywhere** - Try/except in Python, state checks in SQL
6. **Documentation is code** - Module docstrings are mandatory
7. **Test incrementally** - Each pattern can be tested independently

---

## Reusable Template

When implementing a similar feature (entity confirmation, approval workflow, etc.):

1. **Copy SQL trigger pattern** from `restaurant_confirmation_whook()`
2. **Copy FastAPI endpoint pattern** from `restaurant_confirmation_request_hook()`
3. **Copy callback handler pattern** from `handle_restaurant_confirmation()`
4. **Copy timeout job pattern** from `job_restaurant_confirmation_timeout()`
5. **Copy config fallback pattern** from timeout job's COALESCE
6. **Update module docstrings** following the established format

---

**See Also:**
- Full patterns guide: `.specify/AI_PATTERNS_GUIDE.md`
- Quick reference: `.specify/QUICK_PATTERNS_REFERENCE.md`
- Implementation progress: `.specify/design/restaurant_confirmation_implementation_progress.md`
