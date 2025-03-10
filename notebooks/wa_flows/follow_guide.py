# %%
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


# %%
flow_id = await wa.create_flow(
    name="OrdeloFlow",
    categories=[FlowCategory.CUSTOMER_SUPPORT, FlowCategory.SURVEY]
)
print(wa.get_flow(flow_id))
# %% 
FLOW_ID = 654860316950174
# %%
print(wa.get_flow(FLOW_ID))

# %% Create dynamic flow
# from pywa.types import FlowButton, FlowActionType, FlowStatus, FlowJSON, Screen, ScreenData, Layout, LayoutType, Form, TextInput, InputType, Footer, CompleteAction
from pywa.types.flows import Screen, FlowJSON, ScreenData, Layout, LayoutType, Form, TextInput, InputType, Footer, CompleteAction
from pywa import utils

dynamic_flow = FlowJSON(
    version=utils.Version.FLOW_JSON,
    data_api_version=utils.Version.FLOW_DATA_API,
    routing_model={},
    screens=[
        Screen(
            id="SIGN_UP",
            title="Orderlo Sign Up",
            terminal=True,
            data=[
                first_name_helper_text := ScreenData(key="first_name_helper_text", example="Enter your first name"),
                is_last_name_required := ScreenData(key="is_last_name_required", example=True),
                is_email_enabled := ScreenData(key="is_email_enabled", example=False),
            ],
            layout=Layout(
                type=LayoutType.SINGLE_COLUMN,
                children=[
                    Form(
                        name="form",
                        children=[
                            first_name := TextInput(
                                name="first_name",
                                label="First Name",
                                input_type=InputType.TEXT,
                                required=True,
                                helper_text=first_name_helper_text.ref,
                            ),
                            last_name := TextInput(
                                name="last_name",
                                label="Last Name",
                                input_type=InputType.TEXT,
                                required=is_last_name_required.ref,
                            ),
                            email := TextInput(
                                name="email",
                                label="Email Address",
                                input_type=InputType.EMAIL,
                                enabled=is_email_enabled.ref,
                            ),
                            Footer(
                                label="Done",
                                on_click_action=CompleteAction(
                                    payload={
                                        "first_name": last_name.ref,
                                        "last_name": last_name.ref,
                                        "email": email.ref,
                                    },
                                ),
                            ),
                        ],
                    )
                ],
            ),
        )
    ],
)

# %% Update flow
# dynamic_flow.to_json()

success, validation_errors = wa.update_flow_json(flow_id=FLOW_ID, flow_json=dynamic_flow)

success, validation_errors
# %%
# %% Send the draft flow 
from pywa.types.flows import FlowActionType, FlowStatus
from pywa.types import FlowButton

# %%
wa.send_message(
    to="447448440754",
    text="Hi, You need to finish your sign up!",
    buttons=FlowButton(
        title="Finish Sign Up",
        flow_id=FLOW_ID,  # The `static_flow` flow id from above
        flow_token="AQAAAAACS5FpgQ_cAAAAAD0QI3s.",
        mode=FlowStatus.DRAFT,
        flow_action_type=FlowActionType.NAVIGATE,
        flow_action_screen="SIGN_UP", # The screen id to open when the user clicks the button
    )
)

# %% update endpoint url
wa.update_flow_metadata(
    flow_id=FLOW_ID,  # The `dynamic_flow` flow id from above
    endpoint_uri="https://your-server.com/flow"
)
# %% publish the flow
wa.publish_flow(flow_id=FLOW_ID)

# %% ToDo - Create the backend server to handle the flow
# %% Edits to json can be handled on the flow UI composer