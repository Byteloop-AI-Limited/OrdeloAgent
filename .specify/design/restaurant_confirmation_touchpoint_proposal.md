# Restaurant Confirmation Touchpoint - Design Proposal

**Version:** 1.0.0  
**Date:** 2025-11-18  
**Status:** DRAFT - Awaiting Review

---

## Executive Summary

This proposal introduces a new touchpoint in the delivery workflow where restaurants confirm food preparation time **before** rider dispatch begins. This prevents premature rider assignments and ensures riders are only dispatched when food is actually ready or nearly ready.

---

## Current Workflow Analysis

### Existing Flow (from code analysis)

```
1. init_delivery() 
   ↓ Creates delivery_summary with status='unassigned'
   ↓ Calls process_delivery() eagerly
   
2. process_delivery() (runs every 5s via cron)
   ↓ Creates delivery_detail records per vehicle type
   ↓ Status remains 'unassigned'
   
3. job_create_dispatch() (runs every 5s via cron)
   ↓ Creates delivery_dispatch records
   ↓ Triggers webhook → sends WhatsApp to riders
   
4. Rider accepts → delivery_inflight created
   ↓ Agent graph initialized
   ↓ Rider receives instructions
```

### Problem Statement

Currently, riders are dispatched immediately after order creation, regardless of whether the restaurant can actually prepare the food in time. This leads to:
- Riders waiting at restaurants
- Poor rider experience
- Inefficient resource allocation
- Potential delivery delays

---

## Proposed Solution

### Option A: New Status-Based Flow (RECOMMENDED)

Introduce a new status `restaurant_unconfirmed` that gates the dispatch process.

#### Modified Workflow

```
1. init_delivery() 
   ↓ Creates delivery_summary with status='restaurant_unconfirmed'
   ↓ Does NOT call process_delivery() yet
   ↓ Triggers restaurant_confirmation_whook()
   
2. Restaurant receives WhatsApp message
   ↓ Selects prep time: 5min / 15min / 25min
   ↓ OR times out after 5 minutes
   
3. Confirmation received/timeout
   ↓ Updates delivery_summary:
      - status → 'unassigned'
      - rest_confirmed_at → timestamp
      - rest_prep_time_minutes → selected value
      - pickup_time → calculated based on prep time
   ↓ Calls process_delivery()
   
4. Normal flow continues (process_delivery → job_create_dispatch → etc.)
```

#### Schema Changes to `delivery_summary`

```sql
ALTER TABLE delivery_summary 
  -- Modify status CHECK constraint
  DROP CONSTRAINT delivery_summary_status_check,
  ADD CONSTRAINT delivery_summary_status_check 
    CHECK (status IN (
      'restaurant_unconfirmed',  -- NEW
      'unassigned', 
      'timedout', 
      'assigned', 
      'completed'
    ));

-- Add new columns
ALTER TABLE delivery_summary
  ADD COLUMN rest_confirmed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN rest_prep_time_minutes INTEGER,
  ADD COLUMN rest_confirmation_method VARCHAR(20) 
    CHECK (rest_confirmation_method IN ('manual', 'timeout', NULL));
```

#### New Database Functions Required

**1. Restaurant Confirmation Webhook Function**
```sql
CREATE OR REPLACE FUNCTION restaurant_confirmation_whook()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
  response json;
BEGIN
  -- Only trigger for new restaurant_unconfirmed orders
  IF NEW.status = 'restaurant_unconfirmed' THEN
    
    -- Build payload
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'created_at', NEW.dtts
    ) INTO webhook_payload;
    
    -- Get webhook URL from config
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
    
    -- Make HTTP POST
    response := (
      SELECT content
      FROM http_post(
        webhook_url,
        webhook_payload::text,
        'application/json'
      )
    );
    
    RAISE NOTICE 'Restaurant confirmation request sent: %', response;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER trigger_restaurant_confirmation_request
AFTER INSERT ON delivery_summary
FOR EACH ROW
WHEN (NEW.status = 'restaurant_unconfirmed')
EXECUTE FUNCTION restaurant_confirmation_whook();
```

