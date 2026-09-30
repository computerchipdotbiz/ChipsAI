import os
import logging
import urllib.request
import urllib.parse
import json
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("chipai.telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5127043704")


def send_message(chat_id: str | int, text: str, reply_markup: dict | None = None) -> bool:
    """Send an outbound Telegram message with optional inline keyboard buttons."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning(f"[MOCK TG] Outbound to {chat_id}: '{text}' (TELEGRAM_BOT_TOKEN not configured)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body_data: dict = {
        "chat_id": str(chat_id),
        "text": text,
    }
    if reply_markup:
        body_data["reply_markup"] = reply_markup

    payload = json.dumps(body_data).encode("utf-8")

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


def answer_callback_query(callback_query_id: str, text: str = "", show_alert: bool = False) -> bool:
    """Acknowledge a Telegram button click (callback_query) with an optional toast or alert."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    body = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        body["text"] = text

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        logger.error(f"Failed to answer callback query {callback_query_id}: {e}")
        return False


def edit_message_text(
    chat_id: str | int,
    message_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> bool:
    """Edit the text and inline buttons of an existing Telegram message."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/editMessageText"
    body: dict = {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
    }
    if reply_markup is not None:
        body["reply_markup"] = reply_markup

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        logger.error(f"Failed to edit message {message_id} in {chat_id}: {e}")
        return False


def send_voice(chat_id: str | int, audio_bytes: bytes, caption: str = "") -> bool:
    """Send an outbound playable Telegram voice message (waveform bubble)."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning(f"[MOCK TG] Outbound voice to {chat_id}: {len(audio_bytes)} bytes (TELEGRAM_BOT_TOKEN not configured)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendVoice"
    files = {"voice": ("voice.mp3", audio_bytes, "audio/mpeg")}
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]

    try:
        import requests
        resp = requests.post(url, data=data, files=files, timeout=25)
        res_json = resp.json()
        if res_json.get("ok"):
            logger.info(f"Telegram voice message sent to {chat_id}")
            return True
        else:
            logger.error(f"Telegram sendVoice failed: {res_json}")
            return False
    except Exception as e:
        logger.error(f"Failed to send voice message to {chat_id}: {e}")
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


def download_file_by_id(file_id: str) -> bytes | None:
    """Download file bytes from Telegram Bot API using file_id."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured; cannot download file.")
        return None

    try:
        # Step 1: Query getFile to retrieve the relative file_path
        url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not data.get("ok"):
                logger.error(f"Telegram getFile returned error: {data}")
                return None
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                logger.error(f"No file_path in getFile result: {data}")
                return None

        # Step 2: Download raw bytes from Telegram file server
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        with urllib.request.urlopen(file_url, timeout=20) as file_resp:
            return file_resp.read()
    except Exception as e:
        logger.error(f"Failed to download file {file_id} from Telegram: {e}")
        return None
