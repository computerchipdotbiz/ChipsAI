import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import google_service

print("=== Testing Sarah's Google Integration ===")

# 1. Drive
drive = google_service.search_drive("pdf", max_results=3)
print(f"📁 Google Drive: status={drive.get('status')}, found {drive.get('count', 0)} files")
for f in drive.get("files", [])[:2]:
    print(f"   - {f['name']} ({f['link']})")

# 2. Gmail
mail = google_service.search_gmail("is:unread", max_results=3)
print(f"\n📧 Gmail: status={mail.get('status')}, found {mail.get('count', 0)} unread emails")
for m in mail.get("emails", [])[:2]:
    print(f"   - From: {m['from'][:30]} | Subject: {m['subject'][:40]}")

# 3. Calendar
cal = google_service.get_calendar_events(days_ahead=7)
print(f"\n📅 Calendar: status={cal.get('status')}, found {cal.get('count', 0)} upcoming events")

# 4. Photos
photos = google_service.search_photos(max_results=3)
print(f"\n📸 Photos: status={photos.get('status')}, found {photos.get('count', 0)} items")

print("\n=== Verification Complete! ===")
