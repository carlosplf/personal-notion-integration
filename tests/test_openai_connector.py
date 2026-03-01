import unittest
import sys
import types

sys.modules.setdefault("openai", types.SimpleNamespace(ChatCompletion=None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
from openai_connector import openai_connector


class TestOpenAIConnector(unittest.TestCase):
    def test_build_message_contains_tasks(self):
        tasks = [
            {"name": "Task one"},
            {"name": "Task two"},
        ]
        message = openai_connector.build_message(tasks)
        self.assertIn("Task one", message)
        self.assertIn("Task two", message)
        self.assertIn("pure JSON format", message)


if __name__ == "__main__":
    unittest.main()
