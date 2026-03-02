import datetime
import logging
import os
import re
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
                    "id": task.get("id"),
                    "page_url": task.get("url"),
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


def _find_property_name(properties, preferred_names, accepted_types):
    for property_name in preferred_names:
        metadata = properties.get(property_name, {})
        if metadata.get("type") in accepted_types:
            return property_name, metadata.get("type")
    for property_name, metadata in properties.items():
        if metadata.get("type") in accepted_types:
            return property_name, metadata.get("type")
    return None, None


def _collect_page_block_ids(page_id, headers):
    block_ids = []
    next_cursor = None
    has_more = True
    while has_more:
        params = {"page_size": 100}
        if next_cursor:
            params["start_cursor"] = next_cursor
        response = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        for block in payload.get("results", []):
            block_id = block.get("id")
            if block_id:
                block_ids.append(block_id)
        has_more = bool(payload.get("has_more"))
        next_cursor = payload.get("next_cursor")
    return block_ids


def _replace_page_content(page_id, headers):
    for block_id in _collect_page_block_ids(page_id, headers):
        archive_response = requests.patch(
            f"https://api.notion.com/v1/blocks/{block_id}",
            json={"archived": True},
            headers=headers,
            timeout=30,
        )
        archive_response.raise_for_status()


def update_notion_page(page_data, project_logger=None):
    project_logger = project_logger or logging.getLogger(__name__)
    notion_credentials = load_credentials.load_notion_credentials(project_logger=project_logger)

    item_type = str(page_data.get("item_type", "")).strip().lower()
    if item_type not in {"task", "card"}:
        raise ValueError("item_type must be 'task' or 'card'")

    page_id = _normalize_notion_object_id(page_data.get("page_id"))
    if not page_id:
        raise ValueError("page_id is required")
    if not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        page_id,
    ):
        raise ValueError("page_id must be a Notion page ID or URL containing a valid page ID")

    headers = {
        "accept": "application/json",
        "Authorization": "Bearer " + notion_credentials["api_key"] + "",
        "Notion-Version": "2022-06-28",
        "content-type": "application/json",
    }
    page_response = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=headers,
        timeout=30,
    )
    page_response.raise_for_status()
    page_payload = page_response.json()
    properties = page_payload.get("properties", {})
    if not isinstance(properties, dict):
        raise RuntimeError("Invalid Notion page properties payload")

    updates = {}
    updated_fields = []
    content = None
    if "content" in page_data:
        raw_content = str(page_data.get("content", ""))
        if raw_content.strip():
            content = raw_content
    content_mode = str(page_data.get("content_mode", "append")).strip().lower() or "append"
    if content_mode not in {"append", "replace"}:
        raise ValueError("content_mode must be 'append' or 'replace'")

    if item_type == "task":
        if "task_name" in page_data:
            title_property, _ = _find_property_name(properties, ("Task", "Name"), {"title"})
            if not title_property:
                raise ValueError("Task title property not found in Notion page")
            task_name = str(page_data.get("task_name", "")).strip()
            updates[title_property] = {"title": [{"text": {"content": task_name}}]}
            updated_fields.append("task_name")

        if "due_date" in page_data:
            date_property, _ = _find_property_name(properties, ("When", "Deadline"), {"date"})
            if not date_property:
                raise ValueError("Task date property not found in Notion page")
            updates[date_property] = {"date": {"start": page_data.get("due_date")}}
            updated_fields.append("due_date")

        if "project" in page_data:
            project_property, _ = _find_property_name(properties, ("Project",), {"select"})
            if not project_property:
                raise ValueError("Task project property not found in Notion page")
            project_name = str(page_data.get("project", "")).strip()
            updates[project_property] = {"select": {"name": project_name} if project_name else None}
            updated_fields.append("project")

        if "tags" in page_data:
            tags_property, tags_type = _find_property_name(properties, ("Tags",), {"multi_select", "select"})
            if not tags_property:
                raise ValueError("Task tags property not found in Notion page")
            tag_names = [str(tag).strip() for tag in page_data.get("tags", []) if str(tag).strip()]
            if tags_type == "multi_select":
                updates[tags_property] = {"multi_select": [{"name": tag} for tag in tag_names]}
            else:
                updates[tags_property] = {"select": {"name": tag_names[0]} if tag_names else None}
            updated_fields.append("tags")

        if "done" in page_data:
            done_property, _ = _find_property_name(properties, ("DONE",), {"checkbox"})
            if not done_property:
                raise ValueError("Task checkbox property not found in Notion page")
            updates[done_property] = {"checkbox": bool(page_data.get("done"))}
            updated_fields.append("done")

    if item_type == "card":
        if "note_name" in page_data:
            title_property, _ = _find_property_name(properties, ("Name", "Type"), {"title"})
            if not title_property:
                raise ValueError("Card title property not found in Notion page")
            note_name = str(page_data.get("note_name", "")).strip()
            updates[title_property] = {"title": [{"text": {"content": note_name}}]}
            updated_fields.append("note_name")

        if "tag" in page_data:
            tag_property, tag_type = _find_property_name(properties, ("Tags", "Type"), {"multi_select", "select"})
            if not tag_property:
                raise ValueError("Card tag property not found in Notion page")
            tag_name = str(page_data.get("tag", "")).strip()
            if tag_type == "multi_select":
                updates[tag_property] = {"multi_select": [{"name": tag_name}] if tag_name else []}
            else:
                updates[tag_property] = {"select": {"name": tag_name} if tag_name else None}
            updated_fields.append("tag")

        if "observations" in page_data:
            observations_property, _ = _find_property_name(
                properties,
                ("Observações", "Observacoes", "Observations"),
                {"rich_text"},
            )
            if not observations_property:
                raise ValueError("Card observations property not found in Notion page")
            updates[observations_property] = {
                "rich_text": _build_notion_rich_text_chunks(str(page_data.get("observations", ""))),
            }
            updated_fields.append("observations")

        if "url" in page_data:
            url_property, _ = _find_property_name(properties, ("URL",), {"url"})
            if not url_property:
                raise ValueError("Card url property not found in Notion page")
            external_url = str(page_data.get("url", "")).strip()
            updates[url_property] = {"url": external_url or None}
            updated_fields.append("url")

        if "date" in page_data:
            date_property, _ = _find_property_name(properties, ("Date", "Created"), {"date"})
            if not date_property:
                raise ValueError("Card date property not found in Notion page")
            updates[date_property] = {"date": {"start": page_data.get("date")}}
            updated_fields.append("date")

    if not updates and content is None:
        raise ValueError("No fields to update")

    result = page_payload
    if updates:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            json={"properties": updates},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

    if content is not None:
        if content_mode == "replace":
            _replace_page_content(page_id, headers)
        children = _build_note_children(content)
        append_response = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            json={"children": children},
            headers=headers,
            timeout=30,
        )
        append_response.raise_for_status()
        updated_fields.append("content")

    return {
        "id": result.get("id"),
        "page_url": result.get("url"),
        "item_type": item_type,
        "updated_fields": updated_fields,
    }


