"""
Creates the WhatsApp message template for the rider delivery-dispatch request.
    . Mirrors the free-form message sent by wa_send_delivery_dispatch_request_to_rider
      (watomation/routers/delivery_hooks.py) so dispatches can reach riders outside the
      24h customer service window
    . Header carries a single variable - a WhatsApp text header supports exactly one
      parameter (max 60 chars), so distance / payout / pickup time are pre-joined into
      {{dispatch_summary}} behind a static "New job - " prefix; an all-variable header
      with no static text is a common Meta rejection
    . Body uses named parameters (ParamFormat.NAMED)
    . Accept / Decline are quick reply buttons; their callback payload is supplied per
      send via QuickReplyButton.params(), the same mechanism enquire_shift_availability
      uses, so watomation/on_callback_wa_handler.dispatch_response needs no change
    . Run the cells in order: definition -> local validation -> create (network call)
  Functions/Classes:
    . dispatch_template - the Template definition submitted to Meta
    . dispatch_callback_payloads - builds the Accept/Decline callback payloads for a send
    . one_line - collapses newlines in a parameter value (WhatsApp rejects them)
"""

# %%
import json

from pywa.types import templates as t

TEMPLATE_NAME = "delivery_dispatch_request"

# %% Template definition
dispatch_template = t.Template(
    name=TEMPLATE_NAME,
    category=t.TemplateCategory.UTILITY,
    language=t.TemplateLanguage.ENGLISH_UK,
    parameter_format=t.ParamFormat.NAMED,
    components=[
        # One variable only (Meta: "Text headers support 1 parameter"), kept behind
        # static text so the header is not 100% variable. 60 char cap covers the
        # prefix plus the longest realistic summary.
        t.HeaderText(
            text="New job - {{dispatch_summary}}",
            dispatch_summary="2.4 miles, £4.50, @18:45",
        ),
        t.BodyText(
            text=(
                "Pickup time - *{{pickup_time}}*\n"
                "\n"
                "Pickup location - *{{rest_name}}*\n"
                "{{rest_address}}\n"
                "\n"
                "Drop off location - *{{customer_name}}*\n"
                "{{customer_address}}\n"
                "\n"
                "Order number - *{{order_number}}*\n"
                "\n"
                "Vehicle type - *{{vehicle_type}}*"
            ),
            pickup_time="18:45",
            rest_name="Elai Restaurant",
            rest_address="12 High Street, Ashford, TN23 1QD",
            customer_name="John Doe",
            customer_address="4 Church Lane, Ashford, TN24 8UP",
            order_number="ELAS-20260903-0042",
            vehicle_type="Bike",
        ),
        t.FooterText(text="♾️ Byteloop AI"),
        t.Buttons(
            buttons=[
                t.QuickReplyButton(text="Accept"),
                t.QuickReplyButton(text="Decline"),
            ]
        ),
    ],
    # A dispatch offer is worthless once the order has been re-dispatched. To cap
    # delivery attempts, set this from {REST_REF}_DELIVERY_TIMEOUT_TIME in ordelo_config
    # rather than a made-up number:
    # message_send_ttl_seconds=...,
)

# %% Local validation - no network call, safe to run first
print(json.dumps(json.loads(dispatch_template.to_json()), indent=2, ensure_ascii=False))

# %% Create the template (network call - submits to Meta for approval)
from config import _sync_wa_client  # noqa: E402

created = _sync_wa_client.create_template(template=dispatch_template)
print("Template created:", created.id, created.status)


# %% Sending it, once Meta approves
def one_line(value: str) -> str:
    """WhatsApp rejects newlines/tabs/4+ spaces in parameter values."""
    return " ".join(str(value).split())


def dispatch_callback_payloads(order_number: str, dispatch_id: int) -> tuple[str, str]:
    """Accept/Decline payloads for the quick reply buttons.

    rider_id is deliberately omitted: dispatch_response() overwrites it with
    msg.sender anyway, and dropping it keeps the payload well inside the button
    payload length limit.
    """
    base = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
    }
    return (
        json.dumps({**base, "status": "accepted"}),
        json.dumps({**base, "status": "declined"}),
    )


# accept_pl, decline_pl = dispatch_callback_payloads("ELAS-20260903-0042", 141)
# await _async_wa_client.send_template(
#     to=recipient,
#     name=TEMPLATE_NAME,
#     language=t.TemplateLanguage.ENGLISH_UK,
#     params=[
#         t.HeaderText.params(
#             dispatch_summary=f"{d['distance']} miles, £{d['rider_payout']}, @{pickup_time}"
#         ),
#         t.BodyText.params(
#             pickup_time=pickup_time,
#             rest_name=one_line(d["rest_name"]),
#             rest_address=one_line(d["rest_address"]),
#             customer_name=one_line(d["customer_name"]),
#             customer_address=one_line(d["customer_address"]),
#             order_number=d["order_number"],
#             vehicle_type=one_line(d["vehicle_type"]),
#         ),
#         t.QuickReplyButton.params(callback_data=accept_pl, index=0),
#         t.QuickReplyButton.params(callback_data=decline_pl, index=1),
#     ],
# )

# %%
