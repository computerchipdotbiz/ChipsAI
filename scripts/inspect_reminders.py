import sqlite3

conn = sqlite3.connect("/opt/chipai/reminders.db")
c = conn.cursor()
c.execute("DELETE FROM reminders WHERE id = 3")
conn.commit()

c.execute("SELECT id, user_phone, reminder_text, scheduled_time, recurrence, status, sent_at FROM reminders")
print("=== Active Reminders in VM Database ===")
for row in c.fetchall():
    print(f"ID: {row[0]} | User: {row[1]} | Text: {row[2]}")
    print(f"  Scheduled UTC: {row[3]}")
    print(f"  Recurrence: {row[4]} | Status: {row[5]} | Sent At: {row[6]}\n")
