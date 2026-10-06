-- select * from payment_event;
-- select * from order_customer_event;
-- select id from order_notification_subscription;
-- select * from notification_outbox;
-- select * from delivery_summary where order_number like '%LXGM-20';
SELECT config_key, config_value, updated_at
FROM public.ordelo_config
WHERE config_key IN ('TEST_PAYMENT_REST_REFS', 'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL')
OR config_key LIKE '%\_WEB\_ORDERING\_PAUSED' ESCAPE '\'
OR config_key LIKE '%\_WEB\_MAX\_DISCOUNT\_PERCENT' ESCAPE '\'
ORDER BY config_key;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT,CRMS', 'Restaurants whose orders always use Stripe test (R3.1)')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP;



selEct * from delivery_summary ;
select * from bnat_menu where addons is not null and addons != '[]' and addons like '%step2%' limit 3;

update delivery_summary set pickup_time='2026-10-02 08:55:19.027864+00'
where order_number='ELAS-LXGM-20';

select * from food_order where order_id='LXGM-20';
select * from customer_master where cust_id='447448440754';
select * from customer_master;
select * from restaurant_master where rest_ref='SFCS';
-- SP2 8BJ, 51.0439463, -1.7898225

restaurant_lat, lon - -1.79609677126815
restaurant_lat=51.0717612607721	
restaurant_lon=-1.79609677126815

payload = {
    "total_food_value": 0,
    "restaurant_latitude": 51.0717612607721,
    "restaurant_longitude": -1.79609677126815,
    "customer_latitude": 51.0439463,
    "customer_longitude": -1.7898225,
    "rest_ref": "SFCS",
}


def _call_pricing_service(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call pricing microservice and return parsed JSON on success."""
    url = ms_settings.pricing_url
    headers = {"Content-Type": "application/json"}
    payload["order_number"] = str(uuid.uuid4())
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"Pricing service HTTP error: {http_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Pricing service request error: {req_err}")
    except Exception as err:  # noqa: BLE001 - capture unexpected issues
        logger.exception(f"Unexpected error calling pricing service: {err}")
    return None

    ;
