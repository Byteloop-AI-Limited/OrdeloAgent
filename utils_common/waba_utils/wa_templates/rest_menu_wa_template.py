"""
WhatsApp restaurant menu carousel template script.
    . Configures PyWa client and fetches WhatsApp template settings for restaurant menus
    . Builds carousel templates and demonstrates sending template-driven promotions
    . Utilizes RestMenuQueryParams for URL query string encoding in template buttons
  Functions/Classes:
    . send_restaurant_menu_carousel
"""

# %%
from typing import Sequence

import os
import requests
import json
import os
from pywa import WhatsApp
from pywa.types import (
    SectionList,
    Section,
    SectionRow,
    Button,
    CallbackButton,
    Message,
    ButtonUrl,
    Template,
)
from pywa.types.templates import *

from pywa import filters as fil
from config.waba_setting import waba_business_settings, waba_cat_settings
from pywa.types import Template as Temp
from config import logger
from pywa.types.templates import CarouselCard
# from pywa.types.templates import CarouselTemplate
# waba_phone_setting, waba_business_setting

from config import _sync_wa_client as wa
from utils_common.wa_templates.rest_menu_query_params import RestMenuQueryParams
from importlib import reload
import config.waba_setting

# Reload to pick up any changes (e.g., app_id added)
reload(config.waba_setting)
from config.waba_setting import _sync_wa_client as wa  # re-import after reload

# Verify app_id is set (required for automatic media upload)
logger.info(f"WhatsApp client app_id: {wa.app_id}")
if not getattr(wa, "app_id", None):
    raise ValueError("app_id is required for automatic media upload in templates")

# %%

recipient = "447448440754"
# recipient = "447446933210"

waba_business_settings.phone_id

# %% sending carousel
# from pywa.types import HeaderImage, QuickReplyButton, URLButton
from pywa.types.templates import (
    CarouselCard,
    HeaderImage,
    HeaderGIF,
    QuickReplyButton,
    URLButton,
    Carousel,
    BodyText,
    TemplateLanguage,
    TemplateCategory,
    Buttons,
    ParamFormat,
)
# %% Create carousel - Trying to create
# %% Example2 of a single variable

# %% Create carousel - Able to create the Carousel only with one URLButton, 2 resulted in failure; Upload media was not required
carousel_components = [
    card1 := CarouselCard(
        components=[
            hi1 := HeaderImage(
                example="https://raw.githubusercontent.com/Byteloop-AI-Limited/elai-menu-images/main/images/elas_logo.jpg"
            ),
            body1 := BodyText(
                text="Experience the finest authentic Indian cuisine with fresh ingredients, traditional recipes, and exceptional flavors",
            ),
            Buttons(
                buttons=[
                    u1 := URLButton(
                        text="Order Now",
                        url="https://restaurant.ordelo.app/restaurant/{{1}}",
                        example="https://restaurant.ordelo.app/restaurant/elas",
                    ),
                ]
            ),
        ]
    ),
    card2 := CarouselCard(
        components=[
            hi2 := HeaderImage(
                example="https://raw.githubusercontent.com/Byteloop-AI-Limited/elai-menu-images/main/images/wits_logo.jpg"
            ),
            body2 := BodyText(
                text="Crispy wings with crackling crunch, tossed in bold house sauces",
            ),
            Buttons(
                buttons=[
                    u2 := URLButton(
                        text="Order Now",
                        url="https://restaurant.ordelo.app/restaurant/{{1}}",
                        example="https://restaurant.ordelo.app/restaurant/wits",
                    ),
                ]
            ),
        ]
    ),
]

# Wrap the cards with a Carousel component (required)
carousel_elai_wits_menu = Carousel(cards=carousel_components)

# Template-level body text (required for carousel templates)
template_body = BodyText(text="Choose your restaurant")

elai_wits_menu_template = Template(
    name="rest_menu_ui_2",
    language=TemplateLanguage.ENGLISH_US,
    category=TemplateCategory.MARKETING,
    parameter_format=ParamFormat.NAMED,
    components=[template_body, carousel_elai_wits_menu],
)
# %%
# Pass app_id to ensure media examples upload via Upload Resumable API
# wa.create_template(elai_wits_menu_template, app_id=waba_business_settings.app_id)

# %% Sending the template


def send_restaurant_menu_carousel(
    *,
    recipient: str,
    rest_menu_params: Sequence[RestMenuQueryParams],
) -> Message:
    """Send the rest_menu_ui_2 template with per-card query parameters."""

    params_list = list(rest_menu_params)
    if len(params_list) != 2:
        raise ValueError(
            "rest_menu_params must contain exactly two RestMenuQueryParams entries."
        )

    elas_params, wits_params = (
        params_list[0].to_query_params(),
        params_list[1].to_query_params(),
    )

    return wa.send_template(
        to=recipient,
        name="rest_menu_ui_2",
        language=TemplateLanguage.ENGLISH_US,
        params=[
            carousel_elai_wits_menu.params(
                cards=[
                    card1.params(
                        index=0,
                        params=[
                            hi1.params(
                                image="https://raw.githubusercontent.com/Byteloop-AI-Limited/elai-menu-images/main/images/elas_logo.jpg"
                            ),
                            u1.params(
                                url_variable=f"/elas?{elas_params}",
                                index=0,
                            ),
                        ],
                    ),
                    card2.params(
                        index=1,
                        params=[
                            hi2.params(
                                image="https://raw.githubusercontent.com/Byteloop-AI-Limited/elai-menu-images/main/images/wits_logo.jpg"
                            ),
                            u2.params(
                                url_variable=f"/wits?{wits_params}",
                                index=0,
                            ),
                        ],
                    ),
                ]
            ),
        ],
    )


# # %%
# send_restaurant_menu_carousel(
#     recipient="447448440754",
#     rest_menu_params=[
#         RestMenuQueryParams(thread_id="Alpha123", recipient="447448440754"),
#         RestMenuQueryParams(thread_id="Beta123", recipient="447448440754"),
#     ],
# )