**2. Restaurant Confirmation Timeout Job**
```sql
CREATE OR REPLACE FUNCTION job_restaurant_confirmation_timeout()
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH timeout_config AS (
    SELECT config_value::INTEGER AS timeout_minutes
    FROM ordelo_config
    WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT'
    LIMIT 1
  ),
  timed_out_orders AS (
    UPDATE delivery_summary ds
    SET 
      status = 'unassigned',
      rest_confirmed_at = NOW(),
      rest_prep_time_minutes = 25,  -- Default to max time
      rest_confirmation_method = 'timeout',
      pickup_time = NOW() + INTERVAL '25 minutes'
    FROM timeout_config tc
    WHERE ds.status = 'restaurant_unconfirmed'
      AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts))/60) >= tc.timeout_minutes
    RETURNING 
      ds.order_number,
      'Order ' || ds.order_number || ' → restaurant confirmation timed out, defaulted to 25min' AS action
  )
  SELECT to_action FROM timed_out_orders to;
END;
$$ LANGUAGE plpgsql;

-- Schedule via pg_cron (runs every minute)
SELECT cron.schedule(
  'job_restaurant_confirmation_timeout',
  '* * * * *',  -- Every minute
  $$SELECT * FROM job_restaurant_confirmation_timeout()$$
);
```

**3. Restaurant Confirmation Handler Function**
```sql
CREATE OR REPLACE FUNCTION handle_restaurant_confirmation(
  p_order_number VARCHAR,
  p_prep_time_minutes INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
  v_updated BOOLEAN;
BEGIN
  -- Validate prep time
  IF p_prep_time_minutes NOT IN (5, 15, 25) THEN
    RAISE EXCEPTION 'Invalid prep time: %. Must be 5, 15, or 25 minutes', p_prep_time_minutes;
  END IF;
  
  -- Update delivery_summary
  UPDATE delivery_summary
  SET 
    status = 'unassigned',
    rest_confirmed_at = NOW(),
    rest_prep_time_minutes = p_prep_time_minutes,
    rest_confirmation_method = 'manual',
    pickup_time = NOW() + (p_prep_time_minutes || ' minutes')::INTERVAL
  WHERE order_number = p_order_number
    AND status = 'restaurant_unconfirmed'
  RETURNING TRUE INTO v_updated;
  
  IF v_updated THEN
    -- Trigger process_delivery for this order
    PERFORM process_delivery();
    RETURN TRUE;
  ELSE
    RETURN FALSE;
  END IF;
END;
$$ LANGUAGE plpgsql;
```

#### New FastAPI Endpoint Required

```python
# In watomation/routers/delivery_hooks.py

@router.post("/restaurant-confirmation-request")
async def restaurant_confirmation_request_hook(
    payload: dict = Depends(get_payload),
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Webhook triggered when a new order needs restaurant confirmation.
    Sends WhatsApp message to restaurant with prep time options.
    
    Payload structure:
    {
        "order_number": "REST-12345",
        "rest_id": "rest_001",
        "rest_name": "Restaurant Name",
        "created_at": "2025-11-18T14:00:00Z"
    }
    """
    try:
        order_number = payload.get("order_number")
        rest_id = payload.get("rest_id")
        rest_name = payload.get("rest_name")
        
        # Get restaurant contact from restaurant_master
        restaurant = client_ordelo.table("restaurant_master")\
            .select("admins")\
            .eq("rest_id", rest_id)\
            .single()\
            .execute()
        
        if not restaurant.data or not restaurant.data.get("admins"):
            logger.error(f"No admin contacts found for restaurant {rest_id}")
            return {"status": "error", "message": "No restaurant contacts"}
        
        # Get first admin contact
        admin_phone = restaurant.data["admins"][0]
        
        # Create callback payloads for each time option
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
        
        logger.info(f"Restaurant confirmation request sent for order {order_number}")
        return {"status": "success", "order_number": order_number}
        
    except Exception as e:
        logger.error(f"Error in restaurant_confirmation_request_hook: {e}")
        return {"status": "error", "message": str(e)}
```

#### New WhatsApp Callback Handler

```python
# In watomation/on_callback_wa_handler.py

async def handle_restaurant_confirmation(
    callback_data: dict,
    sender: str,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Handles restaurant confirmation callback from WhatsApp buttons.
    
    Callback data structure:
    {
        "command": "/restaurantConfirmation",
        "order_number": "REST-12345",
        "prep_time_minutes": 15
    }
    """
    try:
        order_number = callback_data.get("order_number")
        prep_time_minutes = callback_data.get("prep_time_minutes")
        
        # Call database function to update
        result = client_ordelo.rpc(
            "handle_restaurant_confirmation",
            {
                "p_order_number": order_number,
                "p_prep_time_minutes": prep_time_minutes
            }
        ).execute()
        
        if result.data:
            await _async_wa_client.send_message(
                to=sender,
                text=f"✅ Confirmed! Food will be ready in {prep_time_minutes} minutes.\n\nDriver will be dispatched accordingly."
            )
            logger.info(f"Restaurant confirmed {prep_time_minutes}min for order {order_number}")
        else:
            await _async_wa_client.send_message(
                to=sender,
                text="⚠️ This order has already been confirmed or is no longer pending."
            )
            
    except Exception as e:
        logger.error(f"Error handling restaurant confirmation: {e}")
        await _async_wa_client.send_message(
            to=sender,
            text="❌ Error processing confirmation. Please contact support."
        )
```

