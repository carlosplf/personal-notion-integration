import unittest
import unittest.mock
import tempfile
import os
import datetime
import sys
import types

sys.modules.setdefault("openai", types.SimpleNamespace(ChatCompletion=None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
from openai_connector import llm_api


class _FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class _FakeResponsesAPI:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.output_text)


class _FakeOpenAIClient:
    def __init__(self, output_text, transcript_text="transcript"):
        self.responses = _FakeResponsesAPI(output_text)
        self.audio = types.SimpleNamespace(
            transcriptions=types.SimpleNamespace(
                calls=[],
                create=self._create_transcription,
            )
        )
        self._transcript_text = transcript_text

    def _create_transcription(self, **kwargs):
        self.audio.transcriptions.calls.append(kwargs)
        return types.SimpleNamespace(text=self._transcript_text)


class TestOpenAIConnector(unittest.TestCase):
    def test_build_message_contains_tasks(self):
        tasks = [
            {"name": "Task one", "project": "Pessoal", "deadline": "2026-03-01", "tags": ["FAST"]},
            {"name": "Task two", "project": "Trabalho", "deadline": "2026-03-02", "tags": ["TAKES TIME"]},
        ]
        message = llm_api.build_message(tasks)
        self.assertIn("Task one", message)
        self.assertIn("Task two", message)
        self.assertIn("Não responder em JSON", message)
        self.assertIn("Formato obrigatório da resposta (Markdown)", message)
        self.assertIn("tags: FAST", message)
        self.assertIn("projeto: Pessoal", message)
        self.assertIn("status_prazo:", message)

    def test_build_message_uses_template_when_prompt_file_missing(self):
        tasks = [{"name": "Task one", "project": "Pessoal", "deadline": "2026-03-01", "tags": ["FUP"]}]

        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = f"{temp_dir}/prompt_template.txt"
            with open(template_path, "w", encoding="utf-8") as prompt_file:
                prompt_file.write("Template prompt line")

            with unittest.mock.patch.object(
                llm_api, "PROMPT_FILE_PATH", f"{temp_dir}/missing_prompt.txt"
            ), unittest.mock.patch.object(
                llm_api, "PROMPT_TEMPLATE_FILE_PATH", template_path
            ):
                message = llm_api.build_message(tasks)

        self.assertIn("Template prompt line", message)
        self.assertIn("Task one", message)

    def test_parse_add_task_output_parses_expected_fields(self):
        output = '{"task_name":"Enviar proposta","project":"Draiven","due_date":"2026-03-05","tags":["FAST","FUP"]}'
        parsed = llm_api.parse_add_task_output(output)
        self.assertEqual(parsed["task_name"], "Enviar proposta")
        self.assertEqual(parsed["project"], "Draiven")
        self.assertEqual(parsed["due_date"], "2026-03-05")
        self.assertEqual(parsed["tags"], ["FAST", "FUP"])

    def test_parse_add_task_output_filters_time_based_tags(self):
        output = '{"task_name":"Enviar proposta","project":"Draiven","due_date":"2026-03-05","tags":["amanhã","manhã","FAST"]}'
        parsed = llm_api.parse_add_task_output(output)
        self.assertEqual(parsed["tags"], ["FAST"])

    def test_parse_add_task_output_defaults_due_date_from_configured_timezone(self):
        output = '{"task_name":"Enviar proposta","project":"Draiven","tags":["FAST"]}'
        with unittest.mock.patch.object(llm_api, "today_iso_in_configured_timezone", return_value="2026-03-01"):
            parsed = llm_api.parse_add_task_output(output)
        self.assertEqual(parsed["due_date"], "2026-03-01")

    def test_build_overdue_label_uses_configured_today(self):
        with unittest.mock.patch.object(llm_api, "today_in_configured_timezone", return_value=datetime.date(2026, 3, 2)):
            self.assertEqual(llm_api._build_overdue_label("2026-03-01"), "ATRASADA")
            self.assertEqual(llm_api._build_overdue_label("2026-03-02"), "NO PRAZO")

    def test_build_calendar_events_prompt_contains_events(self):
        prompt = llm_api.build_calendar_events_prompt(
            [
                {
                    "summary": "Reunião com cliente",
                    "start": "2026-03-02T10:00:00Z",
                    "end": "2026-03-02T11:00:00Z",
                    "location": "Google Meet",
                }
            ]
        )
        self.assertIn("Agenda da semana", prompt)
        self.assertIn("Reunião com cliente", prompt)

    def test_parse_add_event_output_parses_expected_fields(self):
        output = (
            '{"summary":"Reunião de kickoff","start_datetime":"2026-03-06T10:00",'
            '"end_datetime":"2026-03-06T11:00","description":"Alinhamento inicial",'
            '"timezone":"America/Sao_Paulo"}'
        )
        parsed = llm_api.parse_add_event_output(output)
        self.assertEqual(parsed["summary"], "Reunião de kickoff")
        self.assertEqual(parsed["start_datetime"], "2026-03-06T10:00")
        self.assertEqual(parsed["end_datetime"], "2026-03-06T11:00")
        self.assertEqual(parsed["timezone"], "America/Sao_Paulo")

    def test_parse_add_note_output_parses_expected_fields(self):
        output = (
            '{"note_name":"Insight de onboarding","tag":"IDEA",'
            '"observations":"Criar checklist de kickoff","url":"https://example.com"}'
        )
        parsed = llm_api.parse_add_note_output(output)
        self.assertEqual(parsed["note_name"], "Insight de onboarding")
        self.assertEqual(parsed["tag"], "IDEA")
        self.assertEqual(parsed["observations"], "Criar checklist de kickoff")
        self.assertEqual(parsed["url"], "https://example.com")

    def test_parse_add_note_output_infers_tag_when_missing(self):
        output = '{"note_name":"Reunião com cliente","observations":"Alinhar próximos passos","url":""}'
        parsed = llm_api.parse_add_note_output(output)
        self.assertEqual(parsed["tag"], "MEETING")

    def test_event_parser_prompt_has_grammar_instruction(self):
        self.assertIn("Corrija erros gramaticais", llm_api.EVENT_PARSER_PROMPT)

    def test_get_llm_model_uses_env_value(self):
        with unittest.mock.patch.dict(os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False):
            self.assertEqual(llm_api._get_llm_model(), "gpt-5-mini")

    def test_call_openai_assistant_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient("Resumo")
        tasks = [{"name": "Task one", "project": "Pessoal", "deadline": "2026-03-01", "tags": ["FAST"]}]

        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            answer = llm_api.call_openai_assistant(tasks, project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))

        self.assertEqual(answer, "Resumo")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")

    def test_parse_add_task_input_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient(
            '{"task_name":"Enviar proposta","project":"Draiven","due_date":"2026-03-05","tags":["FAST"]}'
        )

        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            parsed = llm_api.parse_add_task_input("enviar proposta", project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))

        self.assertEqual(parsed["task_name"], "Enviar proposta")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")
        self.assertIn("Contexto temporal operacional do usuário", fake_client.responses.calls[0]["input"])

    def test_parse_add_task_input_includes_temporal_context(self):
        fake_client = _FakeOpenAIClient(
            '{"task_name":"Enviar proposta","project":"Draiven","due_date":"2026-03-05","tags":["FAST"]}'
        )
        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.object(
            llm_api,
            "build_time_context",
            return_value={
                "timezone_name": "America/Sao_Paulo",
                "local_now_iso": "2026-03-01T22:30:00-03:00",
                "local_date_iso": "2026-03-01",
                "local_utc_offset": "-03:00",
                "utc_now_iso": "2026-03-02T01:30:00Z",
                "utc_date_iso": "2026-03-02",
            },
        ):
            llm_api.parse_add_task_input(
                "enviar proposta amanhã",
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )
        prompt_input = fake_client.responses.calls[0]["input"]
        self.assertIn("Timezone: America/Sao_Paulo", prompt_input)
        self.assertIn("Data local atual: 2026-03-01", prompt_input)
        self.assertIn("interprete termos relativos de tempo", prompt_input)

    def test_parse_add_note_input_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient(
            '{"note_name":"Ideia","tag":"IDEA","observations":"Implementar rotina de notas","url":""}'
        )
        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            parsed = llm_api.parse_add_note_input("anotar ideia sobre rotina", project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))

        self.assertEqual(parsed["note_name"], "Ideia")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")

    def test_parse_add_event_output_uses_configured_timezone_when_missing(self):
        output = (
            '{"summary":"Reunião de kickoff","start_datetime":"2026-03-06T10:00",'
            '"end_datetime":"2026-03-06T11:00","description":"Alinhamento inicial"}'
        )
        with unittest.mock.patch.object(llm_api, "get_configured_timezone_name", return_value="America/Sao_Paulo"):
            parsed = llm_api.parse_add_event_output(output)
        self.assertEqual(parsed["timezone"], "America/Sao_Paulo")

    def test_transcribe_audio_input_uses_transcribe_model_from_env(self):
        fake_client = _FakeOpenAIClient("unused", transcript_text="texto transcrito")
        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"AUDIO_TRANSCRIBE_MODEL": "gpt-4o-mini-transcribe"}, clear=False
        ):
            transcript = llm_api.transcribe_audio_input(
                b"fake-audio-bytes",
                "audio.ogg",
                "audio/ogg",
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )
        self.assertEqual(transcript, "texto transcrito")
        self.assertEqual(fake_client.audio.transcriptions.calls[0]["model"], "gpt-4o-mini-transcribe")
        file_payload = fake_client.audio.transcriptions.calls[0]["file"]
        self.assertIsInstance(file_payload, tuple)
        self.assertEqual(file_payload[0], "audio.ogg")

    def test_transcribe_audio_input_rejects_empty_audio(self):
        with self.assertRaises(ValueError):
            llm_api.transcribe_audio_input(
                b"",
                "audio.ogg",
                "audio/ogg",
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )

    def test_summarize_calendar_events_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient("Resumo da agenda")
        events = [{"summary": "Reunião", "start": "2026-03-02T10:00:00Z", "end": "2026-03-02T11:00:00Z"}]

        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            summary = llm_api.summarize_calendar_events(events, project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))

        self.assertEqual(summary, "Resumo da agenda")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")

    def test_build_day_summary_prompt_contains_tasks_and_events(self):
        prompt = llm_api.build_day_summary_prompt(
            [{"name": "Enviar proposta", "project": "Draiven", "deadline": "2026-03-01T10:00:00", "tags": ["FAST"]}],
            [{"summary": "Daily", "start": "2026-03-01T11:00:00", "end": "2026-03-01T11:30:00", "location": "Meet"}],
        )
        self.assertIn("Resumo de hoje", prompt)
        self.assertIn("Enviar proposta", prompt)
        self.assertIn("Daily", prompt)

    def test_build_period_summary_prompt_for_week_contains_labels(self):
        prompt = llm_api.build_period_summary_prompt(
            "semana atual",
            [{"name": "Task week", "project": "Pessoal", "deadline": "2026-03-03", "tags": []}],
            [{"summary": "Evento week", "start": "2026-03-03T10:00:00", "end": "2026-03-03T11:00:00"}],
        )
        self.assertIn("Resumo da semana atual", prompt)
        self.assertIn("Tarefas da semana", prompt)
        self.assertIn("Agenda da semana", prompt)
        self.assertIn("Não liste todas as tarefas ou eventos individualmente", prompt)
        self.assertNotIn("**HH:MM ou Dia inteiro** — Tarefa (Projeto) [Tags]", prompt)

    def test_summarize_day_context_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient("## Resumo do dia")
        tasks = [{"name": "Task", "project": "Pessoal", "deadline": "2026-03-01T10:00:00", "tags": []}]
        events = [{"summary": "Evento", "start": "2026-03-01T12:00:00", "end": "2026-03-01T13:00:00"}]

        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            summary = llm_api.summarize_day_context(tasks, events, project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))

        self.assertEqual(summary, "## Resumo do dia")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")

    def test_summarize_day_context_returns_empty_day_message_without_llm_call(self):
        with unittest.mock.patch.object(llm_api, "_create_openai_client") as mocked_client:
            summary = llm_api.summarize_day_context([], [], project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None))
        self.assertIn("Sem tarefas e sem eventos para hoje", summary)
        mocked_client.assert_not_called()

    def test_summarize_period_context_uses_llm_model_from_env(self):
        fake_client = _FakeOpenAIClient("## Resumo de amanhã")
        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.dict(
            os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False
        ):
            summary = llm_api.summarize_period_context(
                "amanhã",
                [{"name": "Task", "project": "Pessoal", "deadline": "2026-03-02"}],
                [{"summary": "Evento", "start": "2026-03-02T12:00:00"}],
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )
        self.assertEqual(summary, "## Resumo de amanhã")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")

    def test_summarize_period_context_returns_empty_message_without_llm(self):
        with unittest.mock.patch.object(llm_api, "_create_openai_client") as mocked_client:
            summary = llm_api.summarize_period_context(
                "semana atual",
                [],
                [],
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )
        self.assertIn("Sem tarefas e sem eventos para esta semana", summary)
        mocked_client.assert_not_called()

    def test_parse_add_event_input_uses_default_timezone_and_llm_model(self):
        fake_client = _FakeOpenAIClient(
            '{"summary":"Kickoff","start_datetime":"2026-03-06T10:00","end_datetime":"2026-03-06T11:00","description":"","timezone":"America/Sao_Paulo"}'
        )
        with unittest.mock.patch.object(llm_api, "_create_openai_client", return_value=fake_client), unittest.mock.patch.object(
            llm_api, "_get_default_event_timezone", return_value="America/Sao_Paulo"
        ), unittest.mock.patch.dict(os.environ, {"LLM_MODEL": "gpt-5-mini"}, clear=False):
            parsed = llm_api.parse_add_event_input(
                "marcar kickoff amanhã às 10h",
                project_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None),
            )
        self.assertEqual(parsed["summary"], "Kickoff")
        self.assertEqual(fake_client.responses.calls[0]["model"], "gpt-5-mini")
        prompt_input = fake_client.responses.calls[0]["input"]
        self.assertIn("Default timezone para este usuário: America/Sao_Paulo.", prompt_input)
        self.assertIn("Input do usuário:\nmarcar kickoff amanhã às 10h", prompt_input)

    def test_parse_add_event_output_rejects_end_before_start(self):
        with self.assertRaises(ValueError):
            llm_api.parse_add_event_output(
                '{"summary":"Kickoff","start_datetime":"2026-03-06T11:00","end_datetime":"2026-03-06T10:00","description":"","timezone":"America/Sao_Paulo"}'
            )

    def test_extract_json_payload_reads_json_wrapped_in_text(self):
        payload = llm_api._extract_json_payload(
            "resposta:\n```json\n{\"task_name\":\"A\",\"project\":\"Pessoal\",\"due_date\":\"2026-03-01\",\"tags\":[]}\n```"
        )
        self.assertEqual(payload["task_name"], "A")

    def test_extract_json_payload_raises_when_json_missing(self):
        with self.assertRaises(ValueError):
            llm_api._extract_json_payload("sem json aqui")

    def test_infer_note_tag_covers_bug_and_fallback(self):
        self.assertEqual(llm_api._infer_note_tag("Erro crítico no deploy"), "BUG")
        self.assertEqual(llm_api._infer_note_tag("tema neutro sem palavras-chave"), "GENERAL")


if __name__ == "__main__":
    unittest.main()
