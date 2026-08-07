SELECT
    thread_id,
    checkpoint_id,
    checkpoint -> 'channel_values' AS state,
    checkpoint -> 'channel_values' -> 'retain_thread' AS retain_thread,
    checkpoint -> 'channel_values' -> 'customer_address' -> 'street_name' AS custAddress
FROM checkpoints
WHERE thread_id = 'ELAS-0277c955-5cdc-47cd-bf60-a629a50cd69f'
  AND checkpoint_ns = ''
ORDER BY checkpoint_id DESC
LIMIT 1;

-- {"wa_name": "Rahul", "rest_ref": "sfcs", "active_agent": "triage_agent", "ask_for_consent": false, "min_order_value": 16.0, "is_outside_delivery_area": false, "is_delivery_address_confirmed": true}
-- 
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (
    SELECT thread_id FROM checkpoints WHERE checkpoint_ns = ''
)
ORDER BY thread_id;