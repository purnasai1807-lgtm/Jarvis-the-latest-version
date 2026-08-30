"""
Phase 6 — Google Calendar integration.

Shares OAuth token with Gmail (same credentials file).

Tools: get_schedule, create_event
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
_CREDS_FILE = Path("data/google_credentials.json")
_TOKEN_FILE = Path("data/google_calendar_token.json")


def _get_calendar_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {_CREDS_FILE}."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), _SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _fmt_event(event: dict) -> str:
    start = event.get("start", {})
    end = event.get("end", {})
    title = event.get("summary", "(untitled)")
    location = event.get("location", "")

    # All-day event
    if "date" in start:
        time_str = f"All day ({start['date']})"
    else:
        dt_start = datetime.fromisoformat(start["dateTime"])
        dt_end = datetime.fromisoformat(end["dateTime"])
        time_str = f"{dt_start.strftime('%H:%M')} – {dt_end.strftime('%H:%M')}"

    result = f"{time_str}: {title}"
    if location:
        result += f" @ {location}"
    return result


# ── Handlers ─────────────────────────────────────────────────────

def get_schedule(date: str = "today", days: int = 1) -> str:
    """Fetch calendar events for a given date range."""
    try:
        service = _get_calendar_service()
        now = datetime.now(timezone.utc)

        if date.lower() in ("today", "azi"):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date.lower() in ("tomorrow", "maine"):
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif date.lower() in ("this week", "saptamana"):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            days = 7
        else:
            try:
                start = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
            except ValueError:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        end = start + timedelta(days=days)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        if not events:
            label = "today" if date.lower() in ("today", "azi") else date
            return f"No events scheduled for {label}."

        label = "today" if date.lower() in ("today", "azi") else date
        lines = [f"Schedule for {label} ({len(events)} event(s)):\n"]
        for e in events:
            lines.append(f"  • {_fmt_event(e)}")

        logger.info(f"get_schedule: {len(events)} events for {date}")
        return "\n".join(lines)

    except Exception as exc:
        logger.error(f"get_schedule failed: {exc}")
        return f"Could not fetch calendar: {exc}"


def create_event(title: str, date: str, time: str = "09:00",
                 duration_minutes: int = 60, description: str = "") -> str:
    """Create a new calendar event."""
    try:
        service = _get_calendar_service()

        # Parse date
        if date.lower() in ("today", "azi"):
            date_str = datetime.now().strftime("%Y-%m-%d")
        elif date.lower() in ("tomorrow", "maine"):
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            date_str = date

        start_dt = datetime.fromisoformat(f"{date_str}T{time}:00")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        tz = "Europe/Bucharest"
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        }

        created = service.events().insert(calendarId="primary", body=event).execute()
        logger.info(f"create_event: '{title}' on {date_str} at {time}")
        return f"Event '{title}' created for {date_str} at {time}."

    except Exception as exc:
        logger.error(f"create_event failed: {exc}")
        return f"Could not create event: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_schedule",
        "description": (
            "Get calendar events from Google Calendar. "
            "Use for: 'what's my schedule today?', 'any meetings tomorrow?', "
            "'what do I have this week?', 'morning briefing' (include schedule). "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "'today', 'tomorrow', 'this week', or ISO date like '2026-04-10'",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to fetch (default 1)",
                },
            },
        },
    },
    {
        "name": "create_event",
        "description": (
            "Create a new event in Google Calendar. "
            "Use when the user says 'add X to my calendar', 'schedule a meeting', "
            "'remind me about X on Y at Z', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "date": {"type": "string", "description": "'today', 'tomorrow', or ISO date like '2026-04-10'"},
                "time": {"type": "string", "description": "Start time in HH:MM format (24h), default '09:00'"},
                "duration_minutes": {"type": "integer", "description": "Duration in minutes, default 60"},
                "description": {"type": "string", "description": "Optional event description or notes"},
            },
            "required": ["title", "date"],
        },
    },
]

HANDLERS = {
    "get_schedule": get_schedule,
    "create_event": create_event,
}
