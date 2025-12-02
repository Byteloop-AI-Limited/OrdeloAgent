# %%
from collections import namedtuple
from loguru import logger
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from config import project_settings

REST_MASTER = RestaurantMaster.from_rest_ref("ELAS")
# REST_MASTER = RestaurantMaster.from_rest_ref(project_settings.rest_ref)
logger.info(
    f"Loading restaurant master data: {REST_MASTER.rest_ref} - Admins: {REST_MASTER.get_admins()}"
)


# %%


def get_restaurant_base_url(rest_ref: str) -> str:
    from config import client_ordelo

    rest_ref = rest_ref.upper() + "_APP_URL"
    resp = (
        client_ordelo.table("ordelo_config")
        .select("*")
        .eq("config_key", rest_ref)
        .execute()
    )
    data = (
        resp["data"]
        if isinstance(resp, dict) and "data" in resp
        else resp.data
        if hasattr(resp, "data")
        else None
    )
    if not data or len(data) == 0:
        raise ValueError(f"No restaurant found with rest_ref={rest_ref}")
    # Use the first row
    row = data[0]
    return row["config_value"]


# %%


# Define config for restaurant and webhooks. Config will be  a namedtuple called RestaurantConfig, with fields REST_REF, TYPE, REST_WEBHOOK_URL
RestaurantConfig = namedtuple(
    "RestaurantConfig", ["type", "base_url", "rest_webhook_url"]
)
wren_base_url = get_restaurant_base_url("WREN")
elab_base_url = get_restaurant_base_url("ELAB")
elas_base_url = get_restaurant_base_url("ELAS")
logger.info(f"Wren base url: {wren_base_url}")
logger.info(f"Elab base url: {elab_base_url}")
logger.info(f"Elas base url: {elas_base_url}")

RESTAURANT_CONFIG = {
    "WREN-RIDER-INFLIGHT": RestaurantConfig(
        "rider-event-inflight",
        wren_base_url,
        "rider-event-hooks/rider-inflight",
    ),
    "WREN-RIDER-REST-CC": RestaurantConfig(
        "rider-event-restaurant-cc",
        wren_base_url,
        "rider-event-hooks/on-restaurant-cc",
    ),
    "WREN-RIDER-CUST-CC": RestaurantConfig(
        "rider-event-customer-cc",
        wren_base_url,
        "rider-event-hooks/on-customer-cc",
    ),
    "WREN-RIDER-REST-ENTER": RestaurantConfig(
        "rider-event-restaurant-enter",
        wren_base_url,
        "rider-event-hooks/on-restaurant-enter",
    ),
    "WREN-RIDER-CUST-ENTER": RestaurantConfig(
        "rider-event-customer-enter",
        wren_base_url,
        "rider-event-hooks/on-customer-enter",
    ),
    "WREN-DELIVERY-TIMEDOUT": RestaurantConfig(
        "delivery-timedout",
        wren_base_url,
        "rider-event-hooks/delivery-timedout",
    ),
    # Bytelooop
    "ELAB-RIDER-INFLIGHT": RestaurantConfig(
        "rider-event-inflight",
        elab_base_url,
        "rider-event-hooks/rider-inflight",
    ),
    "ELAB-RIDER-REST-CC": RestaurantConfig(
        "rider-event-restaurant-cc",
        elab_base_url,
        "rider-event-hooks/on-restaurant-cc",
    ),
    "ELAB-RIDER-CUST-CC": RestaurantConfig(
        "rider-event-customer-cc",
        elab_base_url,
        "rider-event-hooks/on-customer-cc",
    ),
    "ELAB-RIDER-REST-ENTER": RestaurantConfig(
        "rider-event-restaurant-enter",
        elab_base_url,
        "rider-event-hooks/on-restaurant-enter",
    ),
    "ELAB-RIDER-CUST-ENTER": RestaurantConfig(
        "rider-event-customer-enter",
        elab_base_url,
        "rider-event-hooks/on-customer-enter",
    ),
    "ELAB-DELIVERY-TIMEDOUT": RestaurantConfig(
        "delivery-timedout",
        elab_base_url,
        "rider-event-hooks/delivery-timedout",
    ),
    # Elas
    "ELAS-RIDER-INFLIGHT": RestaurantConfig(
        "rider-event-inflight",
        elas_base_url,
        "rider-event-hooks/rider-inflight",
    ),
    "ELAS-RIDER-REST-CC": RestaurantConfig(
        "rider-event-restaurant-cc",
        elas_base_url,
        "rider-event-hooks/on-restaurant-cc",
    ),
    "ELAS-RIDER-CUST-CC": RestaurantConfig(
        "rider-event-customer-cc",
        elas_base_url,
        "rider-event-hooks/on-customer-cc",
    ),
    "ELAS-RIDER-REST-ENTER": RestaurantConfig(
        "rider-event-restaurant-enter",
        elas_base_url,
        "rider-event-hooks/on-restaurant-enter",
    ),
    "ELAS-RIDER-CUST-ENTER": RestaurantConfig(
        "rider-event-customer-enter",
        elas_base_url,
        "rider-event-hooks/on-customer-enter",
    ),
    "ELAS-DELIVERY-TIMEDOUT": RestaurantConfig(
        "delivery-timedout",
        elas_base_url,
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
    return config.base_url + "/" + config.rest_webhook_url


# %%
# get_webhook_url("ELAB", "delivery-timedout")
