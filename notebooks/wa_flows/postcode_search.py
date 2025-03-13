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
from pywa.errors import FlowUpdatingError
# %%
POST_CODE_SEARCH = FlowJSON(
    version=utils.Version.FLOW_JSON,
    data_api_version=utils.Version.FLOW_DATA_API,
    routing_model={
        "START": ["ADDRESS"],
    },
    screens=[
        Screen(
            id="START",
            title="Search Address",
            data=[
                flow_name := ScreenData(key='flow_name', example='Customer Address Capture'),
                customer_id := ScreenData(key='customer_id', example='447234123412'),
                postcode_init := ScreenData(key='postcode_init', example='BR6 6DN'),
                ip_postcode := ScreenData(key='ip_postcode', example="1 kingdom street"),
            ],
            layout=Layout(
                children=[
                    TextHeading(
                        text=FlowStr("Search your address"),
                    ),
                    TextSubheading(text="Search your address"),
                    Form(
                        name="address_search",
                        children=[
                            ip_postcode := TextInput(
                                name="search_query",
                                label="Enter your postcode or street name",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=postcode_init.ref,
                            ),
                            Footer(
                                label="Search",
                                on_click_action=Action(
                                    name=FlowActionType.DATA_EXCHANGE,
                                    payload={
                                        "flow_name": flow_name.ref,
                                        "ip_postcode": ip_postcode.ref
                                    },
                                ),
                            ),
                        ]
                    ),
                ]
            ),
        ),
        Screen(
            id="ADDRESS",
            title="Update Address",
            data=[
                flow_name := ScreenData(key='flow_name', example='Customer Address Capture'),
                customer_id := ScreenData(key='customer_id', example='447234123412'),
                house_number := ScreenData(key='house_number', example="42"),
                building := ScreenData(key='building', example="Maple Court"),
                street := ScreenData(key='street', example="Kingdom Street"),
                city := ScreenData(key='city', example="London"),
                postcode := ScreenData(key='postcode', example="BR6 6DN"),
                # error_message := ScreenData(key='error_message', example="this is error msg")
            ],
            terminal=True,
            layout=Layout(
                children=[
                    TextSubheading(text="Complete your address details"),
                    Form(
                        name="address_details",
                        children=[
                            house_number_input := TextInput(
                                name="house_number",
                                label="House/Flat Number",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=house_number.ref,
                                # error_message=error_message.ref,
                            ),
                            building_input := TextInput(
                                name="building",
                                label="Building",
                                input_type=InputType.TEXT,
                                required=False,
                                init_value=building.ref,
                            ),
                            street_input := TextInput(
                                name="street",
                                label="Street",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=street.ref,
                            ),
                            city_input := TextInput(
                                name="city",
                                label="City/Town",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=city.ref,
                            ),
                            postcode := TextInput(
                                name="postcode",
                                label="Postcode",
                                input_type=InputType.TEXT,
                                required=False,
                                enabled=False,
                                init_value=postcode.ref,
                            ),
                            Footer(
                                label="Update",
                                on_click_action=Action(
                                    name=FlowActionType.COMPLETE,
                                    payload={
                                        "flow_name": flow_name.ref,
                                        "customer_id": customer_id.ref,
                                        "house_number": house_number_input.ref,
                                        "building": building_input.ref,
                                        "street": street_input.ref,
                                        "city": city_input.ref,
                                        "postcode": postcode.ref
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

FLOW_ID = '955259853427256'
# %% Create a flow

# flow_id = wa.create_flow(
#     name="Postcode Search",
#     categories=[FlowCategory.SIGN_IN, FlowCategory.SIGN_UP],
# )

# wa.update_flow_metadata(
#     flow_id=FLOW_ID,
#     endpoint_uri="https://agent.orderlo.app/sign-up-flow1",
# )
FLOW_ID = 955259853427256


# %% UPDATE FLOW JSON
try:
    success, validation_errors = wa.update_flow_json(
        flow_id=FLOW_ID,
        flow_json=POST_CODE_SEARCH,
    )
    print(success, validation_errors)
except FlowUpdatingError as e:
    print("Flow updating failed")
    print(validation_errors)

# %% GET FLOW DATA 
wa.get_flow(flow_id=FLOW_ID)

# %% Send draft flow:
from pywa.types.flows import FlowActionType, FlowStatus
from pywa.types import FlowButton, Button


wa.send_message(
    to="447448440754",
    # to="447448440754",
    # to="447446933210",
    text="Update your address details",
    buttons=FlowButton(
        title="Update Details",
        flow_id=FLOW_ID,  # The `static_flow` flow id from above
        flow_token="123",
        mode=FlowStatus.DRAFT,
        flow_action_type=FlowActionType.NAVIGATE,
        flow_action_screen="START", # The screen id to open when the user clicks the button
        flow_action_payload={
            "flow_name": "Postcode Search",
            "customer_id": "44744123123123",
            "postcode_init": "BR6 6DN"
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
