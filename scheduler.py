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

            if "quote" in text.lower():
                import assistant
                body = assistant.generate_daily_quote()
            else:
                body = f"⏰ ChipAI Reminder: {text}"
            logger.info(f"Sending due reminder #{reminder_id} to {user_phone}: {body[:50]}...")

            # Telegram is the sole communication channel
            import os
            import telegram_service

            if "tg_" in str(user_phone):
                chat_id = user_phone.replace("tg_", "")
            elif user_phone.isdigit():
                chat_id = user_phone
            else:
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "5127043704")

            sent = telegram_service.send_message(chat_id, body)

            # Mark sent to prevent endless duplicate loops
            database.mark_reminder_sent(reminder_id)
            if sent:
                logger.info(f"Reminder #{reminder_id} sent successfully to Telegram {chat_id}.")
            else:
                logger.warning(f"Reminder #{reminder_id} dispatched with warning.")

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
