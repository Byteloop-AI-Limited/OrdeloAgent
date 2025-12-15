"""WhatsApp ad-hoc runner notebook.
  . Dependencies based on imports: pywa, requests, config.waba_setting, utils_common.waba_utils.wa_senders
  . Provides scratch utilities to send test WhatsApp messages/templates
Functions/Clases
  . send_restaurant_order_confirmation
"""

# %%
import os
import requests
import json
from config import _async_wa_client as wa
from pywa.types import (
    SectionList,
    Section,
    SectionRow,
    Button,
    CallbackButton,
    Message,
    ButtonUrl,
)

from pywa import filters as fil
from config.waba_setting import waba_business_settings, waba_cat_settings
from pywa.types import Template as Temp
from pywa.types.templates import QuickReplyButton, TemplateLanguage, BodyText
from utils_common.waba_utils.wa_senders import CallbackButtonData
# waba_phone_setting, waba_business_setting

# %%
recipient = 447448440754


# %%

# %%


# recipient = "447448440754"
async def send_restaurant_order_confirmation(
    recipient: str,
    order_number: str,
    order_amount: str,
    order_items: str,
    order_time: int,
    order_type: str,
) -> Message:
    """Send the restaurant order confirmation as an interactive message."""
    accept_button = CallbackButtonData(
        action="/RestaurantOrder-Accept",
        order_number=order_number,
        order_time=order_time,
    )
    decline_button = CallbackButtonData(
        action="/RestaurantOrder-Decline",
        order_number=order_number,
        order_time=order_time,
    )

    if order_type == "delivery":
        order_type_icon = " 🚚 "
    elif order_type == "takeaway":
        order_type_icon = " 🥡 "
    else:
        order_type_icon = " "

    return await wa.send_message(
        to=recipient,
        header=(
            order_number
            + " "
            + order_amount
            + order_type_icon
            + order_type.capitalize()
        ),
        text=order_items,
        reply_to_message_id=None,
        buttons=[
            Button(title="Accept", callback_data=accept_button.model_dump_json()),
            Button(title="Decline", callback_data=decline_button.model_dump_json()),
        ],
    )


# %% Call function with dummy values
await send_restaurant_order_confirmation(recipient, "123", "10", "10", "10", "delivery")
# %%
msg_id = await wa.send_template(
    to=recipient,
    name="shift_availability",
    language=TemplateLanguage.ENGLISH_UK,
    params=[
        BodyText.params(text="lohith"),
        QuickReplyButton.params(callback_data="accept", index=0),
        QuickReplyButton.params(callback_data="accept", index=1),
    ],
)
# %% enquire admin availability
admin_availability_cb_data = CallbackButtonData(
    action="/adminAvailability",
    recipient=recipient,
)
msg_id = await wa.send_template(
    to=recipient,
    name="alert_order_notification_resolve",
    language=TemplateLanguage.ENGLISH_UK,
    params=[
        BodyText.params(text="There"),
        QuickReplyButton.params(
            callback_data=admin_availability_cb_data.model_dump_json(), index=0
        ),
    ],
)
# %%"
image_path = "/mnt/c/wsl_transfers/trump.jpeg"
# read image
with open(image_path, "rb") as f:
    image = f.read()

# %%
type(image)
# %%
await _async_wa_client.send_image(
    to=recipient,
    image=image,
    caption="This is an image!",
    mime_type="image/jpeg",
)
# %% investigate callback data
order_number = "test123"
msg = await _async_wa_client.send_message(
    to=recipient,
    reply_to_message_id="wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAERgSRTMzMEZCNEM4OTRGRDc2ODZFAA==",
    header=f"{order_number} Update",
    text=(
        "🚗 **Our delivery rider has left the restaurant!**\n\n"
        "You can track your order live using the button below:\n\n"
        "Warren Road, Orpington, BR6 6JF"
    ),
    buttons=ButtonUrl(title="Live Location", url="https://google.com"),
)
# %%
msg.id
# %%
from pywa.types import NewTemplate as NewTemp
from config import _sync_wa_client as wa

recipient = 447448440754
wa.send_message(
    to=recipient,
    text="hi, this is cool",
    reply_to_message_id=None,
)
# %%

