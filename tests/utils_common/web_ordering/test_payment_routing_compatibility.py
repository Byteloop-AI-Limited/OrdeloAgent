"""Old checkout toggles cannot change mode or defeat basket conflict detection."""
import hashlib
import json

import pytest

from utils_common.web_ordering import web_checkout as checkout


def request(**extra):
    return checkout.OrderInput(thread_id="WEB-t", cust_id="W-KEY", rest_ref="ELAS", order_items=[{
        "sku":"food", "product_name":"TEST3100", "price":3, "quantity":1,
    }], **extra)


@pytest.mark.parametrize("retired_toggle", [False, True, "anything"])
def test_retired_client_field_is_discarded(retired_toggle):
    req=request(test_payment=retired_toggle)
    assert "test_payment" not in req.model_dump()
    assert checkout.fingerprint(req,None) == checkout.fingerprint(request(),None)


@pytest.mark.parametrize("old_value", [False, True])
def test_old_hash_recognises_same_input_but_rejects_changed_basket_and_address(old_value):
    req=request()
    address={"postcode":"SP1 1AA"}
    data=req.model_dump(mode="json") | {"address":address,"test_payment":old_value}
    old_hash=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    assert checkout.fingerprint_matches(old_hash,req,address)
    changed=req.model_copy(deep=True)
    changed.order_items[0].quantity=2
    assert not checkout.fingerprint_matches(old_hash,changed,address)
    assert not checkout.fingerprint_matches(old_hash,req,{"postcode":"SP2 2BB"})
