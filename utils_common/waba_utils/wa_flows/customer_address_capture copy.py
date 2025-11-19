# %%
from pywa import utils
from pywa.types.flows import (
    FlowJSON,
    FlowStr,
    Screen,
    ScreenData,
    Form,
    Footer,
    Layout,
    Action,
    Next,
    NextType,
    FlowActionType,
    ComponentRef,
    InputType,
    TextHeading,
    TextSubheading,
    TextInput,
    OptIn,
    EmbeddedLink,
    RichText,
    ChipsSelector,
    DataSource,
    PhotoPicker,
    PhotoSource,
    Dropdown,
    OpenUrlAction,
    CompleteAction
)

CUSTOMER_ADDRESS_CAPTURE = FlowJSON(
    version=utils.Version.FLOW_JSON,
    data_api_version=utils.Version.FLOW_DATA_API,
    routing_model={
        "START": [],
    },
    screens=[
        Screen(
            id="START",
            title="Home",
            data=[
                flow_name := ScreenData(key='flow_name', example='Customer Address Capture'),
                customer_name := ScreenData(key='customer_name', example='John Doe'),
                customer_id := ScreenData(key='customer_id', example='447234123412'),
                address := ScreenData(key='address', example="1 kingdom street, br66dn"),
                error_message := ScreenData(key='error_message', example="this is error msg")
            ],
            terminal=True,
            layout=Layout(
                children=[
                    TextHeading(
                        text=FlowStr("Welcome to Ordelo master: {user_name}", user_name=customer_name.ref),
                    ),
                    TextSubheading(text="Update your details"),
                    Form(
                        name="address_detail",
                        children=[
                            customer_name := TextInput(
                                name="customer_name",
                                label="Name",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=customer_name.ref,
                                error_message=error_message.ref,
                            ),
                            customer_id := TextInput(
                                name="customer_id",
                                label="Phone Number",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=customer_id.ref,
                            ),
                            address := TextInput(
                                name="address",
                                label="Address",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=address.ref,
                            ),
                            # Data exchange
                            # Footer(
                            #     label="Done",
                            #     on_click_action=Action(
                            #         name=FlowActionType.DATA_EXCHANGE,
                            #         payload={
                            #             "customer_name": customer_name.ref,
                            #             "customer_id": customer_id.ref,
                            #             "address": address.ref
                            #         },
                            #     )
                            # ),
                            # Complete action 
                            Footer(
                                label="Update",
                                on_click_action=CompleteAction(
                                    payload={
                                        "flow_name": flow_name.ref,
                                        "customer_name": customer_name.ref,
                                        "customer_id": customer_id.ref,
                                        "address": address.ref
                                    },
                                ),
                            ),
                        ]
                    ),
                ]
            ),
        )
    ]
)

# %%
from config import waba_business_settings
from pywa import WhatsApp
from pywa.types import FlowCategory

wa = WhatsApp(
            token=waba_business_settings.token,
            business_account_id=waba_business_settings.account_id,
            verify_token=waba_business_settings.verify_token,
            phone_id=waba_business_settings.phone_id
        )

FLOW_ID = '1814859459306906'
# %% Create a flow

# flow_id = wa.create_flow(
#     name="Customer Address Capture",
#     categories=[FlowCategory.SIGN_IN, FlowCategory.SIGN_UP],
# )

# wa.update_flow_metadata(
#     flow_id=FLOW_ID,
#     endpoint_uri="https://agent.orderlo.app/sign-up-flow1",
# )
FLOW_ID = 1814859459306906


# %% UPDATE FLOW JSON

from pywa.errors import FlowUpdatingError

try:
    success, validation_errors = wa.update_flow_json(
        flow_id=FLOW_ID,
        flow_json=CUSTOMER_ADDRESS_CAPTURE,
    )
    print(success, validation_errors)
except FlowUpdatingError as e:
    print("Flow updating failed")
    print(validation_errors)


# %% GET FLOW DATA 
wa.get_flow(flow_id=FLOW_ID)

# %% Send draft flow:
from pywa.types.flows import FlowActionType, FlowStatus
from pywa.types import FlowButton

wa.send_message(
    to="447448440754",
    # to="447448440754",
    # to="447446933210",
    text="Update your details",
    buttons=FlowButton(
        title="Update Details",
        flow_id=FLOW_ID,  # The `static_flow` flow id from above
        flow_token="123",
        mode=FlowStatus.DRAFT,
        flow_action_type=FlowActionType.NAVIGATE,
        flow_action_screen="START", # The screen id to open when the user clicks the button
        flow_action_payload={
            "flow_name": "CustomerAddressCapture",
            "customer_name": "10gan - works",
            "customer_id": "44744123123123",
            "address": "one kingdom street",
            "error_message": "this is error msg",
        }
    )
)

# %%
wa.send_message(
    to="447448440754",
    # to="447448440754",
    # to="447446933210",
    text="Update your details"
)
