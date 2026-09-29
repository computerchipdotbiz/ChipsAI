import os
import re
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("chipai.twilio")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
USER_PHONE_NUMBER = os.getenv("USER_PHONE_NUMBER", "")


def clean_phone(phone: Optional[str]) -> str:
    """Normalize phone number to digits with leading plus."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d+]", "", phone.strip())
    if not digits.startswith("+") and len(digits) == 10:
        digits = "+1" + digits
    return digits


def is_authorized(from_number: str) -> bool:
    """Check if incoming phone number matches the whitelisted user phone number."""
    if not USER_PHONE_NUMBER:
        # If no whitelist specified, warn and reject for safety
        logger.warning("USER_PHONE_NUMBER is not set! Rejecting incoming SMS for security.")
        return False
    return clean_phone(from_number) == clean_phone(USER_PHONE_NUMBER)


def send_sms(to_number: str, body: str) -> bool:
    """Send an outbound SMS message via Twilio."""
    # Check credentials
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        logger.warning(
            f"[MOCK SMS] Outbound SMS to {to_number}: '{body}' (Twilio credentials not configured)"
        )
        return False

    try:
        from twilio.rest import Client

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            to=clean_phone(to_number),
            from_=clean_phone(TWILIO_PHONE_NUMBER),
            body=body,
        )
        logger.info(f"SMS successfully dispatched to {to_number} (SID: {message.sid})")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMS to {to_number}: {e}")
        return False


def build_twiml_response(reply_text: str) -> str:
    """Generate TwiML XML response for incoming Twilio webhooks."""
    try:
        from twilio.twiml.messaging_response import MessagingResponse

        response = MessagingResponse()
        response.message(reply_text)
        return str(response)
    except ImportError:
        # Fallback raw XML if twilio library is somehow missing
        escaped = reply_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>'
