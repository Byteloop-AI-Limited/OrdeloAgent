from pywa import WhatsApp, types
from config import logger

def handle_message(wa: WhatsApp, msg: types.Message):
    logger.success("inside handle_message")
    logger.info(msg)

def handle_callback_button(wa: WhatsApp, clb: types.CallbackButton):
    print(clb.data)