#   %%
# %% All screens in one place
from pywa import utils
from pywa.types.flows import (
    FlowJSON,
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
    Dropdown
)

SIGN_UP_FLOW_JSON = FlowJSON(
    version=utils.Version.FLOW_JSON,
    data_api_version=utils.Version.FLOW_DATA_API,
    routing_model={
        "START": ["SIGN_UP", "LOGIN"],
        "SIGN_UP": ["LOGIN"],
        "LOGIN": ["LOGIN_SUCCESS"],
        "LOGIN_SUCCESS": [],
    },
    screens=[
        Screen(
            id="START",
            title="Home",
            layout=Layout(
                children=[
                    Dropdown(
                        name='ddOptions',
                        data_source=[
                            DataSource(id='1', title='Option 1'),
                            DataSource(id='2', title='Option 2'),
                            DataSource(id='3', title='Option 3'),
                        ],
                        label='Options',
                        required=True,
                        init_value='1'
                    ),
                    PhotoPicker(
                        name='photo',
                        label='Take a photo',
                        description='wishing I could see you now',
                        photo_source=PhotoSource.CAMERA,
                        max_file_size_kb=10_000,  # 10MB
                        min_uploaded_photos=1,
                        max_uploaded_photos=3,
                    ),
                    ChipsSelector(
                        name='options',
                        data_source=[
                            DataSource(id='1', title='Option 1'),
                            DataSource(id='2', title='Option 2'),
                            DataSource(id='3', title='Option 3'),
                        ],
                        label='Options',
                        min_selected_items=1,
                        max_selected_items=2,
                        required=True,
                        init_value=['1', '2']
                    ),
                    TextHeading(
                        text="Welcome to Ordelo",
                    ),
                    EmbeddedLink(
                        text="Click here to sign up",
                        on_click_action=Action(
                            name=FlowActionType.NAVIGATE,
                            next=Next(
                                type=NextType.SCREEN,
                                name="SIGN_UP",
                            ),
                            payload={
                                "first_name_initial_value": "",
                                "last_name_initial_value": "",
                                "email_initial_value": "",
                                "password_initial_value": "",
                                "confirm_password_initial_value": "",
                            },
                        ),
                    ),
                    EmbeddedLink(
                        text="Click here to login",
                        on_click_action=Action(
                            name=FlowActionType.NAVIGATE,
                            next=Next(
                                type=NextType.SCREEN,
                                name="LOGIN",
                            ),
                            payload={
                                "email_initial_value": "",
                                "password_initial_value": "",
                            },
                        ),
                    ),
                ]
            ),
        ),
        Screen(
            id="SIGN_UP",
            title="Sign Up",
            data=[
                first_name_initial_value := ScreenData(key="first_name_initial_value", example="John"),
                last_name_initial_value := ScreenData(key="last_name_initial_value", example="Doe"),
                email_initial_value := ScreenData(key="email_initial_value", example="john.doe@gmail.com"),
                password_initial_value := ScreenData(key="password_initial_value", example="abc123"),
                confirm_password_initial_value := ScreenData(key="confirm_password_initial_value", example="abc123"),
            ],
            layout=Layout(
                children=[
                    TextHeading(
                        text="Please enter your details",
                    ),
                    EmbeddedLink(
                        text="Already have an account?",
                        on_click_action=Action(
                            name=FlowActionType.NAVIGATE,
                            next=Next(
                                type=NextType.SCREEN,
                                name="LOGIN",
                            ),
                            payload={
                                "email_initial_value": "",
                                "password_initial_value": "",
                            },
                        ),
                    ),
                    Form(
                        name="form",
                        children=[
                            first_name := TextInput(
                                name="first_name",
                                label="First Name",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=first_name_initial_value.ref,
                            ),
                            last_name := TextInput(
                                name="last_name",
                                label="Last Name",
                                input_type=InputType.TEXT,
                                required=True,
                                init_value=last_name_initial_value.ref,
                            ),
                            email := TextInput(
                                name="email",
                                label="Email Address",
                                input_type=InputType.EMAIL,
                                required=True,
                                init_value=email_initial_value.ref,
                            ),
                            password := TextInput(
                                name="password",
                                label="Password",
                                input_type=InputType.PASSWORD,
                                min_chars=8,
                                max_chars=16,
                                helper_text="Password must contain at least one number",
                                required=True,
                                init_value=password_initial_value.ref,
                            ),
                            confirm_password := TextInput(
                                name="confirm_password",
                                label="Confirm Password",
                                input_type=InputType.PASSWORD,
                                min_chars=8,
                                max_chars=16,
                                required=True,
                                init_value=confirm_password_initial_value.ref,
                            ),
                            Footer(
                                label="Done",
                                on_click_action=Action(
                                    name=FlowActionType.DATA_EXCHANGE,
                                    payload={
                                        "first_name": first_name.ref,
                                        "last_name": last_name.ref,
                                        "email": email.ref,
                                        "password": password.ref,
                                        "confirm_password": confirm_password.ref,
                                    },
                                ),
                            ),
                        ]
                    )
                ]
            )
        ),
        Screen(
            id="LOGIN",
            title="Login",
            terminal=True,
            data=[
                email_initial_value := ScreenData(key="email_initial_value", example="LOHITH.chaitra@gmail.com"),
                password_initial_value := ScreenData(key="password_initial_value", example="abc123"),
            ],
            layout=Layout(
                children=[
                    TextHeading(
                        text="Please enter your details"
                    ),
                    EmbeddedLink(
                        text="Don't have an account?",
                        on_click_action=Action(
                            name=FlowActionType.NAVIGATE,
                            next=Next(
                                type=NextType.SCREEN,
                                name="SIGN_UP",
                            ),
                            payload={
                                "email_initial_value": "",
                                "password_initial_value": "",
                                "confirm_password_initial_value": "",
                                "first_name_initial_value": "",
                                "last_name_initial_value": "",
                            },
                        ),
                    ),
                    Form(
                        name="form",
                        children=[
                            email := TextInput(
                                name="email",
                                label="Email Address",
                                input_type=InputType.EMAIL,
                                required=True,
                                init_value=email_initial_value.ref,
                            ),
                            password := TextInput(
                                name="password",
                                label="Password",
                                input_type=InputType.PASSWORD,
                                required=True,
                                init_value=password_initial_value.ref,
                            ),
                            Footer(
                                label="Done",
                                on_click_action=Action(
                                    name=FlowActionType.DATA_EXCHANGE,
                                    payload={
                                        "email": email.ref,
                                        "password": password.ref,
                                    },
                                ),
                            ),
                        ]
                    )
                ]
            ),
        ),
        Screen(
            id="LOGIN_SUCCESS",
            title="Success",
            terminal=True,
            layout=Layout(
                children=[
                    TextHeading(
                        text="Welcome to our store",
                    ),
                    TextSubheading(
                        text="You are now logged in",
                    ),
                    Form(
                        name="form",
                        children=[
                            stay_logged_in := OptIn(
                                name="stay_logged_in",
                                label="Stay logged in",
                            ),
                            Footer(
                                label="Done",
                                on_click_action=Action(
                                    name=FlowActionType.COMPLETE,
                                    payload={
                                        "stay_logged_in": stay_logged_in.ref,
                                    },
                                ),
                            ),
                        ]
                    )
                ]
            ),
        )
    ]
)

