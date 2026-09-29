import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Dict, Any, Generator

DB_FILE = os.getenv("DATABASE_PATH", "reminders.db")


@contextmanager
def get_db(db_path: str = DB_FILE) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections that ensures commit and proper closure."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_FILE) -> None:
    """Initialize database tables for reminders and message history."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone TEXT NOT NULL,
                reminder_text TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, scheduled_time)"
        )


def add_reminder(
    user_phone: str,
    reminder_text: str,
    scheduled_time_utc: str,
    db_path: str = DB_FILE,
) -> int:
    """Schedule a new reminder. scheduled_time_utc must be ISO 8601 UTC string."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reminders (user_phone, reminder_text, scheduled_time, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (user_phone, reminder_text, scheduled_time_utc, now_iso),
        )
        return cursor.lastrowid


def get_due_reminders(db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    """Return all pending reminders whose scheduled_time is less than or equal to now."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_phone, reminder_text, scheduled_time, created_at
            FROM reminders
            WHERE status = 'pending' AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
            """,
            (now_iso,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_reminder_sent(reminder_id: int, db_path: str = DB_FILE) -> None:
    """Mark a reminder as sent."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminders
            SET status = 'sent', sent_at = ?
            WHERE id = ?
            """,
            (now_iso, reminder_id),
        )


def list_active_reminders(user_phone: str, db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    """List pending upcoming reminders for the user."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, reminder_text, scheduled_time, created_at
            FROM reminders
            WHERE user_phone = ? AND status = 'pending'
            ORDER BY scheduled_time ASC
            """,
            (user_phone,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def cancel_reminder(reminder_id: int, user_phone: str, db_path: str = DB_FILE) -> bool:
    """Cancel a pending reminder."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminders
            SET status = 'cancelled'
            WHERE id = ? AND user_phone = ? AND status = 'pending'
            """,
            (reminder_id, user_phone),
        )
        return cursor.rowcount > 0


def save_message(user_phone: str, role: str, content: str, db_path: str = DB_FILE) -> None:
    """Save a user or assistant message to history."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversation_history (user_phone, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_phone, role, content, now_iso),
        )


def get_recent_history(
    user_phone: str, limit: int = 6, db_path: str = DB_FILE
) -> List[Dict[str, str]]:
    """Retrieve recent conversation history for context."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content
            FROM conversation_history
            WHERE user_phone = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_phone, limit),
        )
        rows = cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
