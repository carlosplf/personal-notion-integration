from __future__ import annotations

import datetime

from notion_connector import notion_connector


def list_notion_tasks(arguments, context):
    n_days = max(int(arguments.get("n_days", 0)), 0)
    limit = int(arguments.get("limit", 10))
    limit = min(max(limit, 1), 50)

    tasks = notion_connector.collect_tasks_from_control_panel(
        n_days=n_days,
        project_logger=context.project_logger,
    )
    return {
        "total": len(tasks),
        "returned": min(limit, len(tasks)),
        "tasks": tasks[:limit],
    }


def list_notion_notes(arguments, context):
    days_back = max(int(arguments.get("days_back", 5)), 0)
    days_forward = max(int(arguments.get("days_forward", 5)), 0)
    limit = int(arguments.get("limit", 20))
    limit = min(max(limit, 1), 100)

    notes = notion_connector.collect_notes_around_today(
        days_back=days_back,
        days_forward=days_forward,
        project_logger=context.project_logger,
    )
    return {
        "total": len(notes),
        "returned": min(limit, len(notes)),
        "notes": notes[:limit],
    }


def create_notion_task(arguments, context):
    task_name = str(arguments.get("task_name", "")).strip()
    if not task_name:
        raise ValueError("task_name is required")

    project = str(arguments.get("project", "Pessoal")).strip() or "Pessoal"
    due_date = str(arguments.get("due_date", datetime.date.today().isoformat())).strip()
    datetime.date.fromisoformat(due_date)

    tags = arguments.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")

    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]

    return notion_connector.create_task_in_control_panel(
        {
            "task_name": task_name,
            "project": project,
            "due_date": due_date,
            "tags": clean_tags,
        },
        project_logger=context.project_logger,
    )


def create_notion_note(arguments, context):
    note_name = str(arguments.get("note_name", "")).strip()
    if not note_name:
        raise ValueError("note_name is required")

    tag = str(arguments.get("tag", "GENERAL")).strip() or "GENERAL"
    observations = str(arguments.get("observations", ""))
    url = str(arguments.get("url", "")).strip()

    return notion_connector.create_note_in_notes_db(
        {
            "note_name": note_name,
            "tag": tag,
            "observations": observations,
            "url": url,
        },
        project_logger=context.project_logger,
    )


def edit_notion_item(arguments, context):
    item_type = str(arguments.get("item_type", "")).strip().lower()
    if item_type not in {"task", "card"}:
        raise ValueError("item_type must be 'task' or 'card'")

    page_id = str(arguments.get("page_id", "")).strip()
    if not page_id:
        raise ValueError("page_id is required")

    payload = {
        "item_type": item_type,
        "page_id": page_id,
    }
    content = None
    if "content" in arguments:
        raw_content = str(arguments.get("content", ""))
        if raw_content.strip():
            content = raw_content
            payload["content"] = raw_content
    if "content_mode" in arguments and content is not None:
        content_mode = str(arguments.get("content_mode", "")).strip().lower()
        if content_mode and content_mode not in {"append", "replace"}:
            raise ValueError("content_mode must be 'append' or 'replace'")
        if content_mode:
            payload["content_mode"] = content_mode

    if item_type == "task":
        if "task_name" in arguments:
            task_name = str(arguments.get("task_name", "")).strip()
            if task_name:
                payload["task_name"] = task_name
        if "due_date" in arguments:
            due_date = str(arguments.get("due_date", "")).strip()
            if due_date:
                datetime.date.fromisoformat(due_date)
                payload["due_date"] = due_date
        if "project" in arguments:
            project = str(arguments.get("project", "")).strip()
            if project:
                payload["project"] = project
        if "tags" in arguments:
            tags = arguments.get("tags", [])
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
            if clean_tags:
                payload["tags"] = clean_tags
        if "done" in arguments:
            payload["done"] = bool(arguments.get("done"))
        if set(payload.keys()) == {"item_type", "page_id"}:
            raise ValueError("At least one task field is required")
    else:
        if "note_name" in arguments:
            note_name = str(arguments.get("note_name", "")).strip()
            if note_name:
                payload["note_name"] = note_name
        if "tag" in arguments:
            tag = str(arguments.get("tag", "")).strip()
            if tag:
                payload["tag"] = tag
        if "observations" in arguments:
            observations = str(arguments.get("observations", ""))
            if observations.strip():
                payload["observations"] = observations
        if "url" in arguments:
            url = str(arguments.get("url", "")).strip()
            if url:
                payload["url"] = url
        if "date" in arguments:
            date_value = str(arguments.get("date", "")).strip()
            if date_value:
                datetime.date.fromisoformat(date_value)
                payload["date"] = date_value
        if set(payload.keys()) == {"item_type", "page_id"}:
            raise ValueError("At least one card field is required")

    return notion_connector.update_notion_page(payload, project_logger=context.project_logger)
