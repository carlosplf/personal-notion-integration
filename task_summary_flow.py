from notion_connector import notion_connector
from openai_connector import llm_api


# Day offset for Notion task filtering (0 = today).
DAYS_TO_CONSIDER = 0


def collect_tasks_and_summary(project_logger, n_days=DAYS_TO_CONSIDER):
    all_tasks = notion_connector.collect_tasks_from_control_panel(
        n_days=n_days, project_logger=project_logger
    )
    chatgpt_answer = llm_api.call_openai_assistant(all_tasks, project_logger)
    return all_tasks, chatgpt_answer
