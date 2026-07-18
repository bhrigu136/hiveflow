"""Thin helper around the Google Calendar API for meeting sync.

Mirrors the credential/token pattern already used in app/routes/tasks.py, but
factored out so the calendar (meeting) feature can create and remove per-attendee
events without duplicating OAuth plumbing. All functions fail soft — a Google
outage or a revoked token must never break booking a meeting in HiveFlow.
"""
import os
from datetime import timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

# Matches the timezone used for task sync elsewhere in the app.
TIME_ZONE = "Asia/Kolkata"


def _service_for(user):
    """Build a Calendar service for a user, or None if they aren't connected."""
    if not (getattr(user, "google_access_token", None) and getattr(user, "google_refresh_token", None)):
        return None
    creds = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_meeting_event(user, meeting, join_url=None):
    """Create a calendar event on the user's primary calendar for a meeting.

    Returns the created event id, or None if the user isn't connected / it failed.
    """
    try:
        service = _service_for(user)
        if service is None:
            return None

        start = meeting.scheduled_for
        end = start + timedelta(minutes=meeting.duration_minutes or 30)

        description = meeting.description or ""
        if join_url:
            description = (description + f"\n\nJoin the meeting room: {join_url}").strip()

        event = {
            "summary": f"Meeting: {meeting.title}",
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": TIME_ZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": TIME_ZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        created = service.events().insert(calendarId="primary", body=event).execute()
        return created.get("id")
    except Exception as e:  # pragma: no cover - never crash booking
        print("Google Calendar meeting create error:", e)
        return None


def delete_meeting_event(user, event_id):
    """Remove a previously-created meeting event from the user's calendar."""
    if not event_id:
        return
    try:
        service = _service_for(user)
        if service is None:
            return
        service.events().delete(calendarId="primary", eventId=event_id).execute()
    except Exception as e:  # pragma: no cover
        print("Google Calendar meeting delete error:", e)
