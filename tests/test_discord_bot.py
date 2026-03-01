import sys
import types
import unittest
import unittest.mock
import datetime

sys.modules.setdefault("discord", types.SimpleNamespace())
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

import discord_bot


class TestDiscordBot(unittest.TestCase):
    def test_build_tasks_response_contains_count_and_summary(self):
        tasks = [{"name": "Task one"}, {"name": "Task two"}]
        message = discord_bot.build_tasks_response(tasks, "Quick summary")
        self.assertIn("Tarefas encontradas: 2", message)
        self.assertIn("Quick summary", message)

    def test_build_tasks_response_is_truncated(self):
        tasks = [{"name": "Task one"}]
        long_summary = "a" * 5000
        message = discord_bot.build_tasks_response(tasks, long_summary)
        self.assertLessEqual(len(message), discord_bot.MAX_DISCORD_MESSAGE_LENGTH)
        self.assertTrue(message.endswith("..."))

    def test_build_error_response_is_truncated(self):
        long_error = "x" * 5000
        message = discord_bot.build_error_response(long_error)
        self.assertLessEqual(len(message), discord_bot.MAX_DISCORD_MESSAGE_LENGTH)
        self.assertIn("Failed to collect tasks", message)

    def test_build_add_task_success_response(self):
        message = discord_bot.build_add_task_success_response(
            {
                "task_name": "Enviar proposta",
                "project": "Draiven",
                "due_date": "2026-03-03",
                "tags": ["FAST", "FUP"],
            }
        )
        self.assertIn("Tarefa criada no Notion", message)
        self.assertIn("Draiven", message)
        self.assertIn("FAST, FUP", message)

    def test_build_calendar_response(self):
        message = discord_bot.build_calendar_response("Resumo da semana")
        self.assertIn("Agenda (7 dias)", message)
        self.assertIn("Resumo da semana", message)

    def test_build_add_event_success_response(self):
        message = discord_bot.build_add_event_success_response(
            {
                "summary": "Reunião de kickoff",
                "start": "2026-03-06T10:00:00",
                "end": "2026-03-06T11:00:00",
                "html_link": "https://calendar.google.com/event?id=1",
            }
        )
        self.assertIn("Evento criado no Google Calendar", message)
        self.assertIn("Reunião de kickoff", message)

    def test_build_add_note_success_response(self):
        message = discord_bot.build_add_note_success_response(
            {
                "note_name": "Idea backlog",
                "date": "2026-03-01",
                "tag": "IDEA",
                "url": "https://example.com",
            }
        )
        self.assertIn("Note created in Notion", message)
        self.assertIn("Idea backlog", message)
        self.assertIn("IDEA", message)

    def test_build_notes_response_contains_notes(self):
        message = discord_bot.build_notes_response(
            [
                {
                    "name": "Daily note",
                    "date": "2026-03-01",
                    "tags": ["GENERAL"],
                    "observations": "Follow up with team",
                    "url": "https://example.com",
                }
            ]
        )
        self.assertIn("Notes (-5 to +5 days)", message)
        self.assertIn("Daily note", message)
        self.assertIn("Follow up with team", message)

    def test_build_notes_response_empty(self):
        message = discord_bot.build_notes_response([])
        self.assertIn("No notes found for this period", message)

    def test_build_note_payload_from_input_preserves_markdown_body(self):
        markdown = "# Header\n\n- item 1\n- item 2\n**bold**"
        with unittest.mock.patch.object(
            discord_bot.llm_api,
            "parse_add_note_input",
            return_value={"note_name": "Parsed title", "tag": "IDEA", "url": "https://example.com"},
        ):
            payload = discord_bot.build_note_payload_from_input(markdown, project_logger=types.SimpleNamespace())

        self.assertEqual(payload["note_name"], "Parsed title")
        self.assertEqual(payload["tag"], "IDEA")
        self.assertEqual(payload["url"], "https://example.com")
        self.assertEqual(payload["observations"], markdown)

    def test_build_note_payload_from_input_falls_back_when_parser_fails(self):
        markdown = "# Minha nota\n\nconteudo"
        with unittest.mock.patch.object(discord_bot.llm_api, "parse_add_note_input", side_effect=RuntimeError("fail")):
            payload = discord_bot.build_note_payload_from_input(markdown, project_logger=types.SimpleNamespace())
        self.assertEqual(payload["note_name"], "Minha nota")
        self.assertEqual(payload["tag"], "GENERAL")
        self.assertEqual(payload["observations"], markdown)

    def test_is_authorized_discord_user_denies_when_unset(self):
        self.assertFalse(discord_bot._is_authorized_discord_user("123", ""))

    def test_is_authorized_discord_user_matches_only_allowed_id(self):
        self.assertTrue(discord_bot._is_authorized_discord_user("123", "123"))
        self.assertFalse(discord_bot._is_authorized_discord_user("999", "123"))

    def test_access_denied_message_is_defined(self):
        self.assertIn("Access denied", discord_bot.ACCESS_DENIED_MESSAGE)

    def test_is_audio_attachment_detects_content_type(self):
        attachment = types.SimpleNamespace(content_type="audio/ogg", filename="voice-message")
        self.assertTrue(discord_bot._is_audio_attachment(attachment))

    def test_is_audio_attachment_detects_extension(self):
        attachment = types.SimpleNamespace(content_type=None, filename="voice.ogg")
        self.assertTrue(discord_bot._is_audio_attachment(attachment))

    def test_select_audio_attachment_returns_first_audio(self):
        attachments = [
            types.SimpleNamespace(content_type="image/png", filename="image.png"),
            types.SimpleNamespace(content_type="", filename="voice.ogg"),
            types.SimpleNamespace(content_type="audio/wav", filename="voice2.wav"),
        ]
        selected = discord_bot._select_audio_attachment(attachments)
        self.assertEqual(selected.filename, "voice.ogg")

    def test_build_bot_response_truncates_long_text(self):
        message = discord_bot.build_bot_response("b" * 5000)
        self.assertLessEqual(len(message), discord_bot.MAX_DISCORD_MESSAGE_LENGTH)
        self.assertTrue(message.endswith("..."))

    def test_build_bot_response_wraps_plain_text_in_markdown(self):
        message = discord_bot.build_bot_response("Resposta simples")
        self.assertTrue(message.startswith("## Assistente pessoal"))
        self.assertIn("Resposta simples", message)

    def test_build_bot_response_preserves_markdown(self):
        markdown_answer = "## Resumo\n\n- Item 1"
        message = discord_bot.build_bot_response(markdown_answer)
        self.assertEqual(message, markdown_answer)

    def test_build_new_chat_response(self):
        message = discord_bot.build_new_chat_response()
        self.assertIn("Nova conversa iniciada", message)
        self.assertIn("Limpei o histórico", message)

    def test_is_dm_reset_shortcut_accepts_reset_and_new_chat(self):
        self.assertTrue(discord_bot._is_dm_reset_shortcut("/reset"))
        self.assertTrue(discord_bot._is_dm_reset_shortcut(" /new_chat "))

    def test_is_dm_reset_shortcut_rejects_other_messages(self):
        self.assertFalse(discord_bot._is_dm_reset_shortcut("reset"))
        self.assertFalse(discord_bot._is_dm_reset_shortcut("/reset agora"))

    def test_filter_tasks_for_today(self):
        today = datetime.date.today().isoformat()
        tasks = [
            {"name": "Hoje", "deadline": f"{today}T10:00:00", "project": "Pessoal"},
            {"name": "Outro dia", "deadline": "2099-12-31T09:00:00", "project": "Pessoal"},
        ]
        filtered = discord_bot.filter_tasks_for_today(tasks)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Hoje")

    def test_filter_events_for_today(self):
        today = datetime.date.today().isoformat()
        events = [
            {"summary": "Evento hoje", "start": f"{today}T09:00:00"},
            {"summary": "Evento futuro", "start": "2099-12-31T09:00:00"},
        ]
        filtered = discord_bot.filter_events_for_today(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["summary"], "Evento hoje")

    def test_filter_tasks_for_tomorrow(self):
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        tasks = [
            {"name": "Amanhã", "deadline": f"{tomorrow}T10:00:00", "project": "Pessoal"},
            {"name": "Hoje", "deadline": f"{datetime.date.today().isoformat()}T10:00:00", "project": "Pessoal"},
        ]
        filtered = discord_bot.filter_tasks_for_tomorrow(tasks)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Amanhã")

    def test_filter_events_for_tomorrow(self):
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        events = [
            {"summary": "Evento amanhã", "start": f"{tomorrow}T09:00:00"},
            {"summary": "Evento hoje", "start": f"{datetime.date.today().isoformat()}T09:00:00"},
        ]
        filtered = discord_bot.filter_events_for_tomorrow(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["summary"], "Evento amanhã")

    def test_filter_tasks_for_current_week(self):
        week_start, week_end = discord_bot._current_week_bounds()
        in_week = week_start.isoformat()
        out_week = (week_end + datetime.timedelta(days=7)).isoformat()
        tasks = [
            {"name": "Dentro", "deadline": f"{in_week}T10:00:00", "project": "Pessoal"},
            {"name": "Fora", "deadline": f"{out_week}T10:00:00", "project": "Pessoal"},
        ]
        filtered = discord_bot.filter_tasks_for_current_week(tasks)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Dentro")

    def test_filter_events_for_current_week(self):
        week_start, week_end = discord_bot._current_week_bounds()
        in_week = week_start.isoformat()
        out_week = (week_end + datetime.timedelta(days=7)).isoformat()
        events = [
            {"summary": "Dentro", "start": f"{in_week}T09:00:00"},
            {"summary": "Fora", "start": f"{out_week}T09:00:00"},
        ]
        filtered = discord_bot.filter_events_for_current_week(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["summary"], "Dentro")

    def test_current_week_bounds_on_sunday_starts_today(self):
        class _SundayDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 3, 1)

        with unittest.mock.patch.object(discord_bot.datetime, "date", _SundayDate):
            week_start, week_end = discord_bot._current_week_bounds()

        self.assertEqual(week_start.isoformat(), "2026-03-01")
        self.assertEqual(week_end.isoformat(), "2026-03-07")

    def test_build_day_response_contains_sections(self):
        response = discord_bot.build_day_response(
            [{"name": "Task A", "project": "Pessoal", "deadline": "2026-03-01T10:00:00"}],
            [{"summary": "Daily", "start": "2026-03-01T11:00:00", "location": "Meet"}],
        )
        self.assertIn("Resumo de hoje", response)
        self.assertIn("Tarefas do Notion", response)
        self.assertIn("Eventos da agenda", response)
        self.assertIn("Task A", response)
        self.assertIn("Daily", response)

    def test_build_day_response_with_empty_lists(self):
        response = discord_bot.build_day_response([], [])
        self.assertIn("Sem tarefas do Notion para hoje", response)
        self.assertIn("Sem eventos na agenda para hoje", response)


if __name__ == "__main__":
    unittest.main()