# %% get WA

from config import waba_business_settings
from pywa import WhatsApp
from pywa.types import FlowCategory

wa = WhatsApp(
            token=waba_business_settings.token,
            business_account_id=waba_business_settings.account_id,
            verify_token=waba_business_settings.verify_token,
            phone_id=waba_business_settings.phone_id
        )

# %% Create a flow

# flow_id = wa.create_flow(
#     name="Sign Up Flow1",
#     categories=[FlowCategory.SIGN_IN, FlowCategory.SIGN_UP],
# )

# %%
FLOW_ID = '1144380177007023'
# %% have to set the endpoint URI first??
# wa.update_flow_metadata(
#     flow_id=FLOW_ID,
#     endpoint_uri="https://agent.orderlo.app/sign-up-flow1",
# )
# %% UPDATE FLOW JSON

from pywa.errors import FlowUpdatingError

try:
    success, validation_errors = wa.update_flow_json(
        flow_id=FLOW_ID,
        flow_json=SIGN_UP_FLOW_JSON,
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
    text="Hi, You need to finish your sign up!",
    buttons=FlowButton(
        title="Finish Sign Up",
        flow_id=1144380177007023,  # The `static_flow` flow id from above
        flow_token="AQAAAAACS5FpgQ_cAAAAAD0QI3s123123",
        mode=FlowStatus.DRAFT,
        flow_action_type=FlowActionType.NAVIGATE,
        flow_action_screen="START", # The screen id to open when the user clicks the button
    )
)

# %%
wa.send_message(
    to="447448440754",
    # to="44744633210",
    text="Hi, You need to finish your sign up!",
    buttons=FlowButton(
        title="Home",
        flow_id=1144380177007023,  # The `static_flow` flow id from above
        flow_token="123.",
        mode=FlowStatus.DRAFT,
        flow_action_type=FlowActionType.NAVIGATE,
        flow_action_screen="START", # The screen id to open when the user clicks the button
    )
)

