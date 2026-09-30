import os
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

import database
import twilio_service
from main import app


@pytest.fixture
def test_db():
    db_name = f"test_{uuid.uuid4().hex[:8]}.db"
    database.init_db(db_name)
    yield db_name
    if os.path.exists(db_name):
        try:
            os.remove(db_name)
        except Exception:
            pass


def test_database_crud(test_db):
    phone = "+15551234567"
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # Add reminders
    id1 = database.add_reminder(phone, "Take medication", past_iso, db_path=test_db)
    id2 = database.add_reminder(phone, "Call dentist", future_iso, db_path=test_db)

    assert id1 > 0
    assert id2 > 0

    # Due reminders should only return the past one
    due = database.get_due_reminders(db_path=test_db)
    assert len(due) == 1
    assert due[0]["id"] == id1
    assert due[0]["reminder_text"] == "Take medication"

    # Mark sent
    database.mark_reminder_sent(id1, db_path=test_db)
    due_after_sent = database.get_due_reminders(db_path=test_db)
    assert len(due_after_sent) == 0

    # Active reminders should show the pending one
    active = database.list_active_reminders(phone, db_path=test_db)
    assert len(active) == 1
    assert active[0]["id"] == id2

    # Cancel reminder
    cancelled = database.cancel_reminder(id2, phone, db_path=test_db)
    assert cancelled is True
    active_after_cancel = database.list_active_reminders(phone, db_path=test_db)
    assert len(active_after_cancel) == 0


def test_conversation_history(test_db):
    phone = "+15551234567"
    database.save_message(phone, "user", "Hello Chip", db_path=test_db)
    database.save_message(phone, "model", "Hello! How can I help you?", db_path=test_db)

    history = database.get_recent_history(phone, limit=5, db_path=test_db)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello Chip"
    assert history[1]["role"] == "model"


def test_phone_authorization():
    twilio_service.USER_PHONE_NUMBER = "+1 (555) 123-4567"
    assert twilio_service.is_authorized("+15551234567") is True
    assert twilio_service.is_authorized("+1-555-123-4567") is True
    assert twilio_service.is_authorized("+19998887777") is False


def test_fastapi_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

    root_res = client.get("/")
    assert root_res.status_code == 200
    assert root_res.json()["service"] == "Sarahzine 800 SMS Assistant"


def test_webhook_unauthorized():
    client = TestClient(app)
    # Whitelist is +15551234567, send from unknown number
    twilio_service.USER_PHONE_NUMBER = "+15551234567"
    response = client.post("/sms", data={"From": "+19990001111", "Body": "Hello"})
    assert response.status_code == 200
    assert response.text == "<Response></Response>"


