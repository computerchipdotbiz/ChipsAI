import os
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import database
import telegram_service
import assistant

logger = logging.getLogger("chipai.scheduler")

_scheduler: BackgroundScheduler | None = None


def _resolve_telegram_chat_id(user_phone: str) -> str:
    """Resolve Telegram chat ID from user identifier."""
    if "tg_" in str(user_phone):
        return str(user_phone).replace("tg_", "")
    elif str(user_phone).isdigit():
        return str(user_phone)
    return os.getenv("TELEGRAM_CHAT_ID", "5127043704")


def check_and_send_due_reminders():
    """Poll the database for due reminders and dispatch notifications."""
    try:
        due = database.get_due_reminders()
        if not due:
            return

        logger.info(f"Found {len(due)} due reminder(s) to dispatch.")
        for item in due:
            reminder_id = item["id"]
            user_phone = item["user_phone"]
            text = item["reminder_text"]

            if any(k in text.lower() for k in ["effexor", "meds", "medication", "medicine", "creatine"]):
                body = assistant.generate_morning_briefing(user_phone)
            elif "quote" in text.lower():
                body = assistant.generate_daily_quote()
            else:
                body = f"⏰ Sarahzine 800 Reminder: {text}"
            logger.info(f"Sending due reminder #{reminder_id} to {user_phone}: {body[:50]}...")

            chat_id = _resolve_telegram_chat_id(user_phone)
            reply_markup = None
            if "quote" not in text.lower():
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Done / Taken", "callback_data": f"rem_done:{reminder_id}"},
                            {"text": "⏰ Snooze 30m", "callback_data": f"rem_snooze:{reminder_id}:30"},
                        ]
                    ]
                }
            sent = telegram_service.send_message(chat_id, body, reply_markup=reply_markup)

            # Mark sent to prevent endless duplicate loops
            database.mark_reminder_sent(reminder_id)
            if sent:
                logger.info(f"Reminder #{reminder_id} sent successfully to Telegram {chat_id}.")
            else:
                logger.warning(f"Reminder #{reminder_id} dispatched with warning.")

    except Exception as e:
        logger.error(f"Error checking due reminders: {e}", exc_info=True)


def check_and_send_event_prep_checkins():
    """Check for upcoming events/talks in the next 24 to 48 hours and send an anticipatory prep check-in.
    Strictly respects quiet hours (10:00 PM - 7:00 AM) and dedupes once per subject.
    """
    try:
        # Strict quiet hours: after 10 PM and before 7 AM
        if assistant.is_in_quiet_hours():
            logger.debug("Quiet hours active (10:00 PM - 7:00 AM). Skipping proactive event prep check-ins.")
            return

        # Look up pending one-shot reminders scheduled within the next 24 to 48 hours
        upcoming = database.get_upcoming_reminders_window(hours_ahead=48.0)
        if not upcoming:
            return

        for item in upcoming:
            reminder_id = item["id"]
            reminder_phone = item["user_phone"]
            text = item["reminder_text"]
            subject_key = f"event_prep_{reminder_id}"

            # Strict deduplication: check if prep check-in for this reminder already sent
            if database.has_proactive_checkin_been_sent(reminder_phone, subject_key):
                continue

            # Generate authentic friend prep message via Gemini
            msg = assistant.generate_event_prep_checkin(text, item["scheduled_time"])
            if not msg:
                # If automated chore or skipped, mark as handled so we don't re-evaluate
                database.record_proactive_checkin(
                    reminder_phone, "event_prep_skipped", subject_key, text, "SKIPPED"
                )
                continue

            chat_id = _resolve_telegram_chat_id(reminder_phone)
            sent = telegram_service.send_message(chat_id, msg)
            if sent:
                # Save into conversation history so when Chip texts back, Sarahzine has context
                database.save_message(reminder_phone, "model", msg)
                database.record_proactive_checkin(
                    reminder_phone, "event_prep", subject_key, text, msg
                )
                logger.info(f"Proactive event prep check-in sent for #{reminder_id} to Telegram {chat_id}.")

    except Exception as e:
        logger.error(f"Error checking proactive event prep check-ins: {e}", exc_info=True)