def _get_notes_database_id(project_logger):
    raw_notes_database_id = str(os.getenv("NOTION_NOTES_DB_ID", "")).strip()
    if raw_notes_database_id:
        normalized_id = _normalize_notion_object_id(raw_notes_database_id)
        return normalized_id
    error_message = "Missing required environment variable: NOTION_NOTES_DB_ID"
    project_logger.error(error_message)
    raise ValueError(error_message)


def _normalize_notion_object_id(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return value

    dashed_match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value,
    )
    if dashed_match:
        return dashed_match.group(0).lower()

    compact_match = re.search(r"[0-9a-fA-F]{32}", value)
    if compact_match:
        compact = compact_match.group(0).lower()
        return (
            f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-"
            f"{compact[16:20]}-{compact[20:32]}"
        )

    return value


def _build_create_note_payload(note_data, tags_property_type, observations_property):
    tag_payload = (
        {"multi_select": [{"name": note_data["tag"]}]}
        if tags_property_type == "multi_select"
        else {"select": {"name": note_data["tag"]}}
    )

    properties = {
        "Name": {
            "title": [{"text": {"content": note_data["note_name"]}}],
        },
        "Date": {
            "date": {"start": note_data["date"]},
        },
        "Tags": tag_payload,
        "URL": {
            "url": note_data["url"],
        },
    }

    if note_data["observations"]:
        properties[observations_property] = {
            "rich_text": _build_notion_rich_text_chunks(note_data["observations"]),
        }

    return properties


