import datetime
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def calendar_connect(project_logger):
    """
    Create a Google Calendar connection using local OAuth credentials.
    This method expects a 'credentials.json' file and stores token in token.json.
    """
    creds = None

    project_logger.debug("Connecting Google Calendar Oauth2...")

    if os.path.exists("token.json"):
        creds = _load_credentials_from_token("token.json", SCOPES, project_logger)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _load_credentials_from_token(token_path, scopes, project_logger):
    try:
        return Credentials.from_authorized_user_file(token_path, scopes)
    except json.JSONDecodeError:
        project_logger.warning("token.json has trailing data; attempting auto-recovery.")
        with open(token_path, "r", encoding="utf-8") as token_file:
            token_payload = _extract_first_json_object(token_file.read())
        with open(token_path, "w", encoding="utf-8") as token_file:
            json.dump(token_payload, token_file)
        return Credentials.from_authorized_user_info(token_payload, scopes)


def _extract_first_json_object(content):
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(content.lstrip())
    if not isinstance(payload, dict):
        raise ValueError("Invalid token payload format")
    return payload


def list_upcoming_events(project_logger, max_results=10):
    service = calendar_connect(project_logger=project_logger)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    response = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for event in response.get("items", []):
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        events.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary", "Sem título"),
                "start": start,
                "html_link": event.get("htmlLink"),
            }
        )
    return events


def list_week_events(project_logger, max_results=100):
    service = calendar_connect(project_logger=project_logger)
    now = datetime.datetime.utcnow()
    week_end = now + datetime.timedelta(days=7)

    response = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat() + "Z",
        timeMax=week_end.isoformat() + "Z",
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for event in response.get("items", []):
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        events.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary", "Sem título"),
                "start": start,
                "end": end,
                "html_link": event.get("htmlLink"),
                "location": event.get("location"),
            }
        )
    return events


def list_current_week_events(project_logger, max_results=100):
    service = calendar_connect(project_logger=project_logger)
    today = datetime.datetime.utcnow().date()
    days_since_sunday = (today.weekday() + 1) % 7
    week_start_date = today - datetime.timedelta(days=days_since_sunday)
    week_start = datetime.datetime.combine(week_start_date, datetime.time.min)
    next_week_start = week_start + datetime.timedelta(days=7)

    response = service.events().list(
        calendarId="primary",
        timeMin=week_start.isoformat() + "Z",
        timeMax=next_week_start.isoformat() + "Z",
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for event in response.get("items", []):
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        events.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary", "Sem título"),
                "start": start,
                "end": end,
                "html_link": event.get("htmlLink"),
                "location": event.get("location"),
            }
        )
    return events


def create_calendar_event(
    project_logger,
    summary,
    start_datetime,
    end_datetime,
    description=None,
    timezone="UTC",
):
    service = calendar_connect(project_logger=project_logger)
    start_rfc3339, start_dt = _normalize_event_datetime(start_datetime, timezone)
    end_rfc3339, end_dt = _normalize_event_datetime(end_datetime, timezone)
    if end_dt <= start_dt:
        raise ValueError("end_datetime must be after start_datetime")

    event_body = {
        "summary": summary,
        "start": {"dateTime": start_rfc3339, "timeZone": timezone},
        "end": {"dateTime": end_rfc3339, "timeZone": timezone},
    }
    if description:
        event_body["description"] = description

    created_event = service.events().insert(calendarId="primary", body=event_body).execute()
    return {
        "id": created_event.get("id"),
        "summary": created_event.get("summary"),
        "start": created_event.get("start", {}).get("dateTime"),
        "end": created_event.get("end", {}).get("dateTime"),
        "html_link": created_event.get("htmlLink"),
    }


def _normalize_event_datetime(value, timezone):
    tz = _get_timezone(timezone)
    text = str(value).strip()
    if not text:
        raise ValueError("Event datetime is required")

    parsed = None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for date_format in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(text, date_format)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("Invalid event datetime format. Use YYYY-MM-DDTHH:MM")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)
    return parsed.isoformat(), parsed


def _get_timezone(timezone):
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Invalid timezone: {timezone}") from error