def check_and_send_random_friend_checkin():
    """Periodically reach out like a true friend on diverse life topics (1 to 2 times per day).
    Strictly honors quiet hours (10pm-7am), max 2 friend check-ins per day, and subject deduping.
    """
    try:
        # Strict quiet hours: after 10 PM and before 7 AM
        if assistant.is_in_quiet_hours():
            logger.debug("Quiet hours active (10:00 PM - 7:00 AM). Skipping random friend check-in.")
            return

        default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5127043704")
        user_phone = f"tg_{default_chat_id}"

        # Max 2 friend check-ins per 24 hours
        recent_count = database.count_recent_proactive_checkins(user_phone, "random_friend", hours=24.0)
        if recent_count >= 2:
            logger.debug("Daily pacing reached: already sent 2 random friend check-ins in the last 24 hours.")
            return

        # Subject deduplication: Find topics that haven't been asked about yet
        candidates = [
            t for t in assistant.FRIEND_TOPICS
            if not database.has_proactive_checkin_been_sent(user_phone, f"friend_topic_{t['slug']}")
        ]

        if not candidates:
            # If all individual topics have been sent once, cycle using ISO week stamp
            week_key = datetime.now(timezone.utc).strftime("%Y_w%W")
            candidates = [
                t for t in assistant.FRIEND_TOPICS
                if not database.has_proactive_checkin_been_sent(user_phone, f"friend_topic_{t['slug']}_{week_key}")
            ]
            if not candidates:
                logger.debug("All friend check-in subjects exhausted for the current weekly cycle.")
                return
            chosen_topic = candidates[0]
            subject_key = f"friend_topic_{chosen_topic['slug']}_{week_key}"
        else:
            chosen_topic = candidates[0]
            subject_key = f"friend_topic_{chosen_topic['slug']}"

        # Generate authentic, peer-level casual message
        msg = assistant.generate_random_friend_checkin(chosen_topic)
        chat_id = _resolve_telegram_chat_id(user_phone)
        sent = telegram_service.send_message(chat_id, msg)
        if sent:
            database.save_message(user_phone, "model", msg)
            database.record_proactive_checkin(
                user_phone, "random_friend", subject_key, chosen_topic["prompt"], msg
            )
            logger.info(f"Random friend check-in ({subject_key}) sent to Telegram {chat_id}.")

    except Exception as e:
        logger.error(f"Error checking random friend check-in: {e}", exc_info=True)


def check_and_send_evening_decompression():
    """Evening shutdown check-in around 8:30 PM Central.
    Dedupes so it only fires once per day.
    """
    try:
        import pytz
        tz = pytz.timezone(os.getenv("USER_TIMEZONE", "America/Chicago"))
        now_local = datetime.now(tz)

        # Trigger window: 8:25 PM to 9:15 PM (20:25 - 21:15)
        if now_local.hour != 20 and (now_local.hour != 21 or now_local.minute > 15):
            return

        default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5127043704")
        user_phone = f"tg_{default_chat_id}"
        date_str = now_local.strftime("%Y-%m-%d")
        subject_key = f"evening_decompression_{date_str}"

        if database.has_proactive_checkin_been_sent(user_phone, subject_key):
            return

        msg = assistant.generate_evening_decompression(user_phone)
        chat_id = _resolve_telegram_chat_id(user_phone)
        sent = telegram_service.send_message(chat_id, msg)
        if sent:
            database.save_message(user_phone, "model", msg)
            database.record_proactive_checkin(
                user_phone, "evening_decompression", subject_key, "Evening shutdown / cognitive decompression", msg
            )
            logger.info(f"Evening decompression check-in sent to Telegram {chat_id}.")
    except Exception as e:
        logger.error(f"Error checking evening decompression: {e}", exc_info=True)


def check_and_send_weather_alerts():
    """Check National Weather Service for active severe weather warnings in Mansfield/DFW.
    Dedupes so each unique alert ID is only sent once.
    """
    try:
        alerts = assistant.check_nws_weather_alerts()
        if not alerts:
            return

        default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5127043704")
        user_phone = f"tg_{default_chat_id}"
        chat_id = _resolve_telegram_chat_id(user_phone)

        for alert in alerts:
            alert_id = alert["id"]
            subject_key = f"weather_alert_{alert_id}"

            if database.has_proactive_checkin_been_sent(user_phone, subject_key):
                continue

            msg = assistant.format_weather_alert_message(alert)
            sent = telegram_service.send_message(chat_id, msg)
            if sent:
                database.record_proactive_checkin(
                    user_phone, "weather_alert", subject_key, alert.get("headline", ""), msg
                )
                logger.info(f"Severe weather alert sent ({alert.get('event')}) to Telegram {chat_id}.")
    except Exception as e:
        logger.error(f"Error checking weather alerts: {e}", exc_info=True)


