import unittest
import datetime
import requests
from unittest.mock import patch

from notion_connector import notion_connector


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)
        return None


class _MockLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class TestNotionConnector(unittest.TestCase):
    def test_build_notion_rich_text_chunks_preserves_markdown_annotations(self):
        rich_text = notion_connector._build_notion_rich_text_chunks(
            "Texto **negrito** *italico* `codigo` [link](https://example.com)"
        )
        self.assertTrue(any(item.get("annotations", {}).get("bold") for item in rich_text))
        self.assertTrue(any(item.get("annotations", {}).get("italic") for item in rich_text))
        self.assertTrue(any(item.get("annotations", {}).get("code") for item in rich_text))
        self.assertTrue(any(item.get("text", {}).get("link", {}).get("url") == "https://example.com" for item in rich_text))

    def test_build_note_children_maps_markdown_blocks(self):
        blocks = notion_connector._build_note_children(
            "# Titulo\n- Item 1\n1. Passo 1\nParagrafo final"
        )
        self.assertEqual(blocks[0]["type"], "heading_1")
        self.assertEqual(blocks[1]["type"], "bulleted_list_item")
        self.assertEqual(blocks[2]["type"], "numbered_list_item")
        self.assertEqual(blocks[3]["type"], "paragraph")

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_tasks_supports_when_property(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "task-1",
                        "properties": {
                            "Task": {
                                "title": [{"plain_text": "Minha tarefa"}]
                            },
                            "When": {
                                "date": {"start": "2026-03-01T10:00:00.000Z"}
                            },
                            "Project": {"select": {"name": "Projeto X"}},
                            "Tags": {
                                "type": "multi_select",
                                "multi_select": [{"name": "FAST"}, {"name": "FUP"}],
                            },
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        tasks = notion_connector.collect_tasks_from_control_panel(
            n_days=0,
            project_logger=_MockLogger(),
        )

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "Minha tarefa")
        self.assertEqual(tasks[0]["deadline"], "2026-03-01T10:00:00.000Z")
        self.assertEqual(tasks[0]["project"], "Projeto X")
        self.assertEqual(tasks[0]["tags"], ["FAST", "FUP"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_tasks_uses_cutoff_filter_for_overdue_and_upcoming(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"results": [], "has_more": False, "next_cursor": None})

        notion_connector.collect_tasks_from_control_panel(
            n_days=2,
            project_logger=_MockLogger(),
        )

        request_payload = mock_post.call_args.kwargs["json"]
        and_filters = request_payload["filter"]["and"]
        self.assertEqual(and_filters[0]["property"], "DONE")
        self.assertEqual(and_filters[0]["checkbox"]["equals"], False)
        self.assertEqual(and_filters[1]["property"], "When")
        self.assertIn("before", and_filters[1]["date"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_task_in_control_panel_posts_expected_fields(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "page-1", "url": "https://notion.so/page-1"})

        result = notion_connector.create_task_in_control_panel(
            {
                "task_name": "Enviar proposta",
                "project": "Draiven",
                "due_date": "2026-03-05",
                "tags": ["FAST", "FUP"],
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "page-1")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "db-id")
        self.assertIn("Task", payload["properties"])
        self.assertIn("When", payload["properties"])
        self.assertEqual(
            payload["properties"]["Project"]["select"]["name"],
            "Draiven",
        )

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_posts_expected_fields(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"})
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "URL": {"type": "url"},
                    "Observações": {"type": "rich_text"},
                }
            }
        )

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Ideia de onboarding",
                    "tag": "IDEA",
                    "observations": "Criar checklist para novos clientes",
                    "url": "https://example.com",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-1")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "notes-db-id")
        self.assertEqual(payload["properties"]["Name"]["title"][0]["text"]["content"], "Ideia de onboarding")
        self.assertEqual(payload["properties"]["Date"]["date"]["start"], datetime.date.today().isoformat())
        self.assertIn("Tags", payload["properties"])

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_fallbacks_on_not_found(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                }
            }
        )
        mock_post.side_effect = [
            _MockResponse({"code": "object_not_found"}, status_code=404),
            _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200),
        ]

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {"note_name": "Fallback note", "tag": "GENERAL", "observations": "abc", "url": ""},
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-1")
        self.assertEqual(mock_post.call_count, 2)

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_splits_long_observations(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200)
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "Observações": {"type": "rich_text"},
                }
            }
        )

        long_observations = "x" * 4200
        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Long note",
                    "tag": "GENERAL",
                    "observations": long_observations,
                    "url": "",
                },
                project_logger=_MockLogger(),
            )

        payload = mock_post.call_args.kwargs["json"]
        rich_text = payload["properties"]["Observações"]["rich_text"]
        self.assertGreater(len(rich_text), 1)
        self.assertTrue(all(len(item["text"]["content"]) <= 1800 for item in rich_text))
        self.assertNotIn("children", payload)

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_normalizes_database_id_from_url(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200)
        mock_get.return_value = _MockResponse(
            {"properties": {"Name": {"type": "title"}, "Date": {"type": "date"}}}
        )
        notes_url = "https://www.notion.so/workspace/123456781234123412341234567890ab?v=abcd"

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": notes_url}, clear=False):
            notion_connector.create_note_in_notes_db(
                {"note_name": "Normalize id", "tag": "GENERAL", "observations": "x", "url": ""},
                project_logger=_MockLogger(),
            )

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "12345678-1234-1234-1234-1234567890ab")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_supports_type_created_schema(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Created": {"type": "created_time"},
                    "Tags": {"type": "multi_select"},
                    "Type": {"type": "select"},
                }
            }
        )

        def _side_effect(*_args, **kwargs):
            properties = kwargs["json"]["properties"]
            if "Name" in properties and "title" in properties["Name"] and "Tags" in properties:
                return _MockResponse({"id": "note-2", "url": "https://notion.so/note-2"}, status_code=200)
            return _MockResponse({"code": "validation_error"}, status_code=400)

        mock_post.side_effect = _side_effect

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Schema fallback",
                    "tag": "GENERAL",
                    "observations": "Long body without dedicated observations property",
                    "url": "",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-2")
        success_payload = mock_post.call_args.kwargs["json"]
        self.assertIn("children", success_payload)

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_notes_around_today_filters_and_parses(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "note-1",
                        "url": "https://notion.so/note-1",
                        "properties": {
                            "Name": {"title": [{"plain_text": "Daily insight"}]},
                            "Date": {"date": {"start": "2026-03-01"}},
                            "Tags": {"type": "multi_select", "multi_select": [{"name": "IDEA"}]},
                            "Observações": {"rich_text": [{"plain_text": "Review weekly goals"}]},
                            "URL": {"url": "https://example.com"},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notes = notion_connector.collect_notes_around_today(
                days_back=5,
                days_forward=5,
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["name"], "Daily insight")
        self.assertEqual(notes[0]["tags"], ["IDEA"])
        self.assertEqual(notes[0]["observations"], "Review weekly goals")
        payload = mock_post.call_args.kwargs["json"]
        and_filters = payload["filter"]["and"]
        self.assertEqual(and_filters[0]["property"], "Date")
        self.assertEqual(and_filters[1]["property"], "Date")
        self.assertIn("on_or_after", and_filters[0]["date"])
        self.assertIn("on_or_before", and_filters[1]["date"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_notes_around_today_supports_created_and_type_properties(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}

        def _side_effect(*_args, **kwargs):
            payload = kwargs["json"]
            first_filter = payload["filter"]["and"][0]
            if first_filter.get("property") == "Date":
                return _MockResponse({"code": "validation_error"}, status_code=400)
            if first_filter.get("property") == "Created":
                return _MockResponse({"code": "validation_error"}, status_code=400)
            return _MockResponse(
                {
                    "results": [
                        {
                            "id": "note-2",
                            "url": "https://notion.so/note-2",
                            "created_time": "2026-03-02T09:00:00.000Z",
                            "properties": {
                                "Type": {"title": [{"plain_text": "Type-based note"}]},
                                "Tags": {"type": "select", "select": {"name": "GENERAL"}},
                                "Status": {"type": "status", "status": {"name": "Open"}},
                            },
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                },
                status_code=200,
            )

        mock_post.side_effect = _side_effect

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notes = notion_connector.collect_notes_around_today(
                days_back=5,
                days_forward=5,
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["name"], "Type-based note")
        self.assertTrue(notes[0]["date"].startswith("2026-03-02"))
        self.assertEqual(notes[0]["tags"], ["GENERAL"])

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_updates_task_fields(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "id": "task-page",
                "url": "https://notion.so/task-page",
                "properties": {
                    "Task": {"type": "title"},
                    "When": {"type": "date"},
                    "Project": {"type": "select"},
                    "Tags": {"type": "multi_select"},
                    "DONE": {"type": "checkbox"},
                },
            }
        )
        mock_patch.return_value = _MockResponse({"id": "task-page", "url": "https://notion.so/task-page"})

        result = notion_connector.update_notion_page(
            {
                "item_type": "task",
                "page_id": "123456781234123412341234567890ab",
                "task_name": "Atualizar backlog",
                "due_date": "2026-03-11",
                "project": "Pessoal",
                "tags": ["FAST"],
                "done": True,
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "task-page")
        payload = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertEqual(payload["Task"]["title"][0]["text"]["content"], "Atualizar backlog")
        self.assertEqual(payload["When"]["date"]["start"], "2026-03-11")
        self.assertEqual(payload["Project"]["select"]["name"], "Pessoal")
        self.assertEqual(payload["Tags"]["multi_select"][0]["name"], "FAST")
        self.assertTrue(payload["DONE"]["checkbox"])

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_updates_card_fields(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "id": "card-page",
                "url": "https://notion.so/card-page",
                "properties": {
                    "Name": {"type": "title"},
                    "Tags": {"type": "select"},
                    "Date": {"type": "date"},
                    "Observações": {"type": "rich_text"},
                    "URL": {"type": "url"},
                },
            }
        )
        mock_patch.return_value = _MockResponse({"id": "card-page", "url": "https://notion.so/card-page"})

        result = notion_connector.update_notion_page(
            {
                "item_type": "card",
                "page_id": "card-page",
                "note_name": "Novo card",
                "tag": "IDEA",
                "date": "2026-03-12",
                "observations": "Texto do card",
                "url": "https://example.com",
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "card-page")
        payload = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertEqual(payload["Name"]["title"][0]["text"]["content"], "Novo card")
        self.assertEqual(payload["Tags"]["select"]["name"], "IDEA")
        self.assertEqual(payload["Date"]["date"]["start"], "2026-03-12")
        self.assertEqual(payload["URL"]["url"], "https://example.com")
        self.assertTrue(payload["Observações"]["rich_text"])


if __name__ == "__main__":
    unittest.main()
