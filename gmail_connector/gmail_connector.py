import os
import base64
import json

from jinja2 import Environment, FileSystemLoader

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from email.mime.text import MIMEText

from utils import message_parser
from utils import nice_message_collector
from utils import load_credentials


SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/calendar.readonly',
        'https://www.googleapis.com/auth/calendar.events',
    ]


def gmail_connect(project_logger):
    """
    Create a Google GMail connection using GCloud credentials.
    This method expects a 'credentials.json' local file and
    a token.json file is created after validating credentials.
    """
    creds = None

    project_logger.debug("Connecting GMAIL Oauth2...")

    if os.path.exists('token.json'):
        creds = _load_credentials_from_token('token.json', SCOPES, project_logger)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())


def build_email_body(all_tasks, display_name, chatgpt_answer,
                     project_logger, to_file=False):
    """
    Build the email HTML using Jinja2. Template is in template/ folder.
    """
    project_logger.info("Building email body...")

    message_json, general_message = message_parser.\
        parse_chatgpt_message(chatgpt_answer, project_logger)
    if message_json is None:
        return False

    nice_message = nice_message_collector.get_motivational_message(
        project_logger=project_logger
    )["text"]

    environment = Environment(loader=FileSystemLoader("templates/"))
    template = environment.get_template("email_template.html")
    context = {
        "username": display_name,
        "all_tasks": all_tasks,
        "nice_message": nice_message,
        "json_gpt_tasks": message_json,
        "gpt_general_comment": general_message
    }

    html_output = template.render(context)

    if to_file:
        with open("some_new_file.html", "w") as f:
            f.write(html_output)

    return html_output


def send_email_with_tasks(all_tasks, chatgpt_answer, project_logger,
                          fake_send=False):
    """
    Considering a already created token.json file based on GCloud credentials,
    send an email using GMail API.
    """
    project_logger.info("Sending email...")
    creds = _load_credentials_from_token('token.json', SCOPES, project_logger)
    email_config = load_credentials.load_email_config(
        project_logger=project_logger
    )
    email_message = build_email_body(
        all_tasks,
        email_config["display_name"],
        chatgpt_answer,
        project_logger,
        to_file=fake_send
    )
    if not email_message:
        project_logger.error("Email body generation failed.")
        return None

    if fake_send:
        return True

    try:
        service = build('gmail', 'v1', credentials=creds)
        message = MIMEText(email_message, 'html')

        message['To'] = email_config["email_to"]
        message['From'] = email_config["email_from"]
        message['Subject'] = 'My Notion Bot - Tasks'

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()) \
            .decode()

        create_message = {
            'raw': encoded_message
        }

        send_message = (service.users().messages().send
                        (userId="me", body=create_message).execute())

    except HttpError as error:
        project_logger.error(F'An error occurred: {error}')
        send_message = None

    return send_message


def send_custom_email(
    project_logger,
    subject,
    body_text,
    email_to=None,
    email_from=None,
    body_subtype="plain",
    fake_send=False,
):
    """
    Send a custom email through Gmail API.
    """
    clean_subject = str(subject or "").strip()
    clean_body = str(body_text or "").strip()
    if not clean_subject:
        raise ValueError("Email subject is required")
    if not clean_body:
        raise ValueError("Email body is required")

    resolved_to = str(email_to or os.getenv("EMAIL_TO", "")).strip()
    resolved_from = str(email_from or os.getenv("EMAIL_FROM", "")).strip()
    if not resolved_to:
        raise ValueError("Destination email is required")
    if not resolved_from:
        raise ValueError("Source email is required")

    message = MIMEText(clean_body, body_subtype, "utf-8")
    message["To"] = resolved_to
    message["From"] = resolved_from
    message["Subject"] = clean_subject
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    if fake_send:
        return {
            "to": resolved_to,
            "from": resolved_from,
            "subject": clean_subject,
            "raw": encoded_message,
        }

    creds = _load_credentials_from_token("token.json", SCOPES, project_logger)
    service = build("gmail", "v1", credentials=creds)
    sent = service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
    return {
        "id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "to": resolved_to,
        "from": resolved_from,
        "subject": clean_subject,
    }


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
