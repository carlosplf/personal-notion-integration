from openai_connector import openai_connector
from dotenv import load_dotenv
from utils import create_logger
from gmail_connector import gmail_connector
from notion_connector import notion_connector

# from tests import mock_gpt_data

# Day offset for Notion task filtering (0 = today).
DAYS_TO_CONSIDER = 0


if __name__ == "__main__":
    project_logger = create_logger.create_logger()
    load_dotenv()
    all_tasks = notion_connector.collect_tasks_from_control_panel(
        n_days=DAYS_TO_CONSIDER, project_logger=project_logger
    )
    
    chatgpt_answer = openai_connector.call_openai_assistant(
        all_tasks, project_logger
    )
    gmail_connector.gmail_connect(project_logger=project_logger)
    gmail_connector.send_email_with_tasks(
        all_tasks, chatgpt_answer,
        project_logger=project_logger,
        fake_send=False
    )
