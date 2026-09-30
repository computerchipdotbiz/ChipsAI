import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, HTTPException, Response, Request, status, BackgroundTasks
from dotenv import load_dotenv

import database
import scheduler
import assistant
import twilio_service
import telegram_service
import tts_service

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
    title="Sarahzine 800 - Personal AI Assistant",
    description="24/7 Always-On Gemini Assistant with Proactive Reminders & Friend Check-ins",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Sarahzine 800 SMS Assistant",
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


async def handle_telegram_message(message: dict):
    """Background worker to process Telegram updates without blocking the webhook response."""
    try:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        # Check for incoming voice memo or audio file
        is_voice = False
        voice = message.get("voice") or message.get("audio")
        if voice and not text:
            is_voice = True
            file_id = voice.get("file_id")
            mime_type = voice.get("mime_type", "audio/ogg")
            logger.info(f"Incoming Telegram voice note from {chat_id} (file_id: {file_id}, mime: {mime_type})")
            audio_bytes = telegram_service.download_file_by_id(file_id)
            if audio_bytes:
                text = assistant.transcribe_audio(audio_bytes, mime_type=mime_type)
                logger.info(f"Transcribed voice note from {chat_id}: '{text}'")
                if not text:
                    telegram_service.send_message(
                        chat_id, "I couldn't quite catch that voice note, Chip. Could you say it again or send it as text?"
                    )
                    return
            else:
                telegram_service.send_message(
                    chat_id, "I had trouble pulling that audio file from Telegram. Mind sending it as text?"
                )
                return

        if not text:
            return

        logger.info(f"Processing Telegram message from {chat_id}: '{text}'")

        if text.startswith("/start"):
            reply_text = "Sarahzine 800 online and connected. What are we working on, Chip?"
        elif "briefing" in text.lower() or text.lower().strip() in ["/briefing", "start my day", "daily starter"]:
            reply_text = assistant.generate_morning_briefing(user_phone=f"tg_{chat_id}")
        else:
            # Process message through Gemini
            user_identifier = f"tg_{chat_id}"
            reply_text = assistant.process_message(user_phone=user_identifier, incoming_text=text)

        # Dispatch reply back to Telegram (Mirror mode: voice gets voice, text gets text)
        if is_voice:
            voice_bytes = tts_service.text_to_speech(reply_text)
            if voice_bytes:
                sent = telegram_service.send_voice(chat_id, voice_bytes, caption=reply_text)
                logger.info(f"Dispatched Telegram voice reply to {chat_id}, success: {sent}")
                if sent:
                    return
            logger.warning(f"Voice dispatch failed or empty; falling back to text for {chat_id}")

        sent = telegram_service.send_message(chat_id, reply_text)
        logger.info(f"Dispatched Telegram text reply to {chat_id}, success: {sent}")
    except Exception as e:
        logger.error(f"Error in background Telegram handler: {e}", exc_info=True)


@app.post("/telegram")
async def incoming_telegram(request: Request, background_tasks: BackgroundTasks):
    """
    Telegram webhook endpoint for incoming messages.
    Returns 200 OK immediately and handles transcription/AI/TTS in the background
    to prevent Telegram 'Read timeout expired' webhook errors.
    """
    try:
        data = await request.json()
        message = data.get("message") or data.get("edited_message")
        if not message:
            return {"ok": True}

        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return {"ok": True}

        if not telegram_service.is_authorized_tg(chat_id):
            logger.warning(f"Unauthorized Telegram chat_id: {chat_id}")
            return {"ok": True}

        # Hand off to background worker for instant response to Telegram
        background_tasks.add_task(handle_telegram_message, message)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error receiving Telegram webhook: {e}", exc_info=True)
        return {"ok": True}


@app.post("/api/reminders/check")
def trigger_reminder_check():
    """Manual trigger to force a reminder check."""
    scheduler.check_and_send_due_reminders()
    return {"status": "triggered"}


@app.post("/api/proactive/event-prep")
def trigger_event_prep_check():
    """Manual trigger to check and dispatch upcoming event prep check-ins."""
    scheduler.check_and_send_event_prep_checkins()
    return {"status": "event_prep_checked"}


@app.post("/api/proactive/friend-checkin")
def trigger_friend_checkin():
    """Manual trigger to evaluate and dispatch random friend check-ins."""
    scheduler.check_and_send_random_friend_checkin()
    return {"status": "friend_checkin_evaluated"}


@app.get("/api/proactive")
def get_proactive_checkins():
    """List sent proactive check-ins from the database."""
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proactive_checkins ORDER BY id DESC LIMIT 50")
        rows = [dict(r) for r in cursor.fetchall()]
        return {"count": len(rows), "checkins": rows}


@app.get("/api/briefing")
def preview_morning_briefing():
    """Preview today's morning starter briefing with meds reminder."""
    briefing = assistant.generate_morning_briefing()
    return {"briefing": briefing}


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


@app.post("/api/reminders/add")
def add_reminder_direct(
    text: str = Form(...),
    time_iso: str = Form(...),
    recurrence: str = Form("none"),
    user_id: str = Form("tg_5127043704"),
):
    """Direct API endpoint to add or verify a reminder."""
    utc_iso = assistant.convert_to_utc_iso(time_iso)
    rid = database.add_reminder(user_id, text, utc_iso, recurrence=recurrence)
    return {"status": "ok", "reminder_id": rid, "text": text, "scheduled_utc": utc_iso, "recurrence": recurrence}


@app.post("/api/reminders/reset")
def reset_reminder_direct(
    reminder_id: int = Form(...),
    scheduled_utc: str = Form(...),
    status: str = Form("pending"),
):
    """Reset a reminder timestamp and status back to pending."""
    with database.get_db() as conn:
        database.execute_query(
            conn,
            "UPDATE reminders SET scheduled_time = ?, status = ?, sent_at = NULL WHERE id = ?",
            (scheduled_utc, status, reminder_id),
        )
    return {"status": "ok", "reminder_id": reminder_id, "scheduled_utc": scheduled_utc}


@app.post("/api/reminders/delete")
def delete_reminder_direct(
    reminder_id: int = Form(...),
):
    """Delete a reminder row from the database."""
    with database.get_db() as conn:
        database.execute_query(
            conn,
            "DELETE FROM reminders WHERE id = ?",
            (reminder_id,),
        )
    return {"status": "ok", "deleted_id": reminder_id}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
