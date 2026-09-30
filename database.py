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
        """
        CREATE TABLE IF NOT EXISTS proactive_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_phone TEXT NOT NULL,
            checkin_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            context_text TEXT NOT NULL,
            message_sent TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(user_phone, subject_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_phone TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            subject TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, scheduled_time)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_proactive_user_subject ON proactive_checkins(user_phone, subject_key)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user_subject ON user_memories(user_phone, subject)"
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
        """
        CREATE TABLE IF NOT EXISTS proactive_checkins (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            checkin_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            context_text TEXT NOT NULL,
            message_sent TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(user_phone, subject_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memories (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            subject TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, scheduled_time)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_proactive_user_subject ON proactive_checkins(user_phone, subject_key)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user_subject ON user_memories(user_phone, subject)"
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


def record_proactive_checkin(
    user_phone: str,
    checkin_type: str,
    subject_key: str,
    context_text: str,
    message_sent: str,
    db_path: str = DB_FILE,
) -> bool:
    """Record a proactive check-in in the database. Returns True if saved, False if already sent (deduped)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with get_db(db_path) as conn:
            execute_query(
                conn,
                """
                INSERT INTO proactive_checkins (user_phone, checkin_type, subject_key, context_text, message_sent, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_phone, checkin_type, subject_key, context_text, message_sent, now_iso),
            )
            return True
    except Exception as e:
        logger.info(f"Proactive check-in for subject '{subject_key}' already recorded or ignored: {e}")
        return False


def has_proactive_checkin_been_sent(
    user_phone: str, subject_key: str, db_path: str = DB_FILE
) -> bool:
    """Check if a proactive check-in for this specific subject has already been sent to the user."""
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id FROM proactive_checkins
            WHERE user_phone = ? AND subject_key = ?
            LIMIT 1
            """,
            (user_phone, subject_key),
        )
        return cursor.fetchone() is not None


def get_last_proactive_checkin(
    user_phone: Optional[str] = None,
    checkin_type: Optional[str] = None,
    db_path: str = DB_FILE,
) -> Optional[Dict[str, Any]]:
    """Return the most recent proactive check-in record for pacing."""
    query = "SELECT * FROM proactive_checkins WHERE 1=1"
    params: List[Any] = []
    if user_phone:
        query += " AND user_phone = ?"
        params.append(user_phone)
    if checkin_type:
        query += " AND checkin_type = ?"
        params.append(checkin_type)
    query += " ORDER BY id DESC LIMIT 1"

    with get_db(db_path) as conn:
        cursor = execute_query(conn, query, tuple(params))
        row = cursor.fetchone()
        return dict(row) if row else None


def count_recent_proactive_checkins(
    user_phone: str,
    checkin_type: str = "random_friend",
    hours: float = 24.0,
    db_path: str = DB_FILE,
) -> int:
    """Count how many proactive check-ins of a given type were sent to this user in the last `hours` hours."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT COUNT(*) FROM proactive_checkins
            WHERE user_phone = ? AND checkin_type = ? AND sent_at >= ?
            """,
            (user_phone, checkin_type, cutoff),
        )
        row = cursor.fetchone()
        return row[0] if isinstance(row, (tuple, list)) else row["COUNT(*)"]


def get_upcoming_reminders_window(
    hours_ahead: float = 48.0,
    db_path: str = DB_FILE,
) -> List[Dict[str, Any]]:
    """Return pending reminders that are scheduled within the next `hours_ahead` hours from now (e.g. 24-48 hours)."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=hours_ahead)
    now_iso = now.isoformat()
    future_iso = future.isoformat()

    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id, user_phone, reminder_text, scheduled_time, created_at, recurrence
            FROM reminders
            WHERE status = 'pending'
              AND (recurrence = 'none' OR recurrence = '' OR recurrence IS NULL)
              AND scheduled_time > ? AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
            """,
            (now_iso, future_iso),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_last_message_time(
    user_phone: str,
    db_path: str = DB_FILE,
) -> Optional[datetime]:
    """Get the UTC datetime of the last message in conversation history for this user."""
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT created_at FROM conversation_history
            WHERE user_phone = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_phone,),
        )
        row = cursor.fetchone()
        if row:
            try:
                from dateutil import parser
                return parser.parse(row["created_at"])
            except Exception:
                try:
                    return datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                except Exception:
                    pass
    return None


def get_outlier_tasks_for_today(
    user_timezone: str = "America/Chicago",
    db_path: str = DB_FILE,
) -> List[Dict[str, Any]]:
    """Return pending one-shot/non-recurring tasks scheduled for today in the user's local timezone."""
    import pytz
    try:
        tz = pytz.timezone(user_timezone)
    except Exception:
        tz = pytz.timezone("America/Chicago")

    now_local = datetime.now(tz)
    start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    start_utc = start_of_day.astimezone(timezone.utc).isoformat()
    end_utc = end_of_day.astimezone(timezone.utc).isoformat()

    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id, reminder_text, scheduled_time, recurrence
            FROM reminders
            WHERE status = 'pending'
              AND (recurrence = 'none' OR recurrence = '' OR recurrence IS NULL)
              AND scheduled_time >= ? AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
            """,
            (start_utc, end_utc),
        )
        rows = cursor.fetchall()
        tasks = []
        for r in rows:
            dt_utc = datetime.fromisoformat(r["scheduled_time"].replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(tz)
            time_str = dt_local.strftime("%I:%M %p").lstrip("0")
            tasks.append({
                "id": r["id"],
                "text": r["reminder_text"],
                "time_str": time_str,
            })
        return tasks


def snooze_reminder(reminder_id: int, minutes: int = 30, db_path: str = DB_FILE) -> bool:
    """Snooze a reminder by setting its scheduled_time into the future and status back to pending."""
    from datetime import timedelta
    new_time_iso = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            "UPDATE reminders SET scheduled_time = ?, status = 'pending', sent_at = NULL WHERE id = ?",
            (new_time_iso, reminder_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def complete_reminder(reminder_id: int, db_path: str = DB_FILE) -> bool:
    """Mark a reminder as completed."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            "UPDATE reminders SET status = 'completed', sent_at = ? WHERE id = ?",
            (now_iso, reminder_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def save_or_update_memory(
    user_phone: str,
    category: str,
    subject: str,
    detail: str,
    db_path: str = DB_FILE,
) -> int:
    """Save a new memory or update an existing memory if the subject already exists."""
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_cat = (category or "general").strip().lower()
    clean_sub = subject.strip()
    clean_detail = detail.strip()

    with get_db(db_path) as conn:
        # Check if subject already exists for this user
        cursor = execute_query(
            conn,
            "SELECT id FROM user_memories WHERE user_phone = ? AND LOWER(subject) = LOWER(?)",
            (user_phone, clean_sub),
        )
        existing = cursor.fetchone()
        if existing:
            mem_id = existing["id"]
            execute_query(
                conn,
                "UPDATE user_memories SET category = ?, detail = ?, updated_at = ? WHERE id = ?",
                (clean_cat, clean_detail, now_iso, mem_id),
            )
            conn.commit()
            return mem_id
        else:
            if is_postgres():
                cursor = execute_query(
                    conn,
                    """
                    INSERT INTO user_memories (user_phone, category, subject, detail, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (user_phone, clean_cat, clean_sub, clean_detail, now_iso, now_iso),
                )
                mem_id = cursor.fetchone()["id"]
            else:
                cursor = execute_query(
                    conn,
                    """
                    INSERT INTO user_memories (user_phone, category, subject, detail, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_phone, clean_cat, clean_sub, clean_detail, now_iso, now_iso),
                )
                mem_id = cursor.lastrowid
            conn.commit()
            return mem_id


def get_user_memories(
    user_phone: str,
    category: Optional[str] = None,
    limit: int = 50,
    db_path: str = DB_FILE,
) -> List[Dict[str, Any]]:
    """Retrieve memories for a user, optionally filtered by category."""
    with get_db(db_path) as conn:
        if category:
            cursor = execute_query(
                conn,
                "SELECT id, category, subject, detail, created_at, updated_at FROM user_memories WHERE user_phone = ? AND LOWER(category) = LOWER(?) ORDER BY updated_at DESC LIMIT ?",
                (user_phone, category.strip(), limit),
            )
        else:
            cursor = execute_query(
                conn,
                "SELECT id, category, subject, detail, created_at, updated_at FROM user_memories WHERE user_phone = ? ORDER BY updated_at DESC LIMIT ?",
                (user_phone, limit),
            )
        return [dict(r) for r in cursor.fetchall()]


def search_user_memories(
    user_phone: str,
    query_text: str,
    limit: int = 10,
    db_path: str = DB_FILE,
) -> List[Dict[str, Any]]:
    """Search memories by subject or detail."""
    pattern = f"%{query_text.strip().lower()}%"
    with get_db(db_path) as conn:
        cursor = execute_query(
            conn,
            """
            SELECT id, category, subject, detail, created_at, updated_at
            FROM user_memories
            WHERE user_phone = ?
              AND (LOWER(subject) LIKE ? OR LOWER(detail) LIKE ? OR LOWER(category) LIKE ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_phone, pattern, pattern, pattern, limit),
        )
        return [dict(r) for r in cursor.fetchall()]


def delete_user_memory(
    memory_id: int,
    user_phone: Optional[str] = None,
    db_path: str = DB_FILE,
) -> bool:
    """Delete a memory by its ID."""
    with get_db(db_path) as conn:
        if user_phone:
            cursor = execute_query(
                conn,
                "DELETE FROM user_memories WHERE id = ? AND user_phone = ?",
                (memory_id, user_phone),
            )
        else:
            cursor = execute_query(
                conn,
                "DELETE FROM user_memories WHERE id = ?",
                (memory_id,),
            )
        conn.commit()
        return cursor.rowcount > 0


def format_user_memories_summary(user_phone: str, limit: int = 20, db_path: str = DB_FILE) -> str:
    """Format key user memories into a compact bullet list for system prompt context."""
    memories = get_user_memories(user_phone, limit=limit, db_path=db_path)
    if not memories:
        return ""
    lines = []
    for m in memories:
        cat = m.get("category", "general")
        sub = m.get("subject", "")
        det = m.get("detail", "")
        lines.append(f"- [{cat}/{sub}]: {det}")
    return "\n".join(lines)


