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
    today = datetime.datetime.now().date()
    cutoff_day = today + datetime.timedelta(days=max(n_days, 0) + 1)
    cutoff_datetime = datetime.datetime.combine(
        cutoff_day,
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
                    "date": {"before": cutoff_datetime},
                },
            ],
        },
        "sorts": [{"property": "When", "direction": "ascending"}],
        "page_size": 100,
    }

    project_logger.info("Collecting pending tasks from Notion (including overdue tasks)...")

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
            properties = task.get("properties", {})
            task_title = (
                properties.get("Task", {}).get("title", [])
                or properties.get("Name", {}).get("title", [])
            )
            deadline = (
                properties.get("Deadline", {}).get("date")
                or properties.get("When", {}).get("date")
            )
            project = properties.get("Project", {}).get("select")
            tags_property = properties.get("Tags", {})
            tags = []
            if tags_property.get("type") == "multi_select":
                tags = [tag.get("name") for tag in tags_property.get("multi_select", []) if tag.get("name")]
            elif tags_property.get("type") == "select":
                tag_name = tags_property.get("select", {}).get("name")
                tags = [tag_name] if tag_name else []

            if not task_title or not deadline or not deadline.get("start"):
                project_logger.warning("Skipping malformed Notion task payload: %s", task.get("id"))
                continue

            all_task_data.append(
                {
                    "name": task_title[0].get("plain_text") or task_title[0]["text"]["content"],
                    "deadline": deadline["start"],
                    "project": project["name"] if project else "No project",
                    "tags": tags,
                }
            )

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    sorted_tasks = sorted(all_task_data, key=lambda d: d['deadline'])

    return sorted_tasks


def _build_create_task_payload(task_data, title_property, date_property):
    return {
        "parent": {"database_id": task_data["database_id"]},
        "properties": {
            title_property: {
                "title": [{"text": {"content": task_data["task_name"]}}]
            },
            date_property: {
                "date": {"start": task_data["due_date"]}
            },
            "Project": {
                "select": {"name": task_data["project"]}
            },
            "Tags": {
                "multi_select": [{"name": tag} for tag in task_data["tags"]]
            },
            "DONE": {
                "checkbox": False
            },
        },
    }


def create_task_in_control_panel(task_data, project_logger=None):
    project_logger = project_logger or logging.getLogger(__name__)
    notion_credentials = load_credentials.load_notion_credentials(project_logger=project_logger)

    create_data = {
        "database_id": notion_credentials["database_id"],
        "task_name": task_data["task_name"],
        "project": task_data["project"],
        "due_date": task_data["due_date"],
        "tags": task_data.get("tags", []),
    }
    headers = {
        "accept": "application/json",
        "Authorization": "Bearer " + notion_credentials["api_key"] + "",
        "Notion-Version": "2022-06-28",
        "content-type": "application/json",
    }
    payload_candidates = [
        _build_create_task_payload(create_data, "Task", "When"),
        _build_create_task_payload(create_data, "Name", "When"),
        _build_create_task_payload(create_data, "Task", "Deadline"),
        _build_create_task_payload(create_data, "Name", "Deadline"),
    ]

    last_error = None
    for payload in payload_candidates:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if response.status_code == 400 and response.json().get("code") == "validation_error":
            last_error = response
            continue
        response.raise_for_status()
        result = response.json()
        return {
            "id": result.get("id"),
            "url": result.get("url"),
            "task_name": create_data["task_name"],
            "project": create_data["project"],
            "due_date": create_data["due_date"],
            "tags": create_data["tags"],
        }

    if last_error is not None:
        last_error.raise_for_status()
    raise RuntimeError("Failed to create task in Notion")