def test_telegram_voice_webhook(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("telegram_service.download_file_by_id", lambda file_id: b"fake_audio_bytes")
    monkeypatch.setattr("assistant.transcribe_audio", lambda audio_bytes, mime_type: "Hello from voice")
    monkeypatch.setattr("assistant.process_message", lambda user_phone, incoming_text: f"Echo: {incoming_text}")
    monkeypatch.setattr("tts_service.text_to_speech", lambda text: b"fake_voice_bytes")
    sent_voices = []
    monkeypatch.setattr("telegram_service.is_authorized_tg", lambda chat_id: True)
    monkeypatch.setattr("telegram_service.send_voice", lambda chat_id, voice_bytes, caption="": sent_voices.append((chat_id, voice_bytes, caption)) or True)

    payload = {
        "message": {
            "chat": {"id": 12345},
            "voice": {"file_id": "voice_123", "mime_type": "audio/ogg"}
        }
    }
    resp = client.post("/telegram", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(sent_voices) == 1
    assert sent_voices[0][1] == b"fake_voice_bytes"
    assert sent_voices[0][2] == "Echo: Hello from voice"


def test_proactive_checkin_db_deduping(test_db):
    user = "tg_123456"
    # First insert succeeds
    ok1 = database.record_proactive_checkin(
        user, "event_prep", "event_prep_99", "Talk with Andy", "Hey, how do you feel?", db_path=test_db
    )
    assert ok1 is True
    assert database.has_proactive_checkin_been_sent(user, "event_prep_99", db_path=test_db) is True

    # Duplicate insert fails / is ignored (strict once-per-subject guarantee)
    ok2 = database.record_proactive_checkin(
        user, "event_prep", "event_prep_99", "Talk with Andy", "Hey duplicate text", db_path=test_db
    )
    assert ok2 is False

    # Check last proactive checkin
    last = database.get_last_proactive_checkin(user, db_path=test_db)
    assert last is not None
    assert last["subject_key"] == "event_prep_99"


def test_upcoming_reminders_window(test_db):
    user = "tg_123456"
    now = datetime.now(timezone.utc)
    in_30_hours = (now + timedelta(hours=30)).isoformat()
    in_72_hours = (now + timedelta(hours=72)).isoformat()

    r1 = database.add_reminder(user, "Talk to Andy about work study", in_30_hours, db_path=test_db)
    r2 = database.add_reminder(user, "Project deadline next week", in_72_hours, db_path=test_db)

    # 48-hour window should find r1 (30h away), not r2 (72h away)
    upcoming = database.get_upcoming_reminders_window(hours_ahead=48.0, db_path=test_db)
    ids = [item["id"] for item in upcoming]
    assert r1 in ids
    assert r2 not in ids


def test_count_recent_proactive_checkins(test_db):
    user = "tg_123456"
    assert database.count_recent_proactive_checkins(user, "random_friend", hours=24.0, db_path=test_db) == 0

    database.record_proactive_checkin(user, "random_friend", "topic_1", "desc", "msg1", db_path=test_db)
    assert database.count_recent_proactive_checkins(user, "random_friend", hours=24.0, db_path=test_db) == 1

    database.record_proactive_checkin(user, "random_friend", "topic_2", "desc", "msg2", db_path=test_db)
    assert database.count_recent_proactive_checkins(user, "random_friend", hours=24.0, db_path=test_db) == 2


def test_quiet_hours_logic():
    import pytz
    import assistant
    tz = pytz.timezone("America/Chicago")

    # 11:00 PM (23:00) -> quiet hours
    dt_night = tz.localize(datetime(2026, 10, 1, 23, 15))
    assert assistant.is_in_quiet_hours(dt_night) is True

    # 4:30 AM (04:30) -> quiet hours
    dt_early = tz.localize(datetime(2026, 10, 1, 4, 30))
    assert assistant.is_in_quiet_hours(dt_early) is True

    # 7:00 AM (07:00) -> waking hours (quiet hours ended)
    dt_morning = tz.localize(datetime(2026, 10, 1, 7, 0))
    assert assistant.is_in_quiet_hours(dt_morning) is False

    # 2:00 PM (14:00) -> waking hours
    dt_afternoon = tz.localize(datetime(2026, 10, 1, 14, 0))
    assert assistant.is_in_quiet_hours(dt_afternoon) is False

    # 9:59 PM (21:59) -> waking hours
    dt_evening = tz.localize(datetime(2026, 10, 1, 21, 59))
    assert assistant.is_in_quiet_hours(dt_evening) is False

    # 10:00 PM (22:00) -> quiet hours started
    dt_bedtime = tz.localize(datetime(2026, 10, 1, 22, 0))
    assert assistant.is_in_quiet_hours(dt_bedtime) is True


def test_event_prep_routine_skipping():
    import assistant
    # Automated routine tasks return None/skipped
    assert assistant.generate_event_prep_checkin("Daily quote", "2026-10-01T14:00:00") is None
    assert assistant.generate_event_prep_checkin("Take blood pressure medicine", "2026-10-01T14:00:00") is None

    # Meaningful event returns proactive prep prompt text without em dashes
    text = assistant.generate_event_prep_checkin("Talk to Andy about his work study plans", "2026-10-01T14:00:00")
    assert text is not None
    assert "Andy" in text or "work study" in text
    assert "—" not in text


def test_random_friend_topics_generation():
    import assistant
    assert len(assistant.FRIEND_TOPICS) >= 5
    for topic in assistant.FRIEND_TOPICS:
        msg = assistant.generate_random_friend_checkin(topic)
        assert msg is not None
        assert len(msg) > 10
        assert "—" not in msg


def test_outlier_tasks_for_today(test_db):
    user = "tg_123456"
    import pytz
    tz = pytz.timezone("America/Chicago")
    now_local = datetime.now(tz)

    # 1. One-shot task scheduled for today at 3pm
    today_3pm = now_local.replace(hour=15, minute=0, second=0).astimezone(timezone.utc).isoformat()
    # 2. Daily recurring task scheduled for today at 4pm
    today_4pm = now_local.replace(hour=16, minute=0, second=0).astimezone(timezone.utc).isoformat()
    # 3. One-shot task scheduled for tomorrow
    tomorrow_3pm = (now_local + timedelta(days=1)).replace(hour=15, minute=0, second=0).astimezone(timezone.utc).isoformat()

    r1 = database.add_reminder(user, "Dentist appointment", today_3pm, recurrence="none", db_path=test_db)
    r2 = database.add_reminder(user, "Daily vitamins", today_4pm, recurrence="daily", db_path=test_db)
    r3 = database.add_reminder(user, "Car oil change", tomorrow_3pm, recurrence="none", db_path=test_db)

    outliers = database.get_outlier_tasks_for_today(user_timezone="America/Chicago", db_path=test_db)
    outlier_ids = [t["id"] for t in outliers]

    # Only r1 should be in today's outlier list (r2 is recurring daily, r3 is tomorrow)
    assert r1 in outlier_ids
    assert r2 not in outlier_ids
    assert r3 not in outlier_ids
    assert outliers[0]["text"] == "Dentist appointment"
    assert "3:00 PM" in outliers[0]["time_str"]


def test_morning_briefing_starts_with_take_your_meds():
    import assistant
    briefing = assistant.generate_morning_briefing()

    # 1. Must start with TAKE YOUR MEDS for Pixel 9 Pro XL notification banner
    assert briefing.startswith("TAKE YOUR MEDS.")

    # 2. Weather
    assert "Weather" in briefing
    assert "Mansfield, TX" in briefing

    # 3. Birthday
    assert "Today's Birthday" in briefing

    # 4. Headline
    assert "Top Headline" in briefing

    # 5. Weird Factoid
    assert "Weird Factoid" in briefing

    # 6. Jesus Teaching
    assert "Daily Teaching" in briefing

    # 7. Motivation
    assert "Motivation" in briefing

    # 8. Outlier Tasks
    assert "Today's Outlier Tasks" in briefing

    # Formatting rule: No em dashes
    assert "—" not in briefing


def test_api_briefing_endpoint():
    client = TestClient(app)
    res = client.get("/api/briefing")
    assert res.status_code == 200
    data = res.json()
    assert "briefing" in data
    assert data["briefing"].startswith("TAKE YOUR MEDS.")


def test_user_memories_crud(test_db):
    user = "tg_123456"
    # 1. Save new memory
    m1 = database.save_or_update_memory(user, "person", "Andy", "Wants to study IT certifications", db_path=test_db)
    assert m1 > 0

    # 2. Update existing memory for same subject
    m2 = database.save_or_update_memory(user, "person", "Andy", "Decided on cybersecurity certifications", db_path=test_db)
    assert m2 == m1

    # 3. Save second memory
    m3 = database.save_or_update_memory(user, "food", "Greek Spot", "Jen loves the gyro platter in Arlington", db_path=test_db)
    assert m3 != m1

    # 4. Retrieve memories
    all_mems = database.get_user_memories(user, db_path=test_db)
    assert len(all_mems) == 2
    assert any(m["subject"] == "Andy" and "cybersecurity" in m["detail"] for m in all_mems)

    # 5. Search memories
    matches = database.search_user_memories(user, "gyro", db_path=test_db)
    assert len(matches) == 1
    assert matches[0]["subject"] == "Greek Spot"

    # 6. Summary format
    summary = database.format_user_memories_summary(user, db_path=test_db)
    assert "[person/Andy]" in summary or "[food/Greek Spot]" in summary

    # 7. Delete memory
    ok = database.delete_user_memory(m3, user_phone=user, db_path=test_db)
    assert ok is True
    assert len(database.get_user_memories(user, db_path=test_db)) == 1


def test_memory_tools_execution(test_db, monkeypatch):
    import assistant
    monkeypatch.setattr(database, "DB_FILE", test_db)
    user = "tg_123456"

    # Test save_memory tool
    res = assistant.execute_tool("save_memory", {"category": "tech", "subject": "PLAUD", "detail": "NotePin voice recorder"}, user)
    assert res.get("success") is True
    mem_id = res.get("memory_id")
    assert mem_id > 0

    # Test recall_memories tool
    res2 = assistant.execute_tool("recall_memories", {"query": "NotePin"}, user)
    assert res2.get("success") is True
    assert res2.get("count") >= 1

    # Test delete_memory tool
    res3 = assistant.execute_tool("delete_memory", {"memory_id": mem_id}, user)
    assert res3.get("success") is True


def test_snooze_and_complete_reminder(test_db):
    user = "tg_123456"
    in_5_min = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    rid = database.add_reminder(user, "Take vitamins", in_5_min, db_path=test_db)

    # Snooze by 30 minutes
    ok = database.snooze_reminder(rid, minutes=30, db_path=test_db)
    assert ok is True
    reminders = database.list_active_reminders(db_path=test_db)
    r = next(item for item in reminders if item["id"] == rid)
    assert r["scheduled_time"] > in_5_min

    # Complete reminder
    ok2 = database.complete_reminder(rid, db_path=test_db)
    assert ok2 is True
    reminders_after = database.list_active_reminders(db_path=test_db)
    assert all(item["id"] != rid for item in reminders_after)


def test_api_memories_endpoint(test_db, monkeypatch):
    monkeypatch.setattr(database, "DB_FILE", test_db)
    client = TestClient(app)

    # 1. Add memory via API
    res = client.post("/api/memories/add", data={"subject": "Car", "detail": "2025 Hyundai Elantra Hybrid Blue", "category": "vehicle", "user_id": "tg_test"})
    assert res.status_code == 200
    mid = res.json()["memory_id"]

    # 2. Get memories via API
    res2 = client.get("/api/memories?user_id=tg_test")
    assert res2.status_code == 200
    assert res2.json()["count"] == 1
    assert res2.json()["memories"][0]["subject"] == "Car"

    # 3. Delete memory via API
    res3 = client.post("/api/memories/delete", data={"memory_id": mid, "user_id": "tg_test"})
    assert res3.status_code == 200
    assert res3.json()["deleted"] is True