response = wa.create_template(
    template=NewTemp(
        name="buy_new_iphone_x",
        category=NewTemp.Category.MARKETING,
        language=NewTemp.Language.ENGLISH_UK,
        header=NewTemp.Text("The New iPhone is here!"),
        body=NewTemp.Body("Buy now and use the code  to get  off!"),
        footer=NewTemp.Footer("Powered by PyWa"),
    ),
)

print(response)
# %% Send documents

from pywa import WhatsApp
import requests

res = requests.get(
    "https://cdn.pixabay.com/photo/2014/10/01/10/44/animal-468228_1280.jpg"
)
wa.send_document(
    to=recipient,
    document=res.content,
    filename="animal.jpg",
    mime_type="image/jpeg",
)

# %% Send OwnTracks Config to drivers

import base64
import json

waypoints = [
    {
        "_type": "waypoint",
        "tst": 1708625557,
        "rid": "h0me",
        "desc": "home",
        "rad": 1,
        "lat": 51.354107,
        "lon": 0.095921,
    }
]

config = {
    "_type": "configuration",
    "mode": 3,
    "allowRemoteLocation": True,
    "usePassword": False,
    "monitoring": 2,
    "username": "iphone14",
    "password": "",
    "url": "https://live-track.byteloop.ai/pub",
    "locatorDisplacement": 2,
    "locatorInterval": 60,
    "waypoints": waypoints,
}

# Convert config to JSON string and encode to base64
config_json = json.dumps(config)
config_base64 = base64.b64encode(config_json.encode()).decode()
href = f"owntracks:///config?inline={config_base64}"


# Send as interactive message with URL button
wa.send_message(
    to=recipient,
    text=f"...",
    reply_to_message_id=None,
    buttons=ButtonUrl(title="Start Job", url=href),
)


# %%
msg_id = wa.send_message(
    to=recipient,
    header="Job details: 1.2 Miles £3.5",
    text=f"Do you accept the job?",
    reply_to_message_id=None,
    footer="⚡Ordelo",
    buttons=ButtonUrl(title="View on Map", url="https://www.google.com/maps"),
)

# %%
wa.send_message(
    to=recipient,
    reply_to_message_id=msg_id.id,
    text="Accepted",
    buttons=[
        Button(title="Accept", callback_data="sadf"),
        Button(title="Decline", callback_data="asdf"),
    ],
)

# %%
msg_id.id
# %%
current_location = "https://maps.google.com/?q=Order('1234')@51.354126,0.099301"

wa.send_message(
    to=recipient,
    text=f"Live location for your order",
    reply_to_message_id=None,
    buttons=ButtonUrl(title="Live Location", url=current_location),
)

# %%
wa.send_location(to=recipient, latitude=51.354126, longitude=0.099301)

# %%
wa.send_text(to=recipient, text="Hello World")


# %% payment reciept
def generate_whatsapp_receipt(order_summary):
    # Extracting order details
    order_id = order_summary["order_id"]
    order_type = order_summary["order_type"]
    recipient = order_summary["recipient"]
    items = order_summary["items"]

    # Building item details
    items_details = ""
    total_amount = 0
    for item in items:
        name = item["product_name"]
        price = item["price"]
        quantity = item["quantity"]
        total_price = price * quantity
        total_amount += total_price
        items_details += f"▫️ *{name}* x{quantity} £{total_price:.2f} "

    return [order_id, order_type, items_details, total_amount]


order_summary = {
    "order_id": "EDJJ-26",
    "order_type": "Paid Collection",
    "payment_status": "awaiting_payment",
    "recipient": "447448440754",
    "thread_id": "39e55759-c10f-44de-8510-25f00682ec8f",
    "items": [
        {"product_name": "Cheesecake", "price": 5.95, "quantity": 2},
        {"product_name": "Meen Mulakittathu Curry", "price": 13.95, "quantity": 2},
    ],
    "currency": "GBP",
}

# Generate receipt
receipt = generate_whatsapp_receipt(order_summary)
print(receipt)

# %%
wa.send_template(
    to=recipient,
    template=Temp(
        name="payment_reciept_elai",
        language=Temp.Language.ENGLISH_UK,
        body=[
            Temp.TextValue(value=receipt[0]),
            Temp.TextValue(value=receipt[1]),
            Temp.TextValue(value=receipt[2]),
            Temp.TextValue(value=receipt[3]),
        ],
    ),
)

# %%
import tenacity
# %%

