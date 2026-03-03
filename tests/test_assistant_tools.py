import unittest
import os
import tempfile
from unittest.mock import patch

from assistant_connector.models import AgentDefinition, ToolExecutionContext
from assistant_connector.tools import (
    calendar_tools,
    contacts_tools,
    email_tools,
    meta_tools,
    news_tools,
    notion_tools,
)


class _FakeLogger:
    def exception(self, *_args, **_kwargs):
        return None


def _build_context():
    agent = AgentDefinition(
        agent_id="personal_assistant",
        description="desc",
        model="model",
        system_prompt="prompt",
        tools=[],
    )
    return ToolExecutionContext(
        session_id="session",
        user_id="user",
        channel_id="channel",
        guild_id="guild",
        project_logger=_FakeLogger(),
        agent=agent,
        available_tools=[{"name": "list_notion_tasks"}],
        available_agents=[{"id": "personal_assistant"}],
    )


class TestAssistantTools(unittest.TestCase):
    @patch("assistant_connector.tools.news_tools._load_sources_config")
    @patch("assistant_connector.tools.news_tools.urlopen")
    def test_list_tech_news_returns_configured_sources_only(self, mock_urlopen, mock_load_sources):
        class _Response:
            def __init__(self, content):
                self._content = content

            def read(self):
                return self._content

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        rss_payload = b"""<?xml version="1.0"?>
        <rss><channel>
          <item><title>AI launch</title><link>https://example.com/a</link><pubDate>Mon, 01 Mar 2026 20:00:00 GMT</pubDate><description>technology</description></item>
        </channel></rss>"""
        top_ids_payload = b"[1001]"
        hn_item_payload = b'{"id":1001,"title":"Startup growth","url":"https://news.ycombinator.com/item?id=1001","time":1772409600}'
        mock_load_sources.return_value = {
            "defaults": {"categories": ["startup"], "date_filter": {"mode": "recent", "lookback_days": 3650}},
            "sources": [
                {"name": "techcrunch", "url": "https://techcrunch.com/", "enabled": True, "filters": {}},
                {"name": "hackernews", "url": "https://news.ycombinator.com/", "enabled": True, "filters": {}},
            ],
        }
        mock_urlopen.side_effect = [
            _Response(rss_payload),
            _Response(top_ids_payload),
            _Response(hn_item_payload),
        ]

        result = news_tools.list_tech_news(
            {"topic": "startup", "limit": 3, "include_hacker_news": True, "max_age_hours": 999},
            _build_context(),
        )

        self.assertEqual(result["returned"], 1)
        self.assertTrue(any(item["source"] == "Hacker News" for item in result["news"]))
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("assistant_connector.tools.news_tools._load_sources_config")
    @patch("assistant_connector.tools.news_tools.urlopen")
    def test_list_tech_news_applies_requested_age_cutoff(self, mock_urlopen, mock_load_sources):
        class _Response:
            def __init__(self, content):
                self._content = content

            def read(self):
                return self._content

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        rss_payload = b"""<?xml version="1.0"?>
        <rss><channel>
          <item><title>Tech recap</title><link>https://example.com/old</link><pubDate>Mon, 01 Mar 2021 20:00:00 GMT</pubDate><description>technology</description></item>
        </channel></rss>"""
        mock_load_sources.return_value = {
            "defaults": {"categories": ["technology"], "date_filter": {"mode": "recent", "lookback_days": 3650}},
            "sources": [{"name": "techcrunch", "url": "https://techcrunch.com/", "enabled": True, "filters": {}}],
        }
        mock_urlopen.side_effect = [_Response(rss_payload)]

        result = news_tools.list_tech_news(
            {"limit": 5, "max_age_hours": 6},
            _build_context(),
        )

        self.assertEqual(result["returned"], 0)

    @patch("assistant_connector.tools.notion_tools.notion_connector.collect_tasks_from_control_panel")
    def test_list_notion_tasks_clamps_inputs(self, mock_collect_tasks):
        mock_collect_tasks.return_value = [{"name": f"Task {i}"} for i in range(60)]

        result = notion_tools.list_notion_tasks(
            {"n_days": -4, "limit": 100},
            _build_context(),
        )

        mock_collect_tasks.assert_called_once_with(n_days=0, project_logger=unittest.mock.ANY)
        self.assertEqual(result["returned"], 50)
        self.assertEqual(len(result["tasks"]), 50)

    @patch("assistant_connector.tools.notion_tools.notion_connector.create_task_in_control_panel")
    def test_create_notion_task_uses_defaults_and_cleans_tags(self, mock_create_task):
        mock_create_task.return_value = {"id": "task-1"}

        result = notion_tools.create_notion_task(
            {
                "task_name": "  Revisar proposta  ",
                "project": "  ",
                "tags": [" FAST ", "", "FUP"],
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "task-1")
        payload = mock_create_task.call_args.args[0]
        self.assertEqual(payload["task_name"], "Revisar proposta")
        self.assertEqual(payload["project"], "Pessoal")
        self.assertEqual(payload["tags"], ["FAST", "FUP"])

    def test_create_notion_task_rejects_invalid_tags(self):
        with self.assertRaises(ValueError):
            notion_tools.create_notion_task(
                {"task_name": "Task", "tags": "FAST"},
                _build_context(),
            )

    @patch("assistant_connector.tools.notion_tools.notion_connector.collect_notes_around_today")
    def test_list_notion_notes_clamps_inputs(self, mock_collect_notes):
        mock_collect_notes.return_value = [{"name": f"Note {i}"} for i in range(120)]

        result = notion_tools.list_notion_notes(
            {"days_back": -3, "days_forward": -1, "limit": 999},
            _build_context(),
        )

        mock_collect_notes.assert_called_once_with(days_back=0, days_forward=0, project_logger=unittest.mock.ANY)
        self.assertEqual(result["returned"], 100)
        self.assertEqual(len(result["notes"]), 100)

    @patch("assistant_connector.tools.notion_tools.notion_connector.create_note_in_notes_db")
    def test_create_notion_note_accepts_rich_observations(self, mock_create_note):
        mock_create_note.return_value = {"id": "note-1"}

        rich_observations = (
            "Resumo completo:\n"
            "- Contexto\n"
            "- Decisões\n"
            "- Próximos passos\n\n"
            "Detalhes adicionais com múltiplos parágrafos."
        )
        result = notion_tools.create_notion_note(
            {
                "note_name": "Reunião produto",
                "tag": "MEETING",
                "observations": rich_observations,
                "url": "https://example.com/doc",
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "note-1")
        payload = mock_create_note.call_args.args[0]
        self.assertEqual(payload["note_name"], "Reunião produto")
        self.assertEqual(payload["tag"], "MEETING")
        self.assertEqual(payload["observations"], rich_observations)
        self.assertEqual(payload["url"], "https://example.com/doc")

    def test_create_notion_note_requires_name(self):
        with self.assertRaises(ValueError):
            notion_tools.create_notion_note(
                {"note_name": "   ", "observations": "conteúdo"},
                _build_context(),
            )

    @patch("assistant_connector.tools.notion_tools.notion_connector.create_expense_in_expenses_db")
    def test_register_financial_expense_creates_expense_page(self, mock_create_expense):
        mock_create_expense.return_value = {"id": "expense-1"}

        result = notion_tools.register_financial_expense(
            {"description": "Uber casa", "amount": 45.5, "expense_date": "2026-03-10"},
            _build_context(),
        )

        self.assertEqual(result["status"], "created")
        payload = mock_create_expense.call_args.args[0]
        self.assertEqual(payload["name"], "Despesa 2026-03-10")
        self.assertEqual(payload["date"], "2026-03-10")
        self.assertEqual(payload["category"], "Transporte")
        self.assertEqual(payload["amount"], 45.5)

    @patch("assistant_connector.tools.notion_tools.notion_connector.create_expense_in_expenses_db")
    def test_register_financial_expense_normalizes_category_aliases(self, mock_create_expense):
        mock_create_expense.return_value = {"id": "expense-2"}

        notion_tools.register_financial_expense(
            {"description": "Consulta médica", "amount": 120, "category": "saude", "expense_date": "2026-03-11"},
            _build_context(),
        )

        payload = mock_create_expense.call_args.args[0]
        self.assertEqual(payload["category"], "Saúde")

    @patch("assistant_connector.tools.notion_tools.notion_connector.collect_expenses_from_expenses_db")
    def test_analyze_monthly_expenses_returns_totals_breakdown_and_top_expense(self, mock_collect_expenses):
        mock_collect_expenses.return_value = [
            {
                "id": "expense-1",
                "date": "2026-03-02",
                "amount": 50.00,
                "category": "Transporte",
                "description": "Uber ida",
            },
            {
                "id": "expense-2",
                "date": "2026-03-03",
                "amount": 120.00,
                "category": "Alimentação",
                "description": "Mercado",
            }
        ]

        result = notion_tools.analyze_monthly_expenses({"month": "2026-03"}, _build_context())

        self.assertEqual(result["month"], "2026-03")
        self.assertEqual(result["total_spent"], 170.0)
        self.assertEqual(result["expenses_count"], 2)
        self.assertEqual(result["breakdown_by_category"][0]["category"], "Alimentação")
        self.assertEqual(result["top_expense"]["amount"], 120.0)

    def test_analyze_monthly_expenses_validates_month_format(self):
        with self.assertRaises(ValueError):
            notion_tools.analyze_monthly_expenses({"month": "03-2026"}, _build_context())

    @patch("assistant_connector.tools.notion_tools.notion_connector.update_notion_page")
    def test_edit_notion_item_updates_task_payload(self, mock_update_page):
        mock_update_page.return_value = {"id": "task-1", "updated_fields": ["task_name", "done"]}

        result = notion_tools.edit_notion_item(
            {
                "item_type": "task",
                "page_id": "https://www.notion.so/workspace/123456781234123412341234567890ab",
                "task_name": "  Fechar sprint ",
                "done": True,
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "task-1")
        payload = mock_update_page.call_args.args[0]
        self.assertEqual(payload["item_type"], "task")
        self.assertEqual(payload["task_name"], "Fechar sprint")
        self.assertTrue(payload["done"])

    @patch("assistant_connector.tools.notion_tools.notion_connector.update_notion_page")
    def test_edit_notion_item_updates_card_payload(self, mock_update_page):
        mock_update_page.return_value = {"id": "card-1", "updated_fields": ["note_name", "date"]}

        result = notion_tools.edit_notion_item(
            {
                "item_type": "card",
                "page_id": "card-page-id",
                "note_name": "Retro semanal",
                "date": "2026-03-10",
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "card-1")
        payload = mock_update_page.call_args.args[0]
        self.assertEqual(payload["item_type"], "card")
        self.assertEqual(payload["note_name"], "Retro semanal")
        self.assertEqual(payload["date"], "2026-03-10")

    def test_edit_notion_item_requires_editable_fields(self):
        with self.assertRaises(ValueError):
            notion_tools.edit_notion_item(
                {"item_type": "task", "page_id": "task-id"},
                _build_context(),
            )

    @patch("assistant_connector.tools.notion_tools.notion_connector.update_notion_page")
    def test_edit_notion_item_ignores_empty_task_fields(self, mock_update_page):
        mock_update_page.return_value = {"id": "task-1", "updated_fields": ["done"]}

        result = notion_tools.edit_notion_item(
            {
                "item_type": "task",
                "page_id": "task-id",
                "task_name": "   ",
                "due_date": "",
                "done": True,
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "task-1")
        payload = mock_update_page.call_args.args[0]
        self.assertEqual(payload, {"item_type": "task", "page_id": "task-id", "done": True})

    @patch("assistant_connector.tools.notion_tools.notion_connector.update_notion_page")
    def test_edit_notion_item_accepts_page_content_update(self, mock_update_page):
        mock_update_page.return_value = {"id": "task-1", "updated_fields": ["content"]}

        result = notion_tools.edit_notion_item(
            {
                "item_type": "task",
                "page_id": "task-id",
                "content": "# Novo conteúdo\n\n- item",
                "content_mode": "replace",
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "task-1")
        payload = mock_update_page.call_args.args[0]
        self.assertEqual(payload["content_mode"], "replace")
        self.assertIn("Novo conteúdo", payload["content"])

    @patch("assistant_connector.tools.calendar_tools.calendar_connector.list_week_events")
    def test_list_calendar_events_clamps_max_results(self, mock_list_events):
        mock_list_events.return_value = [{"id": "1"}]

        result = calendar_tools.list_calendar_events(
            {"max_results": 500},
            _build_context(),
        )

        mock_list_events.assert_called_once_with(project_logger=unittest.mock.ANY, max_results=100)
        self.assertEqual(result["total"], 1)

    @patch("assistant_connector.tools.calendar_tools.calendar_connector.create_calendar_event")
    def test_create_calendar_event_passes_arguments(self, mock_create_event):
        mock_create_event.return_value = {"id": "event-1"}

        result = calendar_tools.create_calendar_event(
            {
                "summary": "Reunião",
                "start_datetime": "2026-03-03T10:00",
                "end_datetime": "2026-03-03T11:00",
                "description": "Kickoff",
                "timezone": "America/Sao_Paulo",
            },
            _build_context(),
        )

        self.assertEqual(result["id"], "event-1")
        mock_create_event.assert_called_once()

    def test_create_calendar_event_requires_fields(self):
        with self.assertRaises(ValueError):
            calendar_tools.create_calendar_event(
                {"summary": "", "start_datetime": "2026-03-03T10:00", "end_datetime": "2026-03-03T11:00"},
                _build_context(),
            )

    def test_meta_tools_return_context_catalogs(self):
        context = _build_context()
        tools_payload = meta_tools.list_available_tools({}, context)
        agents_payload = meta_tools.list_available_agents({}, context)

        self.assertEqual(tools_payload["agent_id"], "personal_assistant")
        self.assertEqual(agents_payload["active_agent_id"], "personal_assistant")

    @patch("assistant_connector.tools.email_tools.gmail_connector.send_custom_email")
    def test_send_email_applies_signature_and_prefix(self, mock_send_custom_email):
        mock_send_custom_email.return_value = {"id": "msg-1"}
        with patch.dict(
            os.environ,
            {
                "EMAIL_ASSISTANT_SIGNATURE": "Carlos",
                "EMAIL_ASSISTANT_SUBJECT_PREFIX": "[Assistente]",
                "EMAIL_ASSISTANT_TONE": "direto",
            },
            clear=False,
        ):
            result = email_tools.send_email(
                {
                    "subject": "Atualização semanal",
                    "body": "Segue status.",
                    "recipient_email": "x@example.com",
                },
                _build_context(),
            )

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["signature_applied"])
        self.assertEqual(result["subject"], "[Assistente] Atualização semanal")
        sent_body = mock_send_custom_email.call_args.kwargs["body_text"]
        self.assertIn("Segue status.", sent_body)
        self.assertIn("Carlos", sent_body)

    @patch("assistant_connector.tools.email_tools.gmail_connector.send_custom_email")
    def test_send_email_can_skip_signature(self, mock_send_custom_email):
        mock_send_custom_email.return_value = {"id": "msg-1"}
        with patch.dict(os.environ, {"EMAIL_ASSISTANT_SIGNATURE": "Carlos"}, clear=False):
            email_tools.send_email(
                {
                    "subject": "Atualização",
                    "body": "Sem assinatura.",
                    "recipient_email": "x@example.com",
                    "include_signature": False,
                },
                _build_context(),
            )

        sent_body = mock_send_custom_email.call_args.kwargs["body_text"]
        self.assertNotIn("Carlos", sent_body)

    def test_send_email_requires_subject_and_body(self):
        with self.assertRaises(ValueError):
            email_tools.send_email(
                {"recipient_email": "x@example.com", "subject": "", "body": "abc"},
                _build_context(),
            )
        with self.assertRaises(ValueError):
            email_tools.send_email(
                {"recipient_email": "x@example.com", "subject": "abc", "body": ""},
                _build_context(),
            )

    def test_send_email_requires_recipient(self):
        with self.assertRaises(ValueError):
            email_tools.send_email(
                {"subject": "abc", "body": "conteúdo"},
                _build_context(),
            )

    @patch("assistant_connector.tools.email_tools.gmail_connector.search_emails")
    def test_search_emails_passes_filters(self, mock_search_emails):
        mock_search_emails.return_value = {"returned": 0, "emails": []}

        email_tools.search_emails(
            {"query": "from:ana@example.com", "max_results": 5, "include_body": True},
            _build_context(),
        )

        kwargs = mock_search_emails.call_args.kwargs
        self.assertEqual(kwargs["query"], "from:ana@example.com")
        self.assertEqual(kwargs["max_results"], 5)
        self.assertTrue(kwargs["include_body"])

    @patch("assistant_connector.tools.email_tools.gmail_connector.read_email")
    def test_read_email_requires_message_id(self, mock_read_email):
        mock_read_email.return_value = {"id": "m1"}

        with self.assertRaises(ValueError):
            email_tools.read_email({}, _build_context())

    @patch("assistant_connector.tools.email_tools.gmail_connector.search_email_attachments")
    def test_search_email_attachments_passes_filters(self, mock_search_attachments):
        mock_search_attachments.return_value = {"returned": 0, "attachments": []}

        email_tools.search_email_attachments(
            {"query": "from:ana@example.com", "filename_contains": ".pdf", "max_results": 8},
            _build_context(),
        )

        kwargs = mock_search_attachments.call_args.kwargs
        self.assertEqual(kwargs["query"], "from:ana@example.com")
        self.assertEqual(kwargs["filename_contains"], ".pdf")
        self.assertEqual(kwargs["max_results"], 8)

    @patch("assistant_connector.tools.email_tools.gmail_connector.analyze_email_attachment")
    def test_analyze_email_attachment_requires_attachment_selector(self, mock_analyze_attachment):
        mock_analyze_attachment.return_value = {"content_preview": "ok"}

        with self.assertRaises(ValueError):
            email_tools.analyze_email_attachment(
                {"message_id": "m1"},
                _build_context(),
            )

        email_tools.analyze_email_attachment(
            {"message_id": "m1", "attachment_id": "att-1", "max_chars": 900},
            _build_context(),
        )
        kwargs = mock_analyze_attachment.call_args.kwargs
        self.assertEqual(kwargs["message_id"], "m1")
        self.assertEqual(kwargs["attachment_id"], "att-1")
        self.assertEqual(kwargs["max_chars"], 900)

    def test_search_contacts_filters_by_query(self):
        csv_content = (
            "Nome, email, telefone, relacionamento\n"
            "Maria,maria@example.com,11999990000,amiga\n"
            "Joao,joao@example.com,21988887777,trabalho\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = os.path.join(temp_dir, "contacts.csv")
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(csv_content)

            with patch("assistant_connector.tools.contacts_tools.CONTACTS_CSV_PATH", csv_path):
                result = contacts_tools.search_contacts({"query": "maria"}, _build_context())

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["contacts"][0]["email"], "maria@example.com")

    def test_search_contacts_raises_for_missing_required_column(self):
        csv_content = "Nome,email,telefone\nMaria,maria@example.com,11999990000\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = os.path.join(temp_dir, "contacts.csv")
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(csv_content)

            with patch("assistant_connector.tools.contacts_tools.CONTACTS_CSV_PATH", csv_path):
                with self.assertRaises(ValueError):
                    contacts_tools.search_contacts({"query": "maria"}, _build_context())


if __name__ == "__main__":
    unittest.main()
