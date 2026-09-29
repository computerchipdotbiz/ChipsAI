import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Dict, Any, Generator, Optional

load_dotenv = None
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logger = logging.getLogger("chipai.database")

DB_FILE = os.getenv("DATABASE_PATH", "reminders.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")

_initialized_dbs = set()


def is_postgres() -> bool:
    return bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")))


def _create_tables_sqlite(conn: sqlite3.Connection) -> None:
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
            sent_at TEXT,
            recurrence TEXT NOT NULL DEFAULT 'none'
        )
        """
    )
    try:
        cursor.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'none'")
    except Exception:
        pass

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
    conn.commit()


def _create_tables_postgres(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            reminder_text TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            sent_at TEXT,
            recurrence TEXT NOT NULL DEFAULT 'none'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_history (
            id SERIAL PRIMARY KEY,
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
    conn.commit()


@contextmanager
def get_db(db_path: str = DB_FILE) -> Generator[Any, None, None]:
    """Context manager yielding SQLite or PostgreSQL connection based on DATABASE_URL."""
    if is_postgres():
        import psycopg2
        import psycopg2.extras

        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        if url not in _initialized_dbs:
            _create_tables_postgres(conn)
            _initialized_dbs.add(url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        if db_path not in _initialized_dbs:
            _create_tables_sqlite(conn)
            _initialized_dbs.add(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def execute_query(conn, query: str, params: tuple = ()):
    """Execute query with automatic placeholder translation (? to %s for Postgres)."""
    cursor = conn.cursor()
    if is_postgres():
        query = query.replace("?", "%s")
    cursor.execute(query, params)
    return cursor


def init_db(db_path: str = DB_FILE) -> None:
    """Initialize database tables."""
    with get_db(db_path):
        pass


def calculate_next_occurrence(current_time_iso: str, recurrence: str) -> Optional[str]:
    """Calculate the next ISO timestamp for a recurring reminder."""
    from datetime import datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(current_time_iso)
        now = datetime.now(timezone.utc)

        if recurrence == "daily":
            next_dt = dt + timedelta(days=1)
            while next_dt <= now:
                next_dt += timedelta(days=1)
            return next_dt.isoformat()

        elif recurrence == "weekdays":
            next_dt = dt + timedelta(days=1)
            while next_dt.weekday() >= 5:  # 5=Sat, 6=Sun
                next_dt += timedelta(days=1)
            while next_dt <= now:
                next_dt += timedelta(days=1)
                while next_dt.weekday() >= 5:
                    next_dt += timedelta(days=1)
            return next_dt.isoformat()

        elif recurrence == "weekly":
            next_dt = dt + timedelta(days=7)
            while next_dt <= now:
                next_dt += timedelta(days=7)
            return next_dt.isoformat()

        elif recurrence.startswith("days:"):
            # e.g. "days:tue,thu"
            day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            raw_days = recurrence.split(":", 1)[1].lower().split(",")
            target_weekdays = set()
            for d in raw_days:
                d = d.strip()
                if d in day_map:
                    target_weekdays.add(day_map[d])
                elif d.isdigit():
                    target_weekdays.add(int(d))

            if target_weekdays:
                next_dt = dt + timedelta(days=1)
                while next_dt.weekday() not in target_weekdays:
                    next_dt += timedelta(days=1)
                while next_dt <= now:
                    next_dt += timedelta(days=1)
                    while next_dt.weekday() not in target_weekdays:
                        next_dt += timedelta(days=1)
                return next_dt.isoformat()

        elif recurrence.startswith("monthly:"):
            # e.g. "monthly:6,21"
            dates = sorted([int(x.strip()) for x in recurrence.split(":", 1)[1].split(",") if x.strip().isdigit()])
            if dates:
                next_dt = dt + timedelta(days=1)
                while next_dt.day not in dates:
                    next_dt += timedelta(days=1)
                while next_dt <= now:
                    next_dt += timedelta(days=1)
                    while next_dt.day not in dates:
                        next_dt += timedelta(days=1)
                return next_dt.isoformat()

    except Exception:
        pass
    return None


def add_reminder(
    user_phone: str,
    reminder_text: str,
    scheduled_time_utc: str,
    recurrence: str = "none",
    db_path: str = DB_FILE,
) -> int:
    """Schedule a new reminder. Supports recurrence: 'none', 'daily', 'weekdays', 'weekly', 'days:...', 'monthly:...'."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            INSERT INTO reminders (user_phone, reminder_text, scheduled_time, status, created_at, recurrence)
            VALUES (?, ?, ?, 'pending', ?, ?)
            RETURNING id
            """,
            (user_phone, reminder_text, scheduled_time_utc, now_iso, recurrence or "none"),
        )
        row = cursor.fetchone()
        return row[0] if isinstance(row, (tuple, list)) else row["id"]


def get_due_reminders(db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    """Return all pending reminders whose scheduled_time is less than or equal to now."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id, user_phone, reminder_text, scheduled_time, created_at, recurrence
            FROM reminders
            WHERE status = 'pending' AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
            """,
            (now_iso,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_reminder_sent(reminder_id: int, db_path: str = DB_FILE) -> None:
    """Mark a reminder as sent, or reschedule it for the next occurrence if recurring."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            "SELECT scheduled_time, recurrence FROM reminders WHERE id = ?",
            (reminder_id,),
        )
        row = cursor.fetchone()
        if row and row["recurrence"] and row["recurrence"] != "none":
            next_time = calculate_next_occurrence(row["scheduled_time"], row["recurrence"])
            if next_time:
                execute_query(
                    conn,
                    """
                    UPDATE reminders
                    SET scheduled_time = ?, sent_at = ?, status = 'pending'
                    WHERE id = ?
                    """,
                    (next_time, now_iso, reminder_id),
                )
                return

        # Default one-shot reminder: mark sent
        execute_query(
            conn,
            """
            UPDATE reminders
            SET status = 'sent', sent_at = ?
            WHERE id = ?
            """,
            (now_iso, reminder_id),
        )


def list_active_reminders(user_phone: Optional[str] = None, db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    """List pending upcoming reminders for Chip across all channels."""
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id, reminder_text, scheduled_time, created_at, recurrence
            FROM reminders
            WHERE status = 'pending'
            ORDER BY scheduled_time ASC
            """,
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def cancel_reminder(reminder_id: int, user_phone: Optional[str] = None, db_path: str = DB_FILE) -> bool:
    """Cancel a pending reminder."""
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            UPDATE reminders
            SET status = 'cancelled'
            WHERE id = ? AND status = 'pending'
            """,
            (reminder_id,),
        )
        return cursor.rowcount > 0


def save_message(user_phone: str, role: str, content: str, db_path: str = DB_FILE) -> None:
    """Save a user or assistant message to history."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        execute_query(
            conn,
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
        cursor = execute_query(
            conn,
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
