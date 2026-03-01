import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_connector.service import AssistantService, create_assistant_service


class _FakeLogger:
    def exception(self, *_args, **_kwargs):
        return None


class _FakeRuntime:
    def __init__(self):
        self.calls = []

    def process_user_message(self, **kwargs):
        self.calls.append(kwargs)
        return "ok"


class _FakeResponses:
    def __init__(self, payloads):
        self._payloads = list(payloads)

    def create(self, **_kwargs):
        return self._payloads.pop(0)


class _FakeOpenAIClient:
    def __init__(self, payloads):
        self.responses = _FakeResponses(payloads)


class TestAssistantService(unittest.TestCase):
    def test_build_session_id_uses_dm_when_guild_missing(self):
        session_id = AssistantService.build_session_id(
            user_id="1",
            channel_id="2",
            guild_id=None,
        )
        self.assertEqual(session_id, "dm:2:1")

    def test_chat_delegates_to_runtime_with_computed_session_id(self):
        runtime = _FakeRuntime()
        service = AssistantService(runtime=runtime)

        result = service.chat(
            user_id="10",
            channel_id="20",
            guild_id="30",
            message="oi",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(runtime.calls[0]["session_id"], "30:20:10")
        self.assertEqual(runtime.calls[0]["message"], "oi")

    def test_create_assistant_service_applies_llm_model_env_override(self):
        config = {
            "tools": [
                {
                    "name": "list_available_tools",
                    "description": "Lista tools",
                    "handler": "assistant_connector.tools.meta_tools:list_available_tools",
                    "write_operation": False,
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                }
            ],
            "agents": [
                {
                    "id": "custom_agent",
                    "description": "Agent de teste",
                    "model": "legacy-model",
                    "system_prompt": "Teste",
                    "tools": ["list_available_tools"],
                }
            ],
        }

        payloads = [{"id": "resp-1", "output": [], "output_text": "Olá"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "agents.json")
            memory_path = os.path.join(temp_dir, "memory.sqlite3")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file)

            with patch.dict(
                os.environ,
                {
                    "LLM_MODEL": "gpt-custom-model",
                    "ASSISTANT_MEMORY_PATH": memory_path,
                },
                clear=False,
            ):
                service = create_assistant_service(
                    project_logger=_FakeLogger(),
                    config_path=config_path,
                    agent_id="custom_agent",
                    openai_client=_FakeOpenAIClient(payloads),
                )
                answer = service.chat(
                    user_id="user-1",
                    channel_id="channel-1",
                    guild_id="guild-1",
                    message="oi",
                )

                self.assertEqual(answer, "Olá")
                self.assertEqual(service._runtime._agent.model, "gpt-custom-model")
                self.assertEqual(service._runtime._available_agents[0]["model"], "gpt-custom-model")
                self.assertTrue(os.path.exists(memory_path))

    def test_create_assistant_service_applies_runtime_limits_from_env(self):
        config = {
            "tools": [
                {
                    "name": "list_available_tools",
                    "description": "Lista tools",
                    "handler": "assistant_connector.tools.meta_tools:list_available_tools",
                    "write_operation": False,
                    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            ],
            "agents": [
                {
                    "id": "custom_agent",
                    "description": "Agent de teste",
                    "model": "legacy-model",
                    "system_prompt": "Teste",
                    "tools": ["list_available_tools"],
                }
            ],
        }
        payloads = [{"id": "resp-1", "output": [], "output_text": "Olá"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "agents.json")
            memory_path = os.path.join(temp_dir, "memory.sqlite3")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file)

            with patch.dict(
                os.environ,
                {
                    "ASSISTANT_MAX_MESSAGES_PER_SESSION": "10",
                    "ASSISTANT_MAX_TOOL_CALLS_PER_SESSION": "11",
                    "ASSISTANT_MAX_STORED_MESSAGE_CHARS": "1200",
                    "ASSISTANT_MAX_STORED_TOOL_PAYLOAD_CHARS": "2200",
                    "ASSISTANT_MAX_HISTORY_CHARS": "3200",
                    "ASSISTANT_MAX_TOOL_OUTPUT_CHARS": "4200",
                },
                clear=False,
            ):
                service = create_assistant_service(
                    project_logger=_FakeLogger(),
                    config_path=config_path,
                    memory_path=memory_path,
                    agent_id="custom_agent",
                    openai_client=_FakeOpenAIClient(payloads),
                )

        self.assertEqual(service._runtime._memory_store._max_messages_per_session, 10)
        self.assertEqual(service._runtime._memory_store._max_tool_calls_per_session, 11)
        self.assertEqual(service._runtime._memory_store._max_message_chars, 1200)
        self.assertEqual(service._runtime._memory_store._max_tool_payload_chars, 2200)
        self.assertEqual(service._runtime._max_history_chars, 3200)
        self.assertEqual(service._runtime._max_tool_output_chars, 4200)


if __name__ == "__main__":
    unittest.main()
