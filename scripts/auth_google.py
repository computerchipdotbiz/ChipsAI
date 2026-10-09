"""
scripts/auth_google.py
One-time Google OAuth authorization for Sarahzine 800.
Authorizes Drive, Gmail, Calendar, and Photos, and saves token.json.
"""
import sys
import os
import traceback
from pathlib import Path

# Ensure console handles UTF-8 on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import google_service

print("=" * 65)
print("[*] SARAHZINE 800 - GOOGLE ACCOUNT AUTHORIZATION")
print("=" * 65)
print("This will connect Sarah to your personal Google account:")
print("  - Google Drive (search documents & files)")
print("  - Gmail (search inbox, trackings & receipts)")
print("  - Google Calendar (view & create calendar events)")
print("  - Google Photos (search photos & media)")
print("=" * 65 + "\n")

try:
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials_file = BASE_DIR / "credentials.json"
    if not credentials_file.exists():
        print(f"[!] Error: credentials.json not found at {credentials_file}")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_file),
        google_service.SCOPES
    )

    print("Launching browser for Google Sign-in...")
    print("Waiting for you to sign in and click 'Allow' in your browser...")
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        success_message="Authentication successful! You may close this tab and return to the terminal."
    )

    if creds and creds.valid:
        token_path = BASE_DIR / "data" / "google_token.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print("\n" + "=" * 65)
        print("[+] SUCCESS! Google account authorized successfully.")
        print(f"[+] Token saved to: {token_path}")
        print("=" * 65 + "\n")
    else:
        print("\n[!] Error: Credentials were not returned or are invalid.")

except Exception as e:
    print(f"\n[!] Error during authorization: {e}")
    traceback.print_exc()

finally:
    try:
        input("Press ENTER to exit this window... ")
    except Exception:
        pass