def check_inventory_watches():
    """Scan all active tech inventory items (e.g. Nvidia DGX Spark) and alert Chip if in stock or updated."""
    try:
        # Respect quiet hours to avoid waking Chip
        if assistant.is_in_quiet_hours():
            logger.debug("Quiet hours active. Skipping inventory checks.")
            return

        watches = database.get_active_inventory_watches()
        if not watches:
            return

        import web_service
        logger.info(f"Checking {len(watches)} active tech inventory watches...")

        for watch in watches:
            watch_id = watch["id"]
            user_phone = watch["user_phone"]
            product_name = watch["product_name"]
            retailers_str = watch.get("retailers", "all")
            retailers = [r.strip() for r in retailers_str.split(",")] if retailers_str != "all" else None

            scan_res = web_service.check_tech_resellers(product_name, target_resellers=retailers)
            overall_status = scan_res.get("overall_availability", "Unknown")
            prices = scan_res.get("detected_prices", [])
            price_str = prices[0] if prices else "Custom Enterprise Quote"
            listings = scan_res.get("listings", [])

            best_listing = listings[0] if listings else {}
            top_retailer = best_listing.get("reseller", "Retailer")
            top_url = best_listing.get("url", "")

            prev_status = watch.get("last_status", "unknown")
            database.update_inventory_watch(watch_id, overall_status, price_str, top_retailer, top_url)

            # Alert if newly in stock or newly detected
            should_alert = False
            if overall_status == "In Stock" and prev_status != "In Stock":
                should_alert = True
            elif prev_status == "pending_scan" and listings:
                should_alert = True

            if should_alert:
                chat_id = _resolve_telegram_chat_id(user_phone)
                alert_text = (
                    f"🚨 **Sarahzine Hardware Radar Update!**\n\n"
                    f"Found an inventory update for **{product_name}**:\n"
                    f"• **Status:** {overall_status}\n"
                    f"• **Price:** {price_str}\n"
                    f"• **Store:** {top_retailer}\n"
                )
                if top_url:
                    alert_text += f"• **Link:** {top_url}\n"

                sent = telegram_service.send_message(chat_id, alert_text)
                if sent:
                    logger.info(f"Inventory watch alert sent to {chat_id} for {product_name}.")
    except Exception as e:
        logger.error(f"Error checking inventory watches: {e}", exc_info=True)


def start_scheduler(interval_seconds: int = 15) -> BackgroundScheduler:
    """Start the background scheduler for reminders, event prep, and friend check-ins."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()

    # 1. Exact due reminders (every 15s)
    _scheduler.add_job(
        check_and_send_due_reminders,
        "interval",
        seconds=interval_seconds,
        id="check_reminders_job",
        replace_existing=True,
    )

    # 2. Anticipatory event prep check-ins (evaluates ~10h upcoming tasks every 5 minutes)
    _scheduler.add_job(
        check_and_send_event_prep_checkins,
        "interval",
        minutes=5,
        id="check_event_prep_job",
        replace_existing=True,
    )

    # 3. Random friend check-ins (evaluates quiet hours & daily pacing every 30 minutes)
    _scheduler.add_job(
        check_and_send_random_friend_checkin,
        "interval",
        minutes=30,
        id="check_friend_checkin_job",
        replace_existing=True,
    )

    # 4. Evening decompression check-in (checks every 10m around 8:30pm)
    _scheduler.add_job(
        check_and_send_evening_decompression,
        "interval",
        minutes=10,
        id="check_evening_decompression_job",
        replace_existing=True,
    )

    # 5. Severe weather radar alerts (checks NWS every 5m)
    _scheduler.add_job(
        check_and_send_weather_alerts,
        "interval",
        minutes=5,
        id="check_weather_alerts_job",
        replace_existing=True,
    )

    # 6. Tech hardware inventory watches (checks every 2 hours)
    _scheduler.add_job(
        check_inventory_watches,
        "interval",
        hours=2,
        id="check_inventory_watches_job",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Background scheduler started with reminders, event prep, friend pings, evening decompression, and weather radar.")
    return _scheduler


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped.")
        _scheduler = None

