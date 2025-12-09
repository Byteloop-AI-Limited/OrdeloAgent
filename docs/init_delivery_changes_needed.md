# Changes Needed for init_delivery.sql

**File:** `ordelo_datamodels/jobs_n_functions/init_delivery.sql`

---

## Change 1: Update Status (Line 137)

**Current:**
```sql
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address,
        'unassigned',  -- <-- LINE 137: CHANGE THIS
        v_rest_confirmation_code,
        v_cust_confirmation_code
    );
```

**New:**
```sql
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address,
        'restaurant_unconfirmed',  -- <-- LINE 137: CHANGED
        v_rest_confirmation_code,
        v_cust_confirmation_code
    );
```

---

## Change 2: Comment Out process_delivery() Call (Lines 141-142)

**Current:**
```sql
    );
    -- kick off process_delivery; May be add condition on pickup_time
    PERFORM process_delivery();  -- <-- LINE 142: COMMENT THIS OUT
    RETURN p_order_number;
END;
```

**New:**
```sql
    );
    -- process_delivery will be called after restaurant confirmation
    -- PERFORM process_delivery();  -- <-- LINE 142: COMMENTED OUT
    RETURN p_order_number;
END;
```

---

## Complete Modified Function

Here's the complete function with both changes applied:

```sql
CREATE OR REPLACE FUNCTION public.init_delivery(p_cust_id VARCHAR, p_order_number VARCHAR)
RETURNS VARCHAR AS $$
DECLARE
    v_rest_ref VARCHAR;
    v_rest_id VARCHAR(12);
    v_rest_name TEXT;
    v_rest_lon DOUBLE PRECISION;
    v_rest_lat DOUBLE PRECISION;
    v_rest_address TEXT;
    v_town VARCHAR(255);
    v_customer_name TEXT;
    v_customer_lon DOUBLE PRECISION;
    v_customer_lat DOUBLE PRECISION;
    v_customer_address TEXT;
    v_salt_number INTEGER;
    v_rest_confirmation_code INTEGER;
    v_cust_confirmation_code INTEGER;
BEGIN
    -- Derive rest_ref from order_number
    v_rest_ref := SPLIT_PART(p_order_number, '-', 1);

    -- Fetch restaurant details
    SELECT
        rm.rest_id,
        rm.rest_name,
        rm.lon,
        rm.lat,
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city
    INTO
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town
    FROM restaurant_master rm
    WHERE rm.rest_ref = v_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;

    -- Fetch customer details
    SELECT
        cm.cust_name,
        cm.lon,
        cm.lat,
        TRIM(CONCAT_WS(' ', cm.house_number, cm.building_name, cm.street_name, cm.city, cm.postcode))
    INTO
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address
    FROM customer_master cm
    WHERE cm.cust_id = p_cust_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id;
    END IF;

    -- Fetch salt from config
    SELECT (config_value)::INTEGER
    INTO v_salt_number
    FROM ordelo_config
    WHERE config_key = 'CONFIRMATION_CODE_SALT'
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT';
    END IF;

    -- Generate confirmation codes
    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::INT;
    v_cust_confirmation_code := v_salt_number - v_rest_confirmation_code;

    -- Insert summary record
    INSERT INTO delivery_summary (
        order_number,
        rest_id,
        rest_name,
        rest_lon,
        rest_lat,
        rest_address,
        town,
        customer_id,
        customer_name,
        customer_lon,
        customer_lat,
        customer_address,
        status,
        rest_confirmation_code,
        cust_confirmation_code
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address,
        'restaurant_unconfirmed',  -- CHANGED: was 'unassigned'
        v_rest_confirmation_code,
        v_cust_confirmation_code
    );
    -- process_delivery will be called after restaurant confirmation
    -- PERFORM process_delivery();  -- COMMENTED OUT
    RETURN p_order_number;
END;
$$ LANGUAGE plpgsql;
```

---

## Why These Changes?

1. **Status Change:** Orders now start as `restaurant_unconfirmed` instead of `unassigned`
   - This triggers the restaurant confirmation webhook
   - Prevents immediate dispatch creation
   - Waits for restaurant to confirm prep time

2. **Remove process_delivery() Call:** Don't start dispatch flow immediately
   - `process_delivery()` will be called by `handle_restaurant_confirmation()` after confirmation
   - Or by timeout job after 5 minutes (or custom timeout)
   - This ensures riders are only dispatched when food is ready or nearly ready

---

## Testing After Changes

```sql
-- Test the modified function
SELECT init_delivery('test_customer_id', 'WREN-TEST123');

-- Verify status is restaurant_unconfirmed
SELECT order_number, status, rest_confirmed_at, rest_prep_time_minutes 
FROM delivery_summary 
WHERE order_number = 'WREN-TEST123';

-- Expected result:
-- order_number: WREN-TEST123
-- status: restaurant_unconfirmed
-- rest_confirmed_at: NULL
-- rest_prep_time_minutes: NULL

-- Restaurant should receive WhatsApp message with buttons
-- After clicking button or timeout, status should change to 'unassigned'
```