def _build_create_note_properties(
    note_data,
    title_property,
    date_property,
    tags_property=None,
    tags_property_type="multi_select",
    observations_property=None,
    url_property=None,
):
    properties = {
        title_property: {
            "title": [{"text": {"content": note_data["note_name"]}}],
        },
        date_property: {
            "date": {"start": note_data["date"]},
        },
    }

    if tags_property:
        if tags_property_type == "select":
            properties[tags_property] = {"select": {"name": note_data["tag"]}}
        else:
            properties[tags_property] = {"multi_select": [{"name": note_data["tag"]}]}

    if url_property and note_data["url"]:
        properties[url_property] = {"url": note_data["url"]}

    if observations_property and note_data["observations"]:
        properties[observations_property] = {
            "rich_text": _build_notion_rich_text_chunks(note_data["observations"]),
        }

    return properties


def _build_notion_rich_text_chunks(text, chunk_size=1800):
    value = str(text or "")
    if not value:
        return []

    segments = _parse_markdown_segments(value)
    rich_text = []
    for segment in segments:
        segment_text = segment["text"]
        if not segment_text:
            continue
        chunks = [segment_text[i : i + chunk_size] for i in range(0, len(segment_text), chunk_size)]
        for chunk in chunks:
            rich_item = {
                "type": "text",
                "text": {
                    "content": chunk,
                },
                "annotations": {
                    "bold": bool(segment.get("bold", False)),
                    "italic": bool(segment.get("italic", False)),
                    "strikethrough": False,
                    "underline": False,
                    "code": bool(segment.get("code", False)),
                    "color": "default",
                },
                "plain_text": chunk,
            }
            if segment.get("url"):
                rich_item["text"]["link"] = {"url": segment["url"]}
            rich_text.append(rich_item)
    return rich_text


def _parse_markdown_segments(text):
    pattern = re.compile(
        r"(\[([^\]]+)\]\((https?://[^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*)"
    )
    segments = []
    cursor = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > cursor:
            segments.append({"text": text[cursor:start]})
        if match.group(2) is not None:
            segments.append({"text": match.group(2), "url": match.group(3)})
        elif match.group(4) is not None:
            segments.append({"text": match.group(4), "bold": True})
        elif match.group(5) is not None:
            segments.append({"text": match.group(5), "code": True})
        elif match.group(6) is not None:
            segments.append({"text": match.group(6), "italic": True})
        cursor = end
    if cursor < len(text):
        segments.append({"text": text[cursor:]})
    return segments


def _build_note_children(text):
    value = str(text or "")
    if not value:
        return []

    blocks = []
    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        if line.startswith("### "):
            block_type = "heading_3"
            content = line[4:]
        elif line.startswith("## "):
            block_type = "heading_2"
            content = line[3:]
        elif line.startswith("# "):
            block_type = "heading_1"
            content = line[2:]
        elif line.startswith("- ") or line.startswith("* "):
            block_type = "bulleted_list_item"
            content = line[2:]
        elif re.match(r"^\d+\.\s+", line):
            block_type = "numbered_list_item"
            content = re.sub(r"^\d+\.\s+", "", line, count=1)
        else:
            block_type = "paragraph"
            content = line

        rich_text = _build_notion_rich_text_chunks(content)
        if not rich_text:
            continue
        blocks.append(
            {
                "object": "block",
                "type": block_type,
                block_type: {"rich_text": rich_text},
            }
        )

    if blocks:
        return blocks

    fallback = _build_notion_rich_text_chunks(value)
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": fallback},
        }
    ] if fallback else []


