# %%
from collections import namedtuple

# Define config for restaurant and webhooks. Config will be  a namedtuple called RestaurantConfig, with fields REST_REF, TYPE, REST_WEBHOOK_URL
RestaurantConfig = namedtuple(
    "RestaurantConfig", ["type", "base_url", "rest_webhook_url"]
)

RESTAURANT_CONFIG = {
    "WREN-RIDER-INFLIGHT": RestaurantConfig(
        "rider-event-inflight",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/rider-inflight",
    ),
    "WREN-RIDER-REST-CC": RestaurantConfig(
        "rider-event-restaurant-cc",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/on-restaurant-cc",
    ),
    "WREN-RIDER-CUST-CC": RestaurantConfig(
        "rider-event-customer-cc",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/on-customer-cc",
    ),
    "WREN-RIDER-REST-ENTER": RestaurantConfig(
        "rider-event-restaurant-enter",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/on-restaurant-enter",
    ),
    "WREN-RIDER-CUST-ENTER": RestaurantConfig(
        "rider-event-customer-enter",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/on-customer-enter",
    ),
    "WREN-DELIVERY-TIMEDOUT": RestaurantConfig(
        "delivery-timedout",
        "https://elaib-agent.ordelo.app/",
        "rider-event-hooks/delivery-timedout",
    ),
    # Bytelooop
    "ELAB-RIDER-INFLIGHT": RestaurantConfig(
        "rider-event-inflight",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/rider-inflight",
    ),
    "ELAB-RIDER-REST-CC": RestaurantConfig(
        "rider-event-restaurant-cc",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/on-restaurant-cc",
    ),
    "ELAB-RIDER-CUST-CC": RestaurantConfig(
        "rider-event-customer-cc",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/on-customer-cc",
    ),
    "ELAB-RIDER-REST-ENTER": RestaurantConfig(
        "rider-event-restaurant-enter",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/on-restaurant-enter",
    ),
    "ELAB-RIDER-CUST-ENTER": RestaurantConfig(
        "rider-event-customer-enter",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/on-customer-enter",
    ),
    "ELAB-DELIVERY-TIMEDOUT": RestaurantConfig(
        "delivery-timedout",
        "https://live-track.bytelooop.ai/",
        "rider-event-hooks/delivery-timedout",
    ),
}


# %%
def get_restaurant_config(rest_ref: str, type: str) -> RestaurantConfig:
    key = f"{rest_ref.upper()}-{type.upper()}"
    config = RESTAURANT_CONFIG.get(key, None)
    if config is None:
        raise ValueError(f"Config for {key} not found")
    return config


# %% get_webhook_url
def get_webhook_url(rest_ref: str, type: str) -> str:
    config = get_restaurant_config(rest_ref, type)
    return config.base_url + config.rest_webhook_url


# %%
# get_webhook_url("ELAB", "delivery-timedout")
