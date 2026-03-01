import datetime
import logging
import os
import requests

from utils import load_credentials


def collect_tasks_from_control_panel(n_days=0, project_logger=None):
    """
    Connect to Notion API and collect Tasks from 'Control Panel' database.
    TODO: Fix project_logger argument. Can't be None.
    """
    project_logger = project_logger or logging.getLogger(__name__)
    notion_credentials = load_credentials.load_notion_credentials(project_logger=project_logger)
    today = datetime.datetime.now().date() + datetime.timedelta(days=n_days)
    start_of_day = datetime.datetime.combine(today, datetime.time.min).isoformat()
    next_day = datetime.datetime.combine(
        today + datetime.timedelta(days=1),
        datetime.time.min,
    ).isoformat()

    query_candidates = [
        {
            "url": f"https://api.notion.com/v1/data_sources/{notion_credentials['database_id']}/query",
            "notion_version": os.getenv("NOTION_VERSION", "2025-09-03"),
        },
        {
            "url": f"https://api.notion.com/v1/databases/{notion_credentials['database_id']}/query",
            "notion_version": "2022-06-28",
        },
    ]

    payload = {
        "filter": {
            "and": [
                {
                    "property": "DONE",
                    "checkbox": {"equals": False},
                },
                {
                    "property": "When",
                    "date": {"on_or_after": start_of_day},
                },
                {
                    "property": "When",
                    "date": {"before": next_day},
                },
            ],
        },
        "sorts": [{"property": "When", "direction": "ascending"}],
        "page_size": 100,
    }

    project_logger.info("Collecting tasks due today from Notion...")

    all_task_data = []
    next_cursor = None
    has_more = True
    selected_candidate = None
    while has_more:
        request_payload = payload.copy()
        if next_cursor:
            request_payload["start_cursor"] = next_cursor

        if selected_candidate is None:
            last_error = None
            for candidate in query_candidates:
                headers = {
                    "accept": "application/json",
                    "Authorization": "Bearer " + notion_credentials["api_key"] + "",
                    "Notion-Version": candidate["notion_version"],
                    "content-type": "application/json",
                }
                response = requests.post(candidate["url"], json=request_payload, headers=headers, timeout=30)
                if response.status_code in (400, 404):
                    response_code = response.json().get("code", "")
                    if response_code in ("invalid_request_url", "object_not_found"):
                        last_error = response
                        continue
                    last_error = response
                response.raise_for_status()
                selected_candidate = candidate
                break
            if selected_candidate is None:
                last_error.raise_for_status()
        else:
            headers = {
                "accept": "application/json",
                "Authorization": "Bearer " + notion_credentials["api_key"] + "",
                "Notion-Version": selected_candidate["notion_version"],
                "content-type": "application/json",
            }
            response = requests.post(selected_candidate["url"], json=request_payload, headers=headers, timeout=30)
            response.raise_for_status()

        data = response.json()

        for task in data.get("results", []):
            task_title = task["properties"].get("Task", {}).get("title", [])
            deadline = task["properties"].get("Deadline", {}).get("date")
            project = task["properties"].get("Project", {}).get("select")

            if not task_title or not deadline or not deadline.get("start"):
                project_logger.warning("Skipping malformed Notion task payload: %s", task.get("id"))
                continue

            all_task_data.append(
                {
                    "name": task_title[0]["text"]["content"],
                    "deadline": deadline["start"],
                    "project": project["name"] if project else "No project",
                }
            )

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    sorted_tasks = sorted(all_task_data, key=lambda d: d['deadline'])

    return sorted_tasks
