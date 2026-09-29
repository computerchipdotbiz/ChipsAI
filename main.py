import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, HTTPException, Response, Request, status
from dotenv import load_dotenv

import database
import scheduler
import assistant
import twilio_service
import telegram_service

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chipai.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events."""
    logger.info("Initializing ChipAI database...")
    database.init_db()

    logger.info("Starting background reminder scheduler...")
    scheduler.start_scheduler(interval_seconds=15)

    # Auto-register Telegram webhook if bot token is configured
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://chipsai.onrender.com")
    if tg_token:
        try:
            telegram_service.set_webhook(f"{base_url}/telegram")
            logger.info(f"Registered Telegram webhook at {base_url}/telegram")
        except Exception as e:
            logger.warning(f"Could not register Telegram webhook: {e}")

    yield

    logger.info("Stopping background reminder scheduler...")
    scheduler.stop_scheduler()


app = FastAPI(
    title="ChipAI - Personal AI Assistant",
    description="24/7 Always-On Gemini Assistant with Proactive Reminders",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "ChipAI SMS Assistant",
        "timezone": os.getenv("USER_TIMEZONE", "America/Chicago"),
        "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/sms")
async def incoming_sms(
    From: str = Form(...),
    Body: str = Form(""),
    To: str = Form(None),
):
    """
    Twilio webhook endpoint for incoming SMS.
    Validates sender against whitelist, passes text to Gemini, and replies with TwiML XML.
    """
    logger.info(f"Incoming SMS received from {From}: '{Body}'")

    # Security Whitelist Check
    if not twilio_service.is_authorized(From):
        logger.warning(
            f"Unauthorized incoming SMS from {From} rejected. (Whitelist: {os.getenv('USER_PHONE_NUMBER')})"
        )
        # Return empty response to drop message without giving attacker details
        return Response(content="<Response></Response>", media_type="application/xml", status_code=status.HTTP_200_OK)

    # Process message through Gemini
    reply_text = assistant.process_message(user_phone=From, incoming_text=Body.strip())
    logger.info(f"Generated reply for {From}: '{reply_text}'")

    # Return Twilio Messaging Response XML
    twiml_xml = twilio_service.build_twiml_response(reply_text)
    return Response(content=twiml_xml, media_type="application/xml")


@app.post("/telegram")
async def incoming_telegram(request: Request):
    """
    Telegram webhook endpoint for incoming messages.
    Validates sender against whitelist, passes text to Gemini, and replies via Telegram Bot API.
    """
    try:
        data = await request.json()
        message = data.get("message") or data.get("edited_message")
        if not message:
            return {"ok": True}

        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            return {"ok": True}

        logger.info(f"Incoming Telegram from {chat_id}: '{text}'")

        if not telegram_service.is_authorized_tg(chat_id):
            logger.warning(f"Unauthorized Telegram chat_id: {chat_id}")
            return {"ok": True}

        if text.startswith("/start"):
            reply_text = "ChipAI online and connected. What are we working on, Chip?"
        else:
            # Process message through Gemini
            user_identifier = f"tg_{chat_id}"
            reply_text = assistant.process_message(user_phone=user_identifier, incoming_text=text)

        # Dispatch reply back to Telegram
        sent = telegram_service.send_message(chat_id, reply_text)
        logger.info(f"Dispatched Telegram reply to {chat_id}, success: {sent}")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@app.post("/api/reminders/check")
def trigger_reminder_check():
    """Manual trigger to force a reminder check."""
    scheduler.check_and_send_due_reminders()
    return {"status": "triggered"}


@app.get("/api/reminders")
def get_reminders_status():
    """Inspect all reminders and recent conversation history."""
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders ORDER BY id DESC")
        reminders = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM conversation_history ORDER BY id DESC LIMIT 10")
        history = [dict(h) for h in cursor.fetchall()]
        return {"count": len(reminders), "reminders": reminders, "recent_history": history}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
