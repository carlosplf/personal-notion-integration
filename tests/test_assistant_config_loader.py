import unittest
import tempfile
import json

from assistant_connector.config_loader import load_assistant_configuration


class TestAssistantConfigLoader(unittest.TestCase):
    def test_load_default_configuration_contains_personal_assistant(self):
        configuration = load_assistant_configuration()
        agent = configuration.get_agent("personal_assistant")
        self.assertEqual(agent.agent_id, "personal_assistant")
        self.assertIn("list_available_tools", agent.tools)
        self.assertIn("list_calendar_events", agent.tools)
        self.assertIn("list_notion_notes", agent.tools)
        self.assertIn("create_notion_note", agent.tools)
        self.assertIn("edit_notion_item", agent.tools)
        self.assertIn("list_unpaid_monthly_bills", agent.tools)
        self.assertIn("mark_monthly_bill_as_paid", agent.tools)
        self.assertIn("analyze_monthly_bills", agent.tools)
        self.assertIn("list_tech_news", agent.tools)
        self.assertIn("search_emails", agent.tools)
        self.assertIn("read_email", agent.tools)
        self.assertIn("search_email_attachments", agent.tools)
        self.assertIn("analyze_email_attachment", agent.tools)

    def test_write_tools_flagged_as_write_operations(self):
        configuration = load_assistant_configuration()
        self.assertTrue(configuration.tools["create_notion_task"].write_operation)
        self.assertTrue(configuration.tools["create_notion_note"].write_operation)
        self.assertTrue(configuration.tools["edit_notion_item"].write_operation)
        self.assertTrue(configuration.tools["mark_monthly_bill_as_paid"].write_operation)
        self.assertTrue(configuration.tools["create_calendar_event"].write_operation)
        self.assertTrue(configuration.tools["send_email"].write_operation)

    def test_duplicate_tool_names_raise_error(self):
        config = {
            "tools": [
                {"name": "tool_a", "description": "d", "handler": "assistant_connector.tools.meta_tools:list_available_tools"},
                {"name": "tool_a", "description": "d2", "handler": "assistant_connector.tools.meta_tools:list_available_agents"},
            ],
            "agents": [
                {"id": "agent_a", "description": "a", "system_prompt": "p", "tools": ["tool_a"]}
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=True, encoding="utf-8") as temp_config:
            json.dump(config, temp_config)
            temp_config.flush()
            with self.assertRaises(ValueError):
                load_assistant_configuration(temp_config.name)

    def test_unknown_tool_reference_raises_error(self):
        config = {
            "tools": [
                {"name": "tool_a", "description": "d", "handler": "assistant_connector.tools.meta_tools:list_available_tools"}
            ],
            "agents": [
                {"id": "agent_a", "description": "a", "system_prompt": "p", "tools": ["tool_missing"]}
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=True, encoding="utf-8") as temp_config:
            json.dump(config, temp_config)
            temp_config.flush()
            with self.assertRaises(ValueError):
                load_assistant_configuration(temp_config.name)

    def test_invalid_limits_raise_error(self):
        config = {
            "tools": [
                {"name": "tool_a", "description": "d", "handler": "assistant_connector.tools.meta_tools:list_available_tools"}
            ],
            "agents": [
                {
                    "id": "agent_a",
                    "description": "a",
                    "system_prompt": "p",
                    "tools": ["tool_a"],
                    "max_tool_rounds": 0,
                }
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=True, encoding="utf-8") as temp_config:
            json.dump(config, temp_config)
            temp_config.flush()
            with self.assertRaises(ValueError):
                load_assistant_configuration(temp_config.name)

    def test_duplicate_agent_ids_raise_error(self):
        config = {
            "tools": [
                {"name": "tool_a", "description": "d", "handler": "assistant_connector.tools.meta_tools:list_available_tools"}
            ],
            "agents": [
                {"id": "agent_a", "description": "a1", "system_prompt": "p", "tools": ["tool_a"]},
                {"id": "agent_a", "description": "a2", "system_prompt": "p", "tools": ["tool_a"]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=True, encoding="utf-8") as temp_config:
            json.dump(config, temp_config)
            temp_config.flush()
            with self.assertRaises(ValueError):
                load_assistant_configuration(temp_config.name)


if __name__ == "__main__":
    unittest.main()
