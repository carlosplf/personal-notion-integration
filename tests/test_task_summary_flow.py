import unittest
from unittest.mock import patch

from task_summary_flow import collect_tasks_and_summary


class TestTaskSummaryFlow(unittest.TestCase):
    @patch("task_summary_flow.llm_api.call_openai_assistant")
    @patch("task_summary_flow.notion_connector.collect_tasks_from_control_panel")
    def test_collect_tasks_and_summary_uses_connectors(self, mock_collect, mock_openai):
        logger = _MockLogger()
        tasks = [{"name": "Task 1", "deadline": "2026-01-01", "project": "X", "tags": ["FAST"]}]
        mock_collect.return_value = tasks
        mock_openai.return_value = "Summary"

        returned_tasks, summary = collect_tasks_and_summary(logger, n_days=2)

        self.assertEqual(returned_tasks, tasks)
        self.assertEqual(summary, "Summary")
        mock_collect.assert_called_once_with(n_days=2, project_logger=logger)
        mock_openai.assert_called_once_with(tasks, logger)


class _MockLogger:
    def info(self, *_args, **_kwargs):
        return None
