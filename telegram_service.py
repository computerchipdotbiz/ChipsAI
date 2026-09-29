import os
import logging
import urllib.request
import urllib.parse
import json
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("chipai.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8976159344:AAEP3jBtyCnO-_Mj7xzyOatNdEFK8-DeDMI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(chat_id: str | int, text: str) -> bool:
    """Send an outbound Telegram message."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning(f"[MOCK TG] Outbound to {chat_id}: '{text}' (TELEGRAM_BOT_TOKEN not configured)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": str(chat_id),
        "text": text,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("ok"):
                logger.info(f"Telegram message sent to {chat_id}")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
        return False


def set_webhook(webhook_url: str) -> bool:
    """Register the webhook URL with Telegram."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; cannot set webhook.")
        return False

    url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = urllib.parse.urlencode({"url": webhook_url}).encode("utf-8")

    req = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            logger.info(f"Set Telegram webhook to {webhook_url}: {result}")
            return result.get("ok", False)
    except Exception as e:
        logger.error(f"Failed to set Telegram webhook: {e}")
        return False


def is_authorized_tg(chat_id: str | int) -> bool:
    """Check if incoming Telegram chat ID matches authorized user."""
    # If no whitelist set yet, allow and log so Chip can grab their chat_id
    if not TELEGRAM_CHAT_ID:
        return True
    return str(chat_id) == str(TELEGRAM_CHAT_ID)
