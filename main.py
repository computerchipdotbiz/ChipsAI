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


async def handle_telegram_callback(callback_query: dict):
    """Handle interactive inline keyboard clicks (e.g. reminder completion or snooze)."""
    try:
        query_id = callback_query.get("id")
        data_str = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        orig_text = message.get("text", "")

        logger.info(f"Received Telegram callback: query_id={query_id}, data='{data_str}' from chat_id={chat_id}")

        if data_str.startswith("rem_done:"):
            rem_id = int(data_str.split(":")[1])
            database.complete_reminder(rem_id)
            telegram_service.answer_callback_query(query_id, text="Marked as done! 👍")
            updated_text = f"{orig_text}\n\n✅ Marked as completed!"
            telegram_service.edit_message_text(chat_id, message_id, text=updated_text)
            logger.info(f"Reminder #{rem_id} completed via Telegram inline button.")

        elif data_str.startswith("rem_snooze:"):
            parts = data_str.split(":")
            rem_id = int(parts[1])
            minutes = int(parts[2]) if len(parts) > 2 else 30
            database.snooze_reminder(rem_id, minutes=minutes)
            telegram_service.answer_callback_query(query_id, text=f"Snoozed for {minutes}m! ⏰")
            updated_text = f"{orig_text}\n\n⏰ Snoozed for {minutes} minutes."
            telegram_service.edit_message_text(chat_id, message_id, text=updated_text)
            logger.info(f"Reminder #{rem_id} snoozed {minutes}m via Telegram inline button.")
        else:
            telegram_service.answer_callback_query(query_id)

    except Exception as e:
        logger.error(f"Error handling Telegram callback: {e}", exc_info=True)