def _fetch_database_schema(database_id, api_key):
    headers = {
        "accept": "application/json",
        "Authorization": "Bearer " + api_key + "",
        "Notion-Version": "2022-06-28",
    }
    response = requests.get(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        timeout=30,
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    properties = payload.get("properties", {})
    return properties if isinstance(properties, dict) else {}


def _build_note_payload_from_schema(create_data, schema_properties):
    title_property = None
    for property_name, metadata in schema_properties.items():
        if metadata.get("type") == "title":
            title_property = property_name
            break
    if not title_property:
        return None

    properties = {
        title_property: {
            "title": [{"text": {"content": create_data["note_name"]}}],
        }
    }

    date_property = None
    for preferred in ("Date",):
        if schema_properties.get(preferred, {}).get("type") == "date":
            date_property = preferred
            break
    if not date_property:
        for property_name, metadata in schema_properties.items():
            if metadata.get("type") == "date":
                date_property = property_name
                break
    if date_property:
        properties[date_property] = {"date": {"start": create_data["date"]}}

    tag_properties = []
    for preferred in ("Tags", "Type"):
        metadata = schema_properties.get(preferred, {})
        if metadata.get("type") in ("multi_select", "select"):
            tag_properties.append((preferred, metadata.get("type")))
    if not tag_properties:
        for property_name, metadata in schema_properties.items():
            if metadata.get("type") in ("multi_select", "select"):
                tag_properties.append((property_name, metadata.get("type")))
                break
    for property_name, property_type in tag_properties:
        if property_type == "multi_select":
            properties[property_name] = {"multi_select": [{"name": create_data["tag"]}]}
        else:
            properties[property_name] = {"select": {"name": create_data["tag"]}}

    if create_data["url"]:
        for preferred in ("URL",):
            if schema_properties.get(preferred, {}).get("type") == "url":
                properties[preferred] = {"url": create_data["url"]}
                break
        else:
            for property_name, metadata in schema_properties.items():
                if metadata.get("type") == "url":
                    properties[property_name] = {"url": create_data["url"]}
                    break

    observations_property = None
    for preferred in ("Observações", "Observacoes", "Observations"):
        if schema_properties.get(preferred, {}).get("type") == "rich_text":
            observations_property = preferred
            break
    if not observations_property:
        for property_name, metadata in schema_properties.items():
            if metadata.get("type") == "rich_text":
                observations_property = property_name
                break
    if observations_property and create_data["observations"]:
        properties[observations_property] = {
            "rich_text": _build_notion_rich_text_chunks(create_data["observations"]),
        }

    payload = {"properties": properties}
    if create_data["observations"] and not observations_property:
        payload["children"] = _build_note_children(create_data["observations"])
    return payload


def create_note_in_notes_db(note_data, project_logger=None):
    project_logger = project_logger or logging.getLogger(__name__)
    notion_credentials = load_credentials.load_notion_credentials(project_logger=project_logger)
    notes_database_id = _get_notes_database_id(project_logger)

    note_name = str(note_data.get("note_name", "")).strip()
    if not note_name:
        raise ValueError("note_name is required")

    create_data = {
        "database_id": notes_database_id,
        "note_name": note_name,
        "tag": str(note_data.get("tag", "GENERAL")).strip() or "GENERAL",
        "date": datetime.date.today().isoformat(),
        "observations": str(note_data.get("observations", "")).strip(),
        "url": str(note_data.get("url", "")).strip() or None,
    }
    request_candidates = [
        {
            "notion_version": "2022-06-28",
            "parent": {"database_id": notes_database_id},
        },
        {
            "notion_version": os.getenv("NOTION_VERSION", "2025-09-03"),
            "parent": {"data_source_id": notes_database_id},
        },
    ]
    schema_properties = _fetch_database_schema(notes_database_id, notion_credentials["api_key"])
    last_error = None
    for request_candidate in request_candidates:
        headers = {
            "accept": "application/json",
            "Authorization": "Bearer " + notion_credentials["api_key"] + "",
            "Notion-Version": request_candidate["notion_version"],
            "content-type": "application/json",
        }
        payload_candidates = []
        schema_payload = _build_note_payload_from_schema(create_data, schema_properties)
        if schema_payload:
            payload = {
                "parent": request_candidate["parent"],
                "properties": schema_payload["properties"],
            }
            if schema_payload.get("children"):
                payload["children"] = schema_payload["children"]
            payload_candidates.append(payload)

        property_candidates = [
            _build_create_note_properties(
                create_data,
                title_property="Name",
                date_property="Date",
                tags_property="Tags",
                tags_property_type="multi_select",
                observations_property="Observações",
                url_property="URL",
            ),
            _build_create_note_properties(
                create_data,
                title_property="Name",
                date_property="Created",
                tags_property="Tags",
                tags_property_type="multi_select",
                observations_property="Observações",
                url_property="URL",
            ),
            _build_create_note_properties(
                create_data,
                title_property="Name",
                date_property="Created",
                tags_property="Tags",
                tags_property_type="select",
                observations_property=None,
                url_property=None,
            ),
            _build_create_note_properties(
                create_data,
                title_property="Type",
                date_property="Created",
                tags_property="Tags",
                tags_property_type="multi_select",
                observations_property=None,
                url_property=None,
            ),
            _build_create_note_properties(
                create_data,
                title_property="Type",
                date_property="Created",
                tags_property="Tags",
                tags_property_type="select",
                observations_property=None,
                url_property=None,
            ),
            _build_create_note_properties(
                create_data,
                title_property="Name",
                date_property="Date",
                tags_property="Tags",
                tags_property_type="multi_select",
                observations_property="Observacoes",
                url_property="URL",
            ),
            _build_create_note_properties(
                create_data,
                title_property="Name",
                date_property="Date",
                tags_property=None,
                observations_property=None,
                url_property=None,
            ),
            _build_create_note_properties(
                create_data,
                title_property="Type",
                date_property="Created",
                tags_property=None,
                observations_property=None,
                url_property=None,
            ),
        ]
        for properties in property_candidates:
            payload = {
                "parent": request_candidate["parent"],
                "properties": properties,
            }
            has_observations_property = any(
                key in properties for key in ("Observações", "Observacoes", "Observations")
            )
            if create_data["observations"] and not has_observations_property:
                payload["children"] = _build_note_children(create_data["observations"])
            payload_candidates.append(payload)
        for payload in payload_candidates:
            response = requests.post(
                "https://api.notion.com/v1/pages",
                json=payload,
                headers=headers,
                timeout=30,
            )
            response_payload = {}
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {}
            if response.status_code in (400, 404):
                response_code = response_payload.get("code", "")
                if response_code in ("validation_error", "object_not_found", "invalid_request"):
                    last_error = response
                    continue
            response.raise_for_status()
            return {
                "id": response_payload.get("id"),
                "page_url": response_payload.get("url"),
                "note_name": create_data["note_name"],
                "tag": create_data["tag"],
                "date": create_data["date"],
                "observations": create_data["observations"],
                "url": create_data["url"],
            }

    if last_error is not None:
        try:
            error_payload = last_error.json()
        except ValueError:
            error_payload = {}
        if error_payload.get("code") == "object_not_found":
            raise ValueError(
                "NOTION_NOTES_DB_ID was not found by the Notion API. "
                "Please verify the exact Notes database/data-source ID and sharing with the integration."
            ) from None
        last_error.raise_for_status()
    raise RuntimeError("Failed to create note in Notion")


def collect_notes_around_today(days_back=5, days_forward=5, project_logger=None):
    project_logger = project_logger or logging.getLogger(__name__)
    notion_credentials = load_credentials.load_notion_credentials(project_logger=project_logger)
    notes_database_id = _get_notes_database_id(project_logger)

    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=max(days_back, 0))).isoformat()
    end_date = (today + datetime.timedelta(days=max(days_forward, 0))).isoformat()

    query_candidates = [
        {
            "url": f"https://api.notion.com/v1/data_sources/{notes_database_id}/query",
            "notion_version": os.getenv("NOTION_VERSION", "2025-09-03"),
            "date_property": "Date",
            "date_filter_type": "property_date",
        },
        {
            "url": f"https://api.notion.com/v1/data_sources/{notes_database_id}/query",
            "notion_version": os.getenv("NOTION_VERSION", "2025-09-03"),
            "date_property": "Created",
            "date_filter_type": "property_date",
        },
        {
            "url": f"https://api.notion.com/v1/data_sources/{notes_database_id}/query",
            "notion_version": os.getenv("NOTION_VERSION", "2025-09-03"),
            "date_property": "created_time",
            "date_filter_type": "created_time",
        },
        {
            "url": f"https://api.notion.com/v1/databases/{notes_database_id}/query",
            "notion_version": "2022-06-28",
            "date_property": "Date",
            "date_filter_type": "property_date",
        },
        {
            "url": f"https://api.notion.com/v1/databases/{notes_database_id}/query",
            "notion_version": "2022-06-28",
            "date_property": "Created",
            "date_filter_type": "property_date",
        },
        {
            "url": f"https://api.notion.com/v1/databases/{notes_database_id}/query",
            "notion_version": "2022-06-28",
            "date_property": "created_time",
            "date_filter_type": "created_time",
        },
    ]

    project_logger.info("Collecting notes from Notion around today...")

    all_notes = []
    next_cursor = None
    has_more = True
    selected_candidate = None
    while has_more:
        if selected_candidate is None:
            request_payload = None
        else:
            request_payload = _build_notes_query_payload(
                selected_candidate,
                start_date,
                end_date,
            )
        if next_cursor:
            request_payload["start_cursor"] = next_cursor

        if selected_candidate is None:
            last_error = None
            for candidate in query_candidates:
                request_payload = _build_notes_query_payload(candidate, start_date, end_date)
                if next_cursor:
                    request_payload["start_cursor"] = next_cursor
                headers = {
                    "accept": "application/json",
                    "Authorization": "Bearer " + notion_credentials["api_key"] + "",
                    "Notion-Version": candidate["notion_version"],
                    "content-type": "application/json",
                }
                response = requests.post(candidate["url"], json=request_payload, headers=headers, timeout=30)
                if response.status_code in (400, 404):
                    response_code = response.json().get("code", "")
                    if response_code in ("invalid_request_url", "object_not_found", "validation_error"):
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

        for note in data.get("results", []):
            properties = note.get("properties", {})
            note_title = (
                properties.get("Name", {}).get("title", [])
                or properties.get("Type", {}).get("title", [])
            )
            note_date = (
                properties.get("Date", {}).get("date")
                or properties.get("Created", {}).get("date")
                or {"start": note.get("created_time")}
            )
            tags_property = properties.get("Tags", {})
            tags = []
            if tags_property.get("type") == "multi_select":
                tags = [tag.get("name") for tag in tags_property.get("multi_select", []) if tag.get("name")]
            elif tags_property.get("type") == "select":
                tag_name = tags_property.get("select", {}).get("name")
                tags = [tag_name] if tag_name else []
            elif properties.get("Type", {}).get("type") == "select":
                type_tag = properties.get("Type", {}).get("select", {}).get("name")
                tags = [type_tag] if type_tag else []

            observations_property = properties.get("Observações", {}).get("rich_text")
            if observations_property is None:
                observations_property = properties.get("Observacoes", {}).get("rich_text", [])
            observations = "".join(
                chunk.get("plain_text") or chunk.get("text", {}).get("content", "")
                for chunk in observations_property
            )
            external_url = properties.get("URL", {}).get("url")

            if not note_title or not note_date or not note_date.get("start"):
                project_logger.warning("Skipping malformed Notion note payload: %s", note.get("id"))
                continue

            all_notes.append(
                {
                    "id": note.get("id"),
                    "name": (
                        (note_title[0].get("plain_text") or note_title[0].get("text", {}).get("content"))
                        if note_title else "Untitled note"
                    ),
                    "date": note_date["start"],
                    "tags": tags,
                    "observations": observations,
                    "url": external_url,
                    "page_url": note.get("url"),
                }
            )

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return sorted(all_notes, key=lambda note: note["date"])


def _build_notes_query_payload(candidate, start_date, end_date):
    if candidate.get("date_filter_type") == "created_time":
        return {
            "filter": {
                "and": [
                    {"timestamp": "created_time", "created_time": {"on_or_after": start_date}},
                    {"timestamp": "created_time", "created_time": {"on_or_before": end_date}},
                ],
            },
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": 100,
        }
    return {
        "filter": {
            "and": [
                {
                    "property": candidate["date_property"],
                    "date": {"on_or_after": start_date},
                },
                {
                    "property": candidate["date_property"],
                    "date": {"on_or_before": end_date},
                },
            ],
        },
        "sorts": [
            {"property": candidate["date_property"], "direction": "ascending"},
        ],
        "page_size": 100,
    }
