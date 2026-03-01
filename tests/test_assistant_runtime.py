import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from assistant_connector.memory_store import ConversationMemoryStore
from assistant_connector.models import AgentDefinition, ToolDefinition
from assistant_connector.runtime import AssistantRuntime
from assistant_connector.tool_registry import ToolRegistry


WRITE_TOOL_CALL_COUNT = 0


def _write_tool(_arguments, _context):
    global WRITE_TOOL_CALL_COUNT
    WRITE_TOOL_CALL_COUNT += 1
    return {"ok": True}


def _raising_tool(_arguments, _context):
    raise RuntimeError("tool exploded")


def _non_dict_tool(_arguments, _context):
    return "invalid"


def _large_payload_tool(_arguments, _context):
    return {"content": "x" * 5000}


class _FakeLogger:
    def exception(self, *_args, **_kwargs):
        return None


class _FakeResponsesAPI:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._payloads:
            raise AssertionError("Unexpected OpenAI call without queued payload")
        return self._payloads.pop(0)


class _FakeOpenAIClient:
    def __init__(self, payloads):
        self.responses = _FakeResponsesAPI(payloads)


class TestAssistantRuntime(unittest.TestCase):
    def _build_runtime(
        self,
        *,
        temp_dir,
        payloads,
        tool_definitions,
        tool_names,
        max_tool_rounds=3,
        memory_window=20,
        max_history_chars=12000,
        max_tool_output_chars=8000,
        agent_memory_text="",
        user_memories=None,
    ):
        return AssistantRuntime(
            agent=AgentDefinition(
                agent_id="personal_assistant",
                description="assistant",
                model="gpt-4.1-mini",
                system_prompt="prompt",
                tools=tool_names,
                max_tool_rounds=max_tool_rounds,
                memory_window=memory_window,
            ),
            tool_registry=ToolRegistry(tool_definitions),
            memory_store=ConversationMemoryStore(os.path.join(temp_dir, "assistant.sqlite3")),
            project_logger=_FakeLogger(),
            available_agents=[{"id": "personal_assistant", "description": "assistant", "model": "gpt-4.1-mini"}],
            max_history_chars=max_history_chars,
            max_tool_output_chars=max_tool_output_chars,
            agent_memory_text=agent_memory_text,
            user_memories=user_memories,
            openai_client=_FakeOpenAIClient(payloads),
        )

    def test_runtime_executes_tool_and_returns_final_message(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "list_available_tools",
                        "arguments": "{}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Aqui estão as tools disponíveis.",
            },
        ]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )

            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="quais tools você tem?",
            )

            self.assertEqual(answer, "Aqui estão as tools disponíveis.")
            history = runtime._memory_store.get_recent_messages("guild:channel:user", 10)
            self.assertEqual(history[0]["role"], "user")
            self.assertEqual(history[1]["role"], "assistant")

    def test_runtime_returns_direct_output_text_without_tool_calls(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "Resposta direta"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        self.assertEqual(answer, "Resposta direta")

    def test_runtime_injects_agent_and_user_memories(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "Resposta direta"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
                agent_memory_text="agent-memory-style",
                user_memories={"about-me.md": "Usuário focado em trabalho e família"},
            )
            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="Me lembre das prioridades da família",
            )

        first_call_input = runtime._openai_client.responses.calls[0]["input"]
        system_messages = [msg["content"] for msg in first_call_input if msg["role"] == "system"]
        self.assertTrue(any("agent-memory-style" in content for content in system_messages))
        self.assertTrue(any("família" in content for content in system_messages))

    def test_runtime_rejects_empty_message(self):
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=[],
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            with self.assertRaises(ValueError):
                runtime.process_user_message(
                    session_id="guild:channel:user",
                    user_id="user",
                    channel_id="channel",
                    guild_id="guild",
                    message="   ",
                )

    def test_runtime_blocks_write_tool_without_confirmation(self):
        global WRITE_TOOL_CALL_COUNT
        WRITE_TOOL_CALL_COUNT = 0

        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "dangerous_write_tool",
                        "arguments": "{\"task_name\":\"Nova tarefa\"}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Confirmação necessária.",
            },
        ]
        tool_definitions = {
            "dangerous_write_tool": ToolDefinition(
                name="dangerous_write_tool",
                description="Cria dado externo",
                input_schema={"type": "object", "properties": {"task_name": {"type": "string"}}},
                handler="tests.test_assistant_runtime:_write_tool",
                write_operation=True,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["dangerous_write_tool"],
            )

            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="crie a tarefa agora",
            )

        self.assertEqual(answer, "Confirmação necessária.")
        self.assertEqual(WRITE_TOOL_CALL_COUNT, 0)
        self.assertIn("confirmation_required", runtime._openai_client.responses.calls[1]["input"][0]["output"])

    def test_runtime_executes_write_tool_with_confirmation(self):
        global WRITE_TOOL_CALL_COUNT
        WRITE_TOOL_CALL_COUNT = 0

        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "dangerous_write_tool",
                        "arguments": "{\"task_name\":\"Nova tarefa\",\"confirmed\":true}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Tarefa criada.",
            },
        ]
        tool_definitions = {
            "dangerous_write_tool": ToolDefinition(
                name="dangerous_write_tool",
                description="Cria dado externo",
                input_schema={"type": "object", "properties": {"task_name": {"type": "string"}}},
                handler="tests.test_assistant_runtime:_write_tool",
                write_operation=True,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["dangerous_write_tool"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="crie a tarefa com confirmação",
            )

        self.assertEqual(answer, "Tarefa criada.")
        self.assertEqual(WRITE_TOOL_CALL_COUNT, 1)

    def test_runtime_handles_invalid_tool_arguments_json(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "list_available_tools",
                        "arguments": "{invalid",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Argumento inválido tratado.",
            },
        ]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="teste",
            )

            self.assertEqual(answer, "Argumento inválido tratado.")
            self.assertIn("invalid_tool_arguments", runtime._openai_client.responses.calls[1]["input"][0]["output"])

            with sqlite3.connect(runtime._memory_store.db_path) as connection:
                row = connection.execute(
                    "SELECT arguments_json FROM tool_calls ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertIn("_raw_arguments", row[0])

    def test_runtime_reports_tool_execution_failure(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "failing_tool",
                        "arguments": "{}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Erro tratado.",
            },
        ]
        tool_definitions = {
            "failing_tool": ToolDefinition(
                name="failing_tool",
                description="Falha sempre",
                input_schema={"type": "object", "properties": {}},
                handler="tests.test_assistant_runtime:_raising_tool",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["failing_tool"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="teste",
            )

        self.assertEqual(answer, "Erro tratado.")
        self.assertIn("tool_execution_failed", runtime._openai_client.responses.calls[1]["input"][0]["output"])

    def test_runtime_reports_non_dict_tool_response(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "non_dict_tool",
                        "arguments": "{}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "Erro tratado.",
            },
        ]
        tool_definitions = {
            "non_dict_tool": ToolDefinition(
                name="non_dict_tool",
                description="Retorno inválido",
                input_schema={"type": "object", "properties": {}},
                handler="tests.test_assistant_runtime:_non_dict_tool",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["non_dict_tool"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="teste",
            )

        self.assertEqual(answer, "Erro tratado.")
        self.assertIn("tool_execution_failed", runtime._openai_client.responses.calls[1]["input"][0]["output"])

    def test_runtime_uses_content_text_when_output_text_missing(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Resposta via content"}],
                    }
                ],
                "output_text": "",
            }
        ]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        self.assertEqual(answer, "Resposta via content")

    def test_runtime_uses_placeholder_call_id_when_missing(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "list_available_tools",
                        "arguments": "{}",
                        "call_id": "",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "ok",
            },
        ]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        self.assertTrue(
            runtime._openai_client.responses.calls[1]["input"][0]["call_id"].startswith(
                "missing-call-id-list_available_tools"
            )
        )

    def test_runtime_returns_fallback_after_max_tool_rounds(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {"type": "function_call", "name": "list_available_tools", "arguments": "{}", "call_id": "call-1"}
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [
                    {"type": "function_call", "name": "list_available_tools", "arguments": "{}", "call_id": "call-2"}
                ],
                "output_text": "",
            },
            {
                "id": "resp-3",
                "output": [
                    {"type": "function_call", "name": "list_available_tools", "arguments": "{}", "call_id": "call-3"}
                ],
                "output_text": "",
            },
        ]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
                max_tool_rounds=2,
            )
            answer = runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        self.assertIn("Não consegui concluir", answer)

    def test_runtime_respects_memory_window(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "ok"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
                memory_window=2,
            )
            runtime._memory_store.append_message("guild:channel:user", "user", "msg-1")
            runtime._memory_store.append_message("guild:channel:user", "assistant", "msg-2")
            runtime._memory_store.append_message("guild:channel:user", "user", "msg-3")

            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="msg-4",
            )

        sent_input = runtime._openai_client.responses.calls[0]["input"]
        self.assertEqual(len(sent_input), 3)
        self.assertEqual(sent_input[-2]["content"], "msg-3")
        self.assertEqual(sent_input[-1]["content"], "msg-4")

    def test_runtime_limits_history_by_char_budget(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "ok"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
                memory_window=10,
                max_history_chars=1000,
            )
            runtime._memory_store.append_message("guild:channel:user", "user", "x" * 600)
            runtime._memory_store.append_message("guild:channel:user", "assistant", "y" * 600)

            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="z" * 600,
            )

        sent_input = runtime._openai_client.responses.calls[0]["input"]
        self.assertEqual(len(sent_input), 2)
        self.assertEqual(sent_input[-1]["content"], "z" * 600)

    def test_runtime_truncates_large_tool_output_sent_to_llm(self):
        payloads = [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "name": "large_tool",
                        "arguments": "{}",
                        "call_id": "call-1",
                    }
                ],
                "output_text": "",
            },
            {
                "id": "resp-2",
                "output": [],
                "output_text": "ok",
            },
        ]
        tool_definitions = {
            "large_tool": ToolDefinition(
                name="large_tool",
                description="Retorna payload grande",
                input_schema={"type": "object", "properties": {}},
                handler="tests.test_assistant_runtime:_large_payload_tool",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["large_tool"],
                max_tool_output_chars=500,
            )
            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="teste",
            )

        output_payload = runtime._openai_client.responses.calls[1]["input"][0]["output"]
        self.assertIn('"truncated": true', output_payload.lower())

    def test_runtime_injects_markdown_response_guidelines(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "ok"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        system_message = runtime._openai_client.responses.calls[0]["input"][0]["content"]
        self.assertIn("Sempre responda em Markdown", system_message)

    def test_runtime_injects_email_style_preferences_when_available(self):
        payloads = [{"id": "resp-1", "output": [], "output_text": "ok"}]
        tool_definitions = {
            "list_available_tools": ToolDefinition(
                name="list_available_tools",
                description="Lista tools",
                input_schema={"type": "object", "properties": {}},
                handler="assistant_connector.tools.meta_tools:list_available_tools",
                write_operation=False,
            )
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "EMAIL_ASSISTANT_TONE": "amigável e direto",
                "EMAIL_ASSISTANT_SIGNATURE": "Carlos",
                "EMAIL_ASSISTANT_STYLE_GUIDE": "Use bullets",
            },
            clear=False,
        ):
            runtime = self._build_runtime(
                temp_dir=temp_dir,
                payloads=payloads,
                tool_definitions=tool_definitions,
                tool_names=["list_available_tools"],
            )
            runtime.process_user_message(
                session_id="guild:channel:user",
                user_id="user",
                channel_id="channel",
                guild_id="guild",
                message="oi",
            )

        system_message = runtime._openai_client.responses.calls[0]["input"][0]["content"]
        self.assertIn("Tom de voz: amigável e direto", system_message)
        self.assertIn("Assinatura padrão:", system_message)
        self.assertIn("destinatário tiver sido informado explicitamente", system_message)


if __name__ == "__main__":
    unittest.main()