wa.send_template(
    to=recipient,
    template=Temp(
        name="request_payment",
        language=Temp.Language.ENGLISH_UK,
        body=[
            Temp.TextValue(value="10hith"),
            Temp.TextValue(value="pubg-14"),
        ],
        buttons=[
            Temp.UrlButtonValue(
                value="c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl"
            ),
            # Temp.TextValue(value="https://checkout.stripe.com/c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl")
        ],
    ),
)

# %%
wa.send_template(
    to="447850773336", template=Temp(name="demo_tryout", language=Temp.Language.ENGLISH)
)

# %%
Temp(
    name="order_management_3",
    language=Temp.Language.ENGLISH_US,
    body=[
        Temp.TextValue(value="Rahul"),
        Temp.TextValue(value="123"),
    ],
    buttons=[
        Temp.UrlButtonValue(
            value="c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl"
        ),
        # Temp.TextValue(value="https://checkout.stripe.com/c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl")
    ],
).to_dict()
# %%
# This is the whatsapp link to start a conversation
markdown_text = """
https://wa.me/447424334783?text=Hello%2C%20I%20would%20like%20more%20information
"""
# wa.send_message(
#     to=recipient,
#     text=markdown_text
# )

wa.send_message(
    to=recipient,
    text="PyWa [markdown](https://faq.whatsapp.com/539178204879377)",
    preview_url=False,
    buttons=[
        Button(title="⬇️ Download", callback_data=f"https://pywa.readthedocs.io/"),
        Button(title="💬 Comments", callback_data=f"cmnts"),
        Button(title="🎬 Info", callback_data=f"info"),
    ],
)

# wa.send_bu(
#     to=recipient,
#     text='PyWa [markdown](https://faq.whatsapp.com/539178204879377)',
#     preview_url=False,
# )

# wa.send_image(
#     to=recipient,
#     image=f'https://pywa.readthedocs.io/',
#     caption='Chandler Jokes | Friends • 2.9M views • 1 year ago',
#     footer='⚡ Powered by PyWa',
#     buttons=[
#         Button(title='⬇️ Download', callback_data=f'https://pywa.readthedocs.io/'),
#         Button(title='💬 Comments', callback_data=f'cmnts'),
#         Button(title='🎬 Info', callback_data=f'info'),
#     ]
# )
# wa.get_commerce_settings()
# wa.get_business_phone_number()

# https://graph.facebook.com/v17.0/{waba_id}/catalogs

# %% Getting feed id
# url = "https://graph.facebook.com/v21.0/365315793337549/product_feeds"
# # 1005775587696145
# payload={}
# response = requests.get(url, headers=waba_cat_setting.cat_headers, data=json.dumps(payload))
# response.text

# %% send catalog
wa.send_catalog(
    to=recipient,
    body="Check out our catalog!",
    # footer='Powered by PyWa',
    thumbnail_product_sku="123",
)

# %% send location
wa.send_location(
    to=recipient,
    latitude=51.2626545707999,
    longitude=-1.0845731448928566,
    name="Elai Restaurant",
    address="Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY",
)
# %% Getting Commerce settings

url = "https://graph.facebook.com/v21.0/365315793337549/whatsapp_commerce_settings"

# Construct the headers using the API key variable
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {waba_business_settings.token}",  # Using f-string for cleaner interpolation
}

# Payload for the request
payload = {}

response = requests.get(url, headers=headers, data=json.dumps(payload))
response.text

# %% Getting product list based on a search
CATALOG_ID = "1005775587696145"
CATALOG_ID = "1088661639000911"
# Define the endpoint URL
url = f"https://graph.facebook.com/v21.0/{CATALOG_ID}/products"

headers = waba_cat_settings.cat_headers

filter_condition = {"name": {"i_contains": "biryani"}}
filter_condition = {"retailer_id": {"eq": "fu1s38ef9q"}}
filter_condition = {}


# Convert the filter to a JSON string
filter_json = json.dumps(filter_condition)

# Set up the query parameters
params = {
    # 'fields': '["name", "availability", "id", "product_id", "quantity_to_sell_on_facebook", "price", "description", "url", "condition", "currency"]',
    "fields": '["availability", "id", "product_id", "quantity_to_sell_on_facebook", "price", "description", "url", "condition", "currency"]',
    "filter": filter_json,
    "summary": "true",
}

# Make the GET request
response = requests.get(url, headers=headers, params=params)

# Check the response status
if response.status_code == 200:
    # Parse the JSON response
    data = response.json()
