import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.header import Header
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("chipai.email_service")

SMS_GATEWAY_EMAIL = os.getenv("SMS_GATEWAY_EMAIL", "6822331191@vzwpix.com")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER or "sarahzine800@gowan.one"


def send_gateway_text(
    body: str,
    to_address: Optional[str] = None,
    subject: str = "Sarahzine 800",
) -> bool:
    """Send an SMS/MMS text message via carrier email-to-text gateway using SMTP.
    For Verizon, sending to @vzwpix.com delivers up to ~3,000 chars as a unified MMS text.
    """
    dest = (to_address or SMS_GATEWAY_EMAIL or "").strip()
    if not dest:
        logger.warning("No destination address provided for email gateway text dispatch.")
        return False

    host = os.getenv("SMTP_HOST", SMTP_HOST).strip()
    user = os.getenv("SMTP_USER", SMTP_USER).strip()
    password = os.getenv("SMTP_PASSWORD", SMTP_PASSWORD).replace(" ", "").strip()
    port = int(os.getenv("SMTP_PORT", str(SMTP_PORT)))
    sender = os.getenv("SMTP_FROM", SMTP_FROM).strip() or user or "sarahzine800@gowan.one"

    # If SMTP credentials are not configured, log mock dispatch
    if not host or not user or not password:
        logger.warning(
            f"[MOCK GATEWAY SMS] Outbound text to {dest}: '{body[:60]}...' (SMTP not configured in .env)"
        )
        return False

    try:
        msg = MIMEText(body, "plain", "utf-8")
        if subject:
            msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = sender
        msg["To"] = dest

        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            if SMTP_USE_TLS:
                server.starttls()

        server.login(user, password)
        server.sendmail(sender, [dest], msg.as_string())
        server.quit()

        logger.info(f"Successfully dispatched text via email gateway to {dest} (Length: {len(body)})")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch text to email gateway {dest}: {e}", exc_info=True)
        return False
