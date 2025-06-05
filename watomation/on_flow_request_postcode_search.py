"""
Handles postcode search flows via WhatsApp.
    . Implements WhatsApp flow request handlers for postcode search
    . Performs address lookup and builds flow responses
    . Integrates with external address resolver service
"""

# %%
from pywa_async import WhatsApp
from config import logger
# project modules
from pywa.types.flows import FlowRequest, FlowResponse, FlowRequestActionType, FlowCompletion
from utils_common.maps_service import address_resolver

# %% 

async def on_pc_search_init(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    logger.info("postcode search init")
    
    if request.has_error:
        logger.error("Flow request has error: %s", request.data)
        return FlowResponse(
            data={"acknowledged": True}
        )

    return FlowResponse(
        version=request.version,
        screen="START",
        data={
            "flow_name": "PostcodeSearch",
            "customer_id": "44744123123123",
            "postcode_init": "BR6 6DN",
            "ip_postcode": "1 kingdom street",
        },
    )


async def on_ip_pc(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    ip_postcode = request.data.get("ip_postcode")
    logger.info(f"IP postcode: {ip_postcode}")
    
    address = address_resolver.get_address_from_postcode(ip_postcode)
    logger.info(f"Address: {address}")
    
    if address.building_name is None:
        address.building_name = ""
    
    if address.house_number is None:
        address.house_number = ""

    if address.street_name is None:
        address.street_name = ""

    if address.city is None:
        return FlowResponse(
            version=request.version,
            screen="ADDRESS",
            error_message="postcode not found",
        )
    
    return FlowResponse(
        version=request.version,
        screen="ADDRESS",
        data={
            "flow_name": "PostcodeSearch",
            "customer_id": "44744123123123",
            "house_number": address.house_number,
            "building": address.building_name,
            "street": address.street_name,
            "city": address.city,
            "postcode": address.postcode,
        },
    )

# %%
