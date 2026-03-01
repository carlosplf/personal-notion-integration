from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from assistant_connector.memory_store import ConversationMemoryStore
from assistant_connector.models import AgentDefinition, ToolExecutionContext
from assistant_connector.tool_registry import ToolRegistry


class AssistantRuntime:
    def __init__(
        self,
        *,
        agent: AgentDefinition,
        tool_registry: ToolRegistry,
        memory_store: ConversationMemoryStore,
        project_logger,
        available_agents: list[dict[str, str]],
        max_history_chars: int = 12000,
        max_tool_output_chars: int = 8000,
        openai_client=None,
    ):
        self._agent = agent
        self._tool_registry = tool_registry
        self._memory_store = memory_store
        self._project_logger = project_logger
        self._available_agents = available_agents
        self._max_history_chars = max(1000, int(max_history_chars))
        self._max_tool_output_chars = max(1000, int(max_tool_output_chars))
        self._openai_client = openai_client or self._create_openai_client()

    def process_user_message(
        self,
        *,
        session_id: str,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
        message: str,
    ) -> str:
        clean_message = str(message).strip()
        if not clean_message:
            raise ValueError("User message cannot be empty")

        self._memory_store.append_message(session_id, "user", clean_message)
        history = self._memory_store.get_recent_messages(
            session_id=session_id,
            limit=max(self._agent.memory_window, 1),
        )
        history = self._trim_history_by_chars(history)

        available_tools = self._tool_registry.describe_tools(self._agent.tools)
        context = ToolExecutionContext(
            session_id=session_id,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            project_logger=self._project_logger,
            agent=self._agent,
            available_tools=available_tools,
            available_agents=self._available_agents,
        )
        openai_tools = self._tool_registry.get_openai_tools(self._agent.tools)
        response = self._openai_client.responses.create(
            model=self._agent.model,
            input=self._build_input_messages(history, available_tools),
            tools=openai_tools,
        )

        for _ in range(max(self._agent.max_tool_rounds, 1)):
            function_calls = self._extract_function_calls(response)
            if not function_calls:
                final_text = self._extract_text_response(response)
                self._memory_store.append_message(session_id, "assistant", final_text)
                return final_text

            tool_outputs = []
            for function_call in function_calls:
                tool_name = function_call["name"]
                raw_arguments = function_call["arguments"]
                try:
                    arguments = self._parse_tool_arguments(raw_arguments)
                except ValueError as error:
                    arguments = {"_raw_arguments": str(raw_arguments)}
                    result = {
                        "error": "invalid_tool_arguments",
                        "tool_name": tool_name,
                        "details": str(error),
                    }
                else:
                    result = self._execute_tool_call(tool_name, arguments, context)
                self._memory_store.log_tool_call(
                    session_id=session_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                )
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": function_call["call_id"] or f"missing-call-id-{tool_name}",
                        "output": self._serialize_tool_output(result),
                    }
                )

            response = self._openai_client.responses.create(
                model=self._agent.model,
                previous_response_id=self._item_get(response, "id"),
                input=tool_outputs,
                tools=openai_tools,
            )

        fallback_message = (
            "Não consegui concluir com segurança agora. "
            "Tente reformular ou dividir em passos menores."
        )
        self._memory_store.append_message(session_id, "assistant", fallback_message)
        return fallback_message

    def _build_input_messages(
        self,
        history: list[dict[str, str]],
        available_tools: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        tools_lines = "\n".join(
            f"- {tool['name']}: {tool['description']}" for tool in available_tools
        )
        system_message = (
            f"{self._agent.system_prompt}\n\n"
            "Ferramentas atualmente habilitadas:\n"
            f"{tools_lines}\n\n"
            "Se o usuário perguntar quais tools existem, responda com os nomes das tools.\n\n"
            "Formato obrigatório para resposta no Discord:\n"
            "- Sempre responda em Markdown.\n"
            "- Use título H2 no início (## ...).\n"
            "- Use listas para itens múltiplos e destaque com negrito quando útil.\n"
            "- Nunca responda em JSON bruto.\n\n"
            f"{self._build_email_style_guidance()}"
        )
        return [{"role": "system", "content": system_message}] + [
            {"role": message["role"], "content": message["content"]}
            for message in history
        ]

    def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        tool_definition = self._tool_registry.get_tool_definition(tool_name)
        if tool_definition.write_operation and not bool(arguments.get("confirmed", False)):
            return {
                "error": "confirmation_required",
                "message": (
                    "Esta ação altera dados externos. "
                    "Peça confirmação explícita do usuário e use confirmed=true."
                ),
            }
        try:
            return self._tool_registry.execute_tool(tool_name, arguments, context)
        except Exception as error:
            context.project_logger.exception("Tool execution failed: %s", tool_name)
            return {
                "error": "tool_execution_failed",
                "tool_name": tool_name,
                "details": str(error),
            }

    def _extract_function_calls(self, response) -> list[dict[str, str]]:
        output_items = self._item_get(response, "output", []) or []
        calls = []
        for item in output_items:
            if self._item_get(item, "type") != "function_call":
                continue
            calls.append(
                {
                    "name": self._item_get(item, "name", ""),
                    "arguments": self._item_get(item, "arguments", "{}"),
                    "call_id": self._item_get(item, "call_id", ""),
                }
            )
        return calls

    def _extract_text_response(self, response) -> str:
        output_text = self._item_get(response, "output_text")
        if output_text:
            return output_text

        output_items = self._item_get(response, "output", []) or []
        for item in output_items:
            if self._item_get(item, "type") != "message":
                continue
            content_items = self._item_get(item, "content", []) or []
            for content_item in content_items:
                content_type = self._item_get(content_item, "type")
                if content_type in ("output_text", "text"):
                    text = self._item_get(content_item, "text")
                    if text:
                        return str(text)

        return "Desculpe, não consegui gerar uma resposta."

    def _parse_tool_arguments(self, raw_arguments) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        text = str(raw_arguments or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Tool arguments are not valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return payload

    def _trim_history_by_chars(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        if not history:
            return history

        selected = []
        total_chars = 0
        for message in reversed(history):
            content = str(message.get("content", ""))
            message_size = len(content)
            if selected and (total_chars + message_size) > self._max_history_chars:
                break
            if not selected and message_size > self._max_history_chars:
                truncated_content = self._truncate_text(content, self._max_history_chars)
                selected.append(
                    {
                        "role": message.get("role", "user"),
                        "content": truncated_content,
                    }
                )
                break
            selected.append(
                {
                    "role": message.get("role", "user"),
                    "content": content,
                }
            )
            total_chars += message_size
        selected.reverse()
        return selected

    def _serialize_tool_output(self, result: dict[str, Any]) -> str:
        payload_json = json.dumps(result, ensure_ascii=False)
        if len(payload_json) <= self._max_tool_output_chars:
            return payload_json
        preview_limit = max(200, self._max_tool_output_chars - 200)
        truncated = {
            "truncated": True,
            "limit_chars": self._max_tool_output_chars,
            "preview": payload_json[:preview_limit],
        }
        return json.dumps(truncated, ensure_ascii=False)

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        marker = "... [truncated]"
        if limit <= len(marker):
            return marker[:limit]
        return f"{text[: limit - len(marker)]}{marker}"

    @staticmethod
    def _build_email_style_guidance() -> str:
        tone = str(os.getenv("EMAIL_ASSISTANT_TONE", "")).strip()
        signature = str(os.getenv("EMAIL_ASSISTANT_SIGNATURE", "")).strip()
        style_guide = str(os.getenv("EMAIL_ASSISTANT_STYLE_GUIDE", "")).strip()
        if not any((tone, signature, style_guide)):
            return (
                "Preferências de email: use tom profissional, claro e cordial.\n"
                "Ao usar send_email, defina o assunto você mesmo e só envie se o destinatário "
                "tiver sido informado explicitamente pelo usuário."
            )

        lines = ["Preferências de email do usuário:"]
        if tone:
            lines.append(f"- Tom de voz: {tone}")
        if style_guide:
            lines.append(f"- Guia de estilo: {style_guide}")
        if signature:
            lines.append(f"- Assinatura padrão:\n{signature}")
        lines.append(
            "- Ao usar send_email, defina o assunto você mesmo e só envie se o destinatário "
            "tiver sido informado explicitamente pelo usuário."
        )
        return "\n".join(lines)

    @staticmethod
    def _item_get(payload, key: str, default=None):
        if isinstance(payload, dict):
            return payload.get(key, default)
        return getattr(payload, key, default)

    @staticmethod
    def _create_openai_client():
        load_dotenv()
        openai_api_key = os.getenv("OPENAI_KEY")
        if not openai_api_key:
            raise ValueError("Missing required environment variable: OPENAI_KEY")
        import openai  # local import to keep module import lightweight for tests

        return openai.OpenAI(api_key=openai_api_key)
