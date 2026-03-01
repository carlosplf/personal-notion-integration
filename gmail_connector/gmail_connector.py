import os
import base64

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
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

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
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
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
