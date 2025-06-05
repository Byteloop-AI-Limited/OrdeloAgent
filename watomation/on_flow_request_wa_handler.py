"""
Handles customer address capture flows via WhatsApp.
    . Implements WhatsApp flow request handlers for address capture
    . Provides data exchange and completion logic for the flow
    . Logs and responds to customer address input events
"""

# %%
from pywa_async import WhatsApp
from config import logger
# project modules
from pywa.types.flows import FlowRequest, FlowResponse, FlowRequestActionType, FlowCompletion

# @WhatsApp.on_flow_request("/customer-address-capture")
async def on_customer_address_flow(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    logger.info(request)
    logger.info(request.data)
    
    if request.has_error:
        logger.error("Flow request has error: %s", request.data)
        return FlowResponse(
            data={"acknowledged": True}
        )

    return FlowResponse(
        version=request.version,
        screen="START",
        data={
            "flow_name": "CustomerAddressCapture",
            "customer_name": "John Doe - test",
            "customer_id": "44744123123123",
            "address": "one kingdom street",
            "error_message": "this is error msg",
        },
    )


async def on_customer_address_flow_data_exchange(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    logger.info("Received data exchange request: %s", request.data)
    return FlowResponse(
        version=request.version,
        screen="START",
        error_message="You are already registered. Please login",
        data={
            "customer_name": "I will give you better name - lohith",
        },
    )

# %% ref flow completion
async def on_customer_address_flow_completion(_: WhatsApp, flow: FlowCompletion) -> FlowResponse | None:
    print(flow)
    logger.success(f"Flow {flow.token} just got completed!. Flow data: {flow.response}")