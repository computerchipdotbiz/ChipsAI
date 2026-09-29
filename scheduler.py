import logging
from apscheduler.schedulers.background import BackgroundScheduler
import database
import twilio_service

logger = logging.getLogger("chipai.scheduler")

_scheduler: BackgroundScheduler | None = None


def check_and_send_due_reminders():
    """Poll the database for due reminders and dispatch SMS notifications."""
    try:
        due = database.get_due_reminders()
        if not due:
            return

        logger.info(f"Found {len(due)} due reminder(s) to dispatch.")
        for item in due:
            reminder_id = item["id"]
            user_phone = item["user_phone"]
            text = item["reminder_text"]

            body = f"⏰ ChipAI Reminder: {text}"
            logger.info(f"Sending due reminder #{reminder_id} to {user_phone}: {text}")

            if user_phone.startswith("tg_"):
                chat_id = user_phone.replace("tg_", "")
                import telegram_service
                sent = telegram_service.send_message(chat_id, body)
            else:
                sent = twilio_service.send_sms(user_phone, body)

            # Mark sent even in mock mode to avoid endless duplicate loops
            database.mark_reminder_sent(reminder_id)
            if sent:
                logger.info(f"Reminder #{reminder_id} sent successfully.")
            else:
                logger.warning(f"Reminder #{reminder_id} processed.")

    except Exception as e:
        logger.error(f"Error checking due reminders: {e}", exc_info=True)


def start_scheduler(interval_seconds: int = 15) -> BackgroundScheduler:
    """Start the background scheduler to periodically check for reminders."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        check_and_send_due_reminders,
        "interval",
        seconds=interval_seconds,
        id="check_reminders_job",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Background reminder scheduler started (interval: {interval_seconds}s).")
    return _scheduler


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Background reminder scheduler stopped.")
        _scheduler = None
