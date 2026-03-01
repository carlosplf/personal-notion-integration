import unittest
from unittest.mock import patch

from notion_connector import notion_connector


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _MockLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class TestNotionConnector(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
