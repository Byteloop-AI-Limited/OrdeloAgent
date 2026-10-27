from ordelo.rider_messaging import job_offer
from .test_offer_reminders import ROW


def test_original_offer_text_is_unchanged():
    offer = job_offer(ROW)
    assert offer.header == '1.5 miles, £5, @7:30 PM'
    assert offer.text == '''
    Pickup time - *7:30 PM*

Pickup location - *Strk Kitchen*
40b The Walnuts

Drop off location - *Test Customer*
1 Test Street

Order number - *STRK-TEST-101500*

Vehicle type - *bicycle*
    '''