#### Configuration Updates

Add to `ordelo_config` table:
```sql
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES 
  ('RESTAURANT_CONFIRMATION_TIMEOUT', '5', 'Minutes to wait for restaurant confirmation before defaulting to max prep time'),
  ('DEFAULT_PREP_TIME_MINUTES', '25', 'Default prep time when restaurant times out');
```

#### Pydantic Model Updates

```python
# In ordelo_datamodels/delivery_pymodels.py

class DeliverySummary(BaseModel):
    order_number: str = Field(..., max_length=100)
    rest_id: str = Field(..., max_length=12)
    rest_name: str
    rest_lon: float
    rest_lat: float
    rest_address: str
    town: str = Field(..., max_length=255)
    customer_id: str = Field(..., max_length=50)
    customer_name: str
    customer_lon: float
    customer_lat: float
    customer_address: str
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

#### Modified `init_delivery()` Function

```sql
-- Key changes in init_delivery.sql
-- Line 137: Change status from 'unassigned' to 'restaurant_unconfirmed'
-- Line 141-142: Comment out or conditionally call process_delivery()

-- Before:
    status = 'unassigned',
    ...
    PERFORM process_delivery();

-- After:
    status = 'restaurant_unconfirmed',
    ...
    -- process_delivery() will be called after restaurant confirmation
```

---

## Option B: Separate Confirmation Table (Alternative)

Create a dedicated `restaurant_confirmation` table to track confirmation state separately.

### Schema

```sql
CREATE TABLE restaurant_confirmation (
    order_number VARCHAR(100) PRIMARY KEY REFERENCES delivery_summary(order_number),
    rest_id VARCHAR(12) NOT NULL,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP WITH TIME ZONE,
    prep_time_minutes INTEGER CHECK (prep_time_minutes IN (5, 15, 25)),
    confirmation_method VARCHAR(20) CHECK (confirmation_method IN ('manual', 'timeout')),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'confirmed', 'timed_out')),
    FOREIGN KEY (rest_id) REFERENCES restaurant_master(rest_id)
);

CREATE INDEX idx_rest_confirmation_status ON restaurant_confirmation(status);
CREATE INDEX idx_rest_confirmation_requested_at ON restaurant_confirmation(requested_at);
```

### Pros & Cons

**Option A (Status-Based) - RECOMMENDED**
- ✅ Simpler implementation
- ✅ Follows existing pattern (status transitions)
- ✅ Fewer tables to manage
- ✅ Easier to query and understand
- ✅ Maintains single source of truth in delivery_summary
- ❌ Adds columns to already-wide table

**Option B (Separate Table)**
- ✅ Cleaner separation of concerns
- ✅ Easier to add more confirmation-related fields later
- ✅ Better for audit trail
- ❌ More complex joins required
- ❌ Additional table to maintain
- ❌ Potential sync issues between tables

---

## Implementation Checklist

### Phase 1: Database Layer
- [ ] Add new columns to `delivery_summary` table
- [ ] Update status CHECK constraint
- [ ] Create `restaurant_confirmation_whook()` function
- [ ] Create trigger for restaurant confirmation request
- [ ] Create `job_restaurant_confirmation_timeout()` function
- [ ] Schedule timeout job via pg_cron
- [ ] Create `handle_restaurant_confirmation()` function
- [ ] Add configuration values to `ordelo_config`
- [ ] Update `init_delivery()` to use new status
- [ ] Write migration script

### Phase 2: Application Layer
- [ ] Update `DeliverySummary` Pydantic model
- [ ] Create `/restaurant-confirmation-request` endpoint
- [ ] Create restaurant confirmation callback handler
- [ ] Register callback handler in WhatsApp client
- [ ] Update module docstrings

### Phase 3: Testing
- [ ] Unit tests for database functions
- [ ] Integration tests for webhook flow
- [ ] Test timeout scenario
- [ ] Test manual confirmation (5/15/25 min)
- [ ] Test edge cases (duplicate confirmations, invalid times)
- [ ] Load testing for concurrent orders

### Phase 4: Monitoring & Rollout
- [ ] Add logging for confirmation events
- [ ] Create dashboard metrics (confirmation rate, avg response time)
- [ ] Gradual rollout to subset of restaurants
- [ ] Monitor timeout rate
- [ ] Gather restaurant feedback

---

## Data Flow Diagram

```
┌─────────────────┐
│  Order Created  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  init_delivery()            │
│  - Creates delivery_summary │
│  - status='restaurant_      │
│    unconfirmed'             │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  DB Trigger Fires           │
│  restaurant_confirmation_   │
│  whook()                    │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  FastAPI Webhook            │
│  /restaurant-confirmation-  │
│  request                    │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  WhatsApp Message Sent      │
│  to Restaurant Admin        │
│  [5min] [15min] [25min]     │
└────────┬────────────────────┘
         │
         ├─────────────────────┐
         │                     │
         ▼                     ▼
