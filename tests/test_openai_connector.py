import unittest
import tempfile
import sys
import types

sys.modules.setdefault("openai", types.SimpleNamespace(ChatCompletion=None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
from openai_connector import llm_api


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


if __name__ == "__main__":
    unittest.main()
