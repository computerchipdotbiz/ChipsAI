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
    assert root_res.json()["service"] == "ChipAI SMS Assistant"


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