┌──────────────────┐  ┌───────────────────┐
│ Restaurant       │  │ 5 Min Timeout     │
│ Clicks Button    │  │ (pg_cron job)     │
└────────┬─────────┘  └─────────┬─────────┘
         │                      │
         ▼                      ▼
┌─────────────────────────────────────────┐
│  handle_restaurant_confirmation()       │
│  - Updates delivery_summary             │
│  - status → 'unassigned'                │
│  - Sets prep_time_minutes               │
│  - Calculates pickup_time               │
│  - Calls process_delivery()             │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Normal Dispatch Flow       │
│  - process_delivery()       │
│  - job_create_dispatch()    │
│  - Rider notification       │
└─────────────────────────────┘
```

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Restaurant doesn't respond | High | 5-minute timeout with default 25min prep time |
| WhatsApp message delivery failure | Medium | Retry logic + fallback to default time |
| Concurrent confirmation attempts | Low | Database constraints + idempotency checks |
| Increased order processing time | Medium | Async webhook processing + background tasks |
| Restaurant confusion about options | Medium | Clear messaging + training materials |

---

## Performance Considerations

1. **Database Impact**
   - New columns are nullable, minimal storage overhead
   - New index on status will help timeout job performance
   - Timeout job runs every minute (lightweight query)

2. **API Impact**
   - New webhook endpoint (async, non-blocking)
   - WhatsApp message sending (async)
   - Minimal latency added to order creation

3. **Scalability**
   - Pattern already proven with existing webhooks
   - Timeout job can be optimized with partial indexes
   - Can batch timeout processing if needed

---

## Alternative Approaches Considered

### 1. Restaurant Pre-Configuration
Store default prep times per restaurant and skip confirmation.
- **Rejected:** Less flexible, doesn't account for kitchen capacity variations

### 2. Predictive Model
Use ML to predict prep time based on order size, time of day, etc.
- **Rejected:** Adds complexity, still needs fallback mechanism

### 3. Continuous Polling
Restaurant updates prep status continuously.
- **Rejected:** Too much friction for restaurants

---

## Success Metrics

- **Confirmation Rate:** % of orders confirmed manually (target: >70%)
- **Average Response Time:** Time from request to confirmation (target: <2 min)
- **Timeout Rate:** % of orders that timeout (target: <30%)
- **Rider Wait Time:** Time riders spend waiting at restaurants (target: reduce by 50%)
- **Order Completion Time:** End-to-end delivery time (target: maintain or improve)

---

## Questions for Review

1. **Status Naming:** Is `restaurant_unconfirmed` clear enough, or should it be `pending_restaurant_confirmation`?

2. **Timeout Duration:** Is 5 minutes appropriate, or should it be configurable per restaurant?

3. **Default Prep Time:** Should we default to 25 minutes on timeout, or use a restaurant-specific default?

4. **Notification Strategy:** Should we send a reminder to the restaurant after 3 minutes if no response?

5. **Backward Compatibility:** Do we need to support the old flow for certain restaurants during transition?

6. **Prep Time Options:** Are 5/15/25 minutes the right intervals, or should we offer more granularity?

---

## Recommendation

**Proceed with Option A (Status-Based Flow)** for the following reasons:

1. Aligns with existing architecture patterns
2. Minimal schema changes
3. Leverages proven webhook + trigger pattern
4. Easier to test and debug
5. Lower maintenance overhead
6. Faster implementation timeline

**Estimated Implementation Time:** 3-5 days
- Day 1: Database layer + migrations
- Day 2: FastAPI endpoints + handlers
- Day 3: Testing + bug fixes
- Day 4-5: Integration testing + documentation

---

## Next Steps

1. **Review this proposal** with the team
2. **Answer open questions** above
3. **Create test plan** with specific scenarios
4. **Set up staging environment** for testing
5. **Begin Phase 1 implementation** after approval

---

**Document Owner:** Cascade AI  
**Reviewers:** [To be assigned]  
**Approval Required From:** [To be assigned]
