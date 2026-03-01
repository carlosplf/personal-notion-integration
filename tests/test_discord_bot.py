import sys
import types
import unittest

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


if __name__ == "__main__":
    unittest.main()
