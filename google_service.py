"""
google_service.py
Unified Google Workspace & Personal Cloud Integration for Sarahzine 800.
Provides authenticated access to:
- Google Drive (search files, read docs, find sheets/PDFs)
- Gmail (search emails, extract order confirmations, trackings, summaries)
- Google Calendar (list upcoming schedule, create events, resolve conflicts)
- Google Photos (search media, browse albums)
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import pytz

logger = logging.getLogger("chipai.google_service")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = DATA_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
]


def get_credentials():
    """Retrieve or refresh authenticated Google OAuth 2.0 credentials."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            logger.warning(f"Error loading saved google token: {e}")

    # If no valid credentials, refresh or prompt
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired Google OAuth access token...")
                creds.refresh(Request())
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception as ex:
                logger.error(f"Failed to refresh Google token: {ex}")
                creds = None

        if not creds:
            if not CREDENTIALS_FILE.exists():
                logger.warning(f"Google credentials.json not found at {CREDENTIALS_FILE}")
                return None
            try:
                logger.info("Starting OAuth local authentication flow...")
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception as e:
                logger.error(f"Failed to complete OAuth flow: {e}")
                return None

    return creds


# ==============================================================================
# GOOGLE DRIVE
# ==============================================================================

def search_drive(query: str, max_results: int = 10) -> Dict[str, Any]:
    """Search Google Drive files and documents by keyword or file name."""
    creds = get_credentials()
    if not creds:
        return {"status": "error", "message": "Google Drive not authenticated. Please add credentials.json"}

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds)

        # Build resilient query: search both title and full-text
        clean_q = query.replace("'", "\\'")
        q_filter = f"name contains '{clean_q}' or fullText contains '{clean_q}' and trashed = false"

        results = service.files().list(
            q=q_filter,
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink, modifiedTime, size)",
        ).execute()

        files = results.get("files", [])
        return {
            "status": "success",
            "count": len(files),
            "files": [
                {
                    "name": f.get("name"),
                    "id": f.get("id"),
                    "link": f.get("webViewLink"),
                    "type": f.get("mimeType"),
                    "modified": f.get("modifiedTime"),
                }
                for f in files
            ],
        }
    except Exception as e:
        logger.error(f"Error searching Google Drive: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ==============================================================================
# GMAIL
# ==============================================================================

def search_gmail(query: str, max_results: int = 10) -> Dict[str, Any]:
    """Search Gmail inbox by standard query syntax (e.g. 'from:andy', 'tracking', 'receipt')."""
    creds = get_credentials()
    if not creds:
        return {"status": "error", "message": "Gmail not authenticated. Please add credentials.json"}

    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)

        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = results.get("messages", [])
        summaries = []

        for m in messages:
            msg = service.users().messages().get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            summaries.append({
                "id": m["id"],
                "subject": headers.get("Subject", "(No Subject)"),
                "from": headers.get("From", "Unknown"),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })

        return {
            "status": "success",
            "count": len(summaries),
            "emails": summaries,
        }
    except Exception as e:
        logger.error(f"Error searching Gmail: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ==============================================================================
# GOOGLE CALENDAR
# ==============================================================================

def get_calendar_events(days_ahead: int = 7) -> Dict[str, Any]:
    """Fetch upcoming events from Chip's primary Google Calendar."""
    creds = get_credentials()
    if not creds:
        return {"status": "error", "message": "Google Calendar not authenticated. Please add credentials.json"}

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        clean_events = []
        for e in events:
            start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date"))
            end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date"))
            clean_events.append({
                "summary": e.get("summary", "(No Title)"),
                "start": start,
                "end": end,
                "location": e.get("location", ""),
                "description": e.get("description", ""),
                "link": e.get("htmlLink", ""),
            })

        return {
            "status": "success",
            "count": len(clean_events),
            "events": clean_events,
        }
    except Exception as e:
        logger.error(f"Error fetching Google Calendar: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def create_calendar_event(summary: str, start_iso: str, end_iso: str = "", description: str = "") -> Dict[str, Any]:
    """Create a new event in Chip's Google Calendar."""
    creds = get_credentials()
    if not creds:
        return {"status": "error", "message": "Google Calendar not authenticated."}

    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds)

        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso or start_iso},
        }

        created = service.events().insert(calendarId="primary", body=body).execute()
        return {
            "status": "success",
            "event_id": created.get("id"),
            "link": created.get("htmlLink"),
            "summary": summary,
        }
    except Exception as e:
        logger.error(f"Error creating Google Calendar event: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ==============================================================================
# GOOGLE PHOTOS
# ==============================================================================

def search_photos(query: str = "", max_results: int = 10) -> Dict[str, Any]:
    """Search Google Photos media library."""
    creds = get_credentials()
    if not creds:
        return {"status": "error", "message": "Google Photos not authenticated."}

    try:
        from googleapiclient.discovery import build
        service = build("photoslibrary", "v1", credentials=creds, static_discovery=False)

        body = {"pageSize": max_results}
        results = service.mediaItems().search(body=body).execute()
        items = results.get("mediaItems", [])

        clean_items = []
        for it in items:
            clean_items.append({
                "id": it.get("id"),
                "filename": it.get("filename"),
                "description": it.get("description", ""),
                "url": it.get("productUrl"),
                "mimeType": it.get("mimeType"),
            })

        return {
            "status": "success",
            "count": len(clean_items),
            "photos": clean_items,
        }
    except Exception as e:
        logger.warning(f"Photos Library API search encountered an issue: {e}. Falling back to Google Drive photos...")
        try:
            from googleapiclient.discovery import build
            service = build("drive", "v3", credentials=creds)
            clean_q = query.replace("'", "\\'") if query else ""
            if clean_q:
                q_filter = f"mimeType contains 'image/' and (name contains '{clean_q}' or fullText contains '{clean_q}') and trashed = false"
            else:
                q_filter = "mimeType contains 'image/' and trashed = false"

            results = service.files().list(
                q=q_filter,
                pageSize=max_results,
                fields="files(id, name, mimeType, webViewLink, modifiedTime, size)",
            ).execute()
            files = results.get("files", [])
            return {
                "status": "success",
                "count": len(files),
                "source": "Google Drive Images",
                "photos": [
                    {
                        "id": f.get("id"),
                        "filename": f.get("name"),
                        "description": "",
                        "url": f.get("webViewLink"),
                        "mimeType": f.get("mimeType"),
                    }
                    for f in files
                ],
            }
        except Exception as drive_err:
            logger.error(f"Error searching photos via Drive: {drive_err}", exc_info=True)
            return {"status": "error", "error": f"Photos API: {e}; Drive fallback: {drive_err}"}

