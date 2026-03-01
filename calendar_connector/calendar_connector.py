import datetime
import os

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
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


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


def create_calendar_event(
    project_logger,
    summary,
    start_datetime,
    end_datetime,
    description=None,
    timezone="UTC",
):
    service = calendar_connect(project_logger=project_logger)
    event_body = {
        "summary": summary,
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
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