async def handle_telegram_message(message: dict):
    """Background worker to process Telegram updates without blocking the webhook response."""
    try:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        user_identifier = f"tg_{chat_id}"

        # 1. Check for incoming photo or image document (Vision)
        photos = message.get("photo")
        doc = message.get("document")
        is_image = False
        img_bytes = None
        img_mime = "image/jpeg"

        if photos:
            is_image = True
            file_id = photos[-1]["file_id"]
            img_bytes = telegram_service.download_file_by_id(file_id)
        elif doc and doc.get("mime_type", "").startswith("image/"):
            is_image = True
            file_id = doc.get("file_id")
            img_mime = doc.get("mime_type", "image/jpeg")
            img_bytes = telegram_service.download_file_by_id(file_id)

        if is_image:
            caption = message.get("caption", "").strip()
            logger.info(f"Processing Telegram photo from {chat_id} (caption: '{caption}')")
            if img_bytes:
                reply_text = assistant.process_image_message(user_identifier, img_bytes, caption, mime_type=img_mime)
            else:
                reply_text = "I received your photo but had trouble pulling the image file from Telegram. Mind sending it again?"
            sent = telegram_service.send_message(chat_id, reply_text)
            logger.info(f"Dispatched Telegram photo reply to {chat_id}, success: {sent}")
            return

        # 2. Check for incoming voice memo or audio file
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

        # 3. Direct shortcuts and commands
        clean_lower = text.lower().strip()
        if text.startswith("/start"):
            reply_text = "Sarahzine 800 online and connected. What are we working on, Chip?"

        elif "briefing" in clean_lower or clean_lower in ["/briefing", "start my day", "daily starter"]:
            reply_text = assistant.generate_morning_briefing(user_phone=user_identifier)

        elif clean_lower.startswith("/memories") or clean_lower in ["memories", "show memories", "what do you remember"]:
            mems = database.get_user_memories(user_identifier, limit=50)
            if not mems:
                reply_text = "🧠 Memory Bank is currently empty. As you share facts about your life, work, preferences, and family, I will store them here!"
            else:
                lines = ["🧠 **Sarahzine 800 Memory Bank:**\n"]
                for m in mems:
                    lines.append(f"• `#{m['id']}` [{m['category']}/{m['subject']}]: {m['detail']}")
                lines.append("\n_Use `/forget <id>` to remove any memory, or `/remember <fact>` to save a new one._")
                reply_text = "\n".join(lines)

        elif clean_lower.startswith("/forget"):
            parts = text.strip().split()
            if len(parts) > 1 and parts[1].isdigit():
                target_id = int(parts[1])
                ok = database.delete_user_memory(target_id, user_phone=user_identifier)
                if ok:
                    reply_text = f"🗑️ Memory `#{target_id}` has been deleted from my memory bank."
                else:
                    reply_text = f"Couldn't find memory `#{target_id}` to delete."
            else:
                reply_text = "Usage: `/forget <id>` (e.g. `/forget 3`)"

        elif clean_lower.startswith("/remember"):
            fact_text = text[len("/remember"):].strip()
            if fact_text:
                mem_id = database.save_or_update_memory(user_identifier, "general", fact_text[:30], fact_text)
                reply_text = f"🧠 Saved memory `#{mem_id}`: '{fact_text}'"
            else:
                reply_text = "Usage: `/remember <fact to remember>`"

        elif clean_lower.startswith("/ebook") or clean_lower.startswith("/books"):
            # Check for query
            query = ""
            for prefix in ["/ebooks", "/ebook", "/books", "/book"]:
                if clean_lower.startswith(prefix):
                    query = text[len(prefix):].strip()
                    break

            summary = database.get_ebook_library_summary()
            if not query:
                sample = database.search_ebooks(limit=10)
                fmt_str = ", ".join(f"{fmt}: {cnt}" for fmt, cnt in summary.get("formats", {}).items())
                lines = [
                    f"📚 **Sarahzine Ebook Library:**\n",
                    f"You have **{summary['total_books']}** ebooks indexed under `Z:\\My Drive\\03_Reading & Library\\Ebooks`.\n",
                    f"**Formats:** {fmt_str}\n",
                    "**Featured / Sample Titles:**",
                ]
                for b in sample:
                    lines.append(f"• **{b['title']}** `[{b['format']}]`")
                lines.append("\n_Search your full library anytime with `/ebook <title or keyword>`!_")
                reply_text = "\n".join(lines)
            else:
                matches = database.search_ebooks(query=query, limit=15)
                if not matches:
                    reply_text = f"📚 No ebooks found matching '{query}'. You have {summary['total_books']} total books indexed."
                else:
                    lines = [f"📚 Found {len(matches)} ebook(s) matching '{query}':\n"]
                    for b in matches:
                        lines.append(f"• **{b['title']}** `[{b['format']} - {b['size_mb']}MB]`\n  📁 _{b['category']}_")
                    reply_text = "\n".join(lines)

        else:
            # Process message through Gemini
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
    Telegram webhook endpoint for incoming messages and interactive button clicks.
    Returns 200 OK immediately and handles AI/multimodal in the background
    to prevent Telegram 'Read timeout expired' webhook errors.
    """
    try:
        data = await request.json()

        # Handle interactive button callback queries
        callback_query = data.get("callback_query")
        if callback_query:
            from_user = callback_query.get("from", {})
            user_id = from_user.get("id")
            if not telegram_service.is_authorized_tg(user_id):
                logger.warning(f"Unauthorized Telegram callback query from: {user_id}")
                return {"ok": True}
            background_tasks.add_task(handle_telegram_callback, callback_query)
            return {"ok": True}

        # Handle regular messages
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


@app.get("/api/memories")
def get_memories_api(user_id: str = "tg_5127043704"):
    """List stored memories for a user."""
    memories = database.get_user_memories(user_id, limit=100)
    return {"status": "ok", "count": len(memories), "memories": memories}


@app.post("/api/memories/add")
def add_memory_api(
    subject: str = Form(...),
    detail: str = Form(...),
    category: str = Form("general"),
    user_id: str = Form("tg_5127043704"),
):
    """Save or update a memory directly."""
    mem_id = database.save_or_update_memory(user_id, category, subject, detail)
    return {"status": "ok", "memory_id": mem_id, "subject": subject, "detail": detail}


@app.post("/api/memories/delete")
def delete_memory_api(
    memory_id: int = Form(...),
    user_id: str = Form("tg_5127043704"),
):
    """Delete a memory by its ID."""
    ok = database.delete_user_memory(memory_id, user_phone=user_id)
    return {"status": "ok", "deleted": ok, "memory_id": memory_id}


@app.get("/api/ebooks")
def get_ebooks_api(query: str = ""):
    """List or search indexed ebooks."""
    summary = database.get_ebook_library_summary()
    books = database.search_ebooks(query=query, limit=50)
    return {
        "status": "ok",
        "total_in_library": summary["total_books"],
        "match_count": len(books),
        "query": query,
        "books": books,
    }


@app.post("/api/proactive/evening")
def trigger_evening_decompression():
    """Manual trigger to evaluate and dispatch evening decompression check-in."""
    scheduler.check_and_send_evening_decompression()
    return {"status": "evening_decompression_checked"}


@app.get("/api/weather/alerts")
def get_weather_alerts_api():
    """Fetch active severe weather warnings for Mansfield from NWS."""
    alerts = assistant.check_nws_weather_alerts()
    return {"status": "ok", "alert_count": len(alerts), "alerts": alerts}


@app.post("/api/weather/check")
def trigger_weather_check():
    """Manual trigger to poll NWS and dispatch any active weather alerts."""
    scheduler.check_and_send_weather_alerts()
    return {"status": "weather_alerts_checked"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