else:
    print(f"Error: {response.status_code}")
    print(response.text)

products = json.loads(response.text)["data"]
products
# %%


def filter_any_dict(dicts, **kwargs):
    filtered_dicts = []
    for d in dicts:
        match = all(d.get(k) == v for k, v in kwargs.items())
        if match:
            filtered_dicts.append(d)
    return filtered_dicts


# %% Update inventory based on product id - Works

url = "https://graph.facebook.com/v20.0/27562949043318468"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {waba_business_settings.cat_token}",
}

payload = {
    "quantity_to_sell_on_facebook": 100,
    "availability": "in stock",
    # "availability": "out of stock"
}

response = requests.post(url, headers=headers, data=payload)

if response.status_code == 200:
    print("Success:", response.json())
else:
    print("Error:", response.status_code, response.text)


# %% on demand catalog datasource update
import time

PRODUCT_FEED_ID = os.getenv("Feed_ID")
# Define the endpoint URL
url = f"https://graph.facebook.com/v21.0/{PRODUCT_FEED_ID}/uploads"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MTG_CAT_TOKEN}",
}

data = {"url": os.getenv("Feed_URL")}

response = requests.post(url, headers=headers, data=data)
if response.status_code == 200:
    upload_session_id = json.loads(response.text)["id"]
    print(f"Upload initiated successfully, with session id {upload_session_id}")
else:
    print("Error updating the catalog")

while True:
    status_url = f"https://graph.facebook.com/{upload_session_id}"
    status_response = requests.get(status_url, headers=headers)
    status_data = json.loads(status_response.text)

    # Check for "end_time" presence
    if "end_time" in status_data:
        print(f"End time found: {status_data['end_time']}")
        break

    print("Checking again in 2 seconds...")
    time.sleep(2)

# %% wa send product based on search


# Search support - Sending products or product list
# GET /v21.0/{whats-app-business-phone-number-id}/whatsapp_commerce_settings HTTP/1.1

wa.get_commerce_settings()

wa.uct(
    to=recipient,
    # catalog_id='431039886329420',
    catalog_id="431039886329420",
    sku="123",
)

# %% wa send products based on search


# %% #! getting product feed errors report


# status_url = f'https://graph.facebook.com/{upload_id}/error_report'
# status_response = requests.get(status_url, headers=headers)
# status_response.status_code, status_response.text


# %% When msg was sent on individual product
Message(
    id="wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAEhgUM0FGNTdENDY5MDI1OEYzQThCODMA",
    type=MessageType.TEXT,
    metadata=Metadata(
        display_phone_number="447929843965", phone_number_id="365315793337549"
    ),
    from_user=User(wa_id="447448440754", name="10hith"),
    timestamp=datetime.datetime(2024, 11, 4, 8, 28, 39),
    reply_to_message=ReplyToMessage(
        message_id="wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAERgPcHJvZHVjdF9pbnF1aXJ5AA==",
        from_user_id="447929843965",
        referred_product=ReferredProduct(
            catalog_id="1088661639000911", sku="dma2z1f184"
        ),
    ),
    forwarded=False,
    forwarded_many_times=False,
    text="10",
    image=None,
    video=None,
    sticker=None,
    document=None,
    audio=None,
    caption=None,
    reaction=None,
    location=None,
    contacts=None,
    order=None,
    system=None,
    error=None,
)

# %% When cart is sent
Message(
    id="wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAEhgUM0E3MUNDRDVDMkZFQUU2RTlGMzgA",
    type=MessageType.ORDER,
    metadata=Metadata(
        display_phone_number="447929843965", phone_number_id="365315793337549"
    ),
    from_user=User(wa_id="447448440754", name="10hith"),
    timestamp=datetime.datetime(2024, 11, 4, 8, 33, 18),
    reply_to_message=None,
    forwarded=False,
    forwarded_many_times=False,
    text=None,
    image=None,
    video=None,
    sticker=None,
    document=None,
    audio=None,
    caption=None,
    reaction=None,
    location=None,
    contacts=None,
    order=Order(
        catalog_id="1088661639000911",
        products=(
            Product(sku="dma2z1f184", quantity=1, price=10, currency="GBP"),
            Product(sku="fu1s38ef9q", quantity=1, price=13.99, currency="GBP"),
        ),
        text="",
    ),
    system=None,
    error=None,
)

# %%
from pywa.types.message import Message

# Message.order
# Message.order.products
