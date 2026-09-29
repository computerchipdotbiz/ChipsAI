import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, HTTPException, Response, status
from dotenv import load_dotenv

import database
import scheduler
import assistant
import twilio_service

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

    yield

    logger.info("Stopping background reminder scheduler...")
    scheduler.stop_scheduler()


app = FastAPI(
    title="ChipAI - Personal SMS Assistant",
    description="24/7 Always-On Gemini SMS Assistant with Proactive Reminders",
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


@app.post("/api/reminders/check")
def trigger_reminder_check():
    """Manual trigger to force a reminder check."""
    scheduler.check_and_send_due_reminders()
    return {"status": "triggered"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
