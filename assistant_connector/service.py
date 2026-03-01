from __future__ import annotations

from dataclasses import replace
import os

from dotenv import load_dotenv

from assistant_connector.config_loader import load_assistant_configuration
from assistant_connector.memory_store import ConversationMemoryStore
from assistant_connector.runtime import AssistantRuntime
from assistant_connector.tool_registry import ToolRegistry


class AssistantService:
    def __init__(self, runtime: AssistantRuntime):
        self._runtime = runtime

    def chat(
        self,
        *,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
        message: str,
    ) -> str:
        session_id = self.build_session_id(
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
        )
        return self._runtime.process_user_message(
            session_id=session_id,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            message=message,
        )

    @staticmethod
    def build_session_id(*, user_id: str, channel_id: str, guild_id: str | None) -> str:
        return f"{guild_id or 'dm'}:{channel_id}:{user_id}"


def create_assistant_service(
    *,
    project_logger,
    config_path: str | None = None,
    memory_path: str | None = None,
    agent_id: str | None = None,
    openai_client=None,
) -> AssistantService:
    load_dotenv()
    configuration = load_assistant_configuration(config_path=config_path)

    selected_agent_id = agent_id or os.getenv("ASSISTANT_AGENT_ID", "personal_assistant")
    selected_agent = configuration.get_agent(selected_agent_id)
    model_override = str(os.getenv("LLM_MODEL", "")).strip()
    if model_override:
        selected_agent = replace(selected_agent, model=model_override)

    default_memory_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assistant_memory.sqlite3")
    )
    resolved_memory_path = memory_path or os.getenv("ASSISTANT_MEMORY_PATH", default_memory_path)
    max_messages_per_session = _get_env_int("ASSISTANT_MAX_MESSAGES_PER_SESSION", 300, minimum=1)
    max_tool_calls_per_session = _get_env_int("ASSISTANT_MAX_TOOL_CALLS_PER_SESSION", 300, minimum=1)
    max_message_chars = _get_env_int("ASSISTANT_MAX_STORED_MESSAGE_CHARS", 4000, minimum=200)
    max_tool_payload_chars = _get_env_int("ASSISTANT_MAX_STORED_TOOL_PAYLOAD_CHARS", 12000, minimum=500)
    max_history_chars = _get_env_int("ASSISTANT_MAX_HISTORY_CHARS", 12000, minimum=1000)
    max_tool_output_chars = _get_env_int("ASSISTANT_MAX_TOOL_OUTPUT_CHARS", 8000, minimum=1000)

    memory_store = ConversationMemoryStore(
        resolved_memory_path,
        max_messages_per_session=max_messages_per_session,
        max_tool_calls_per_session=max_tool_calls_per_session,
        max_message_chars=max_message_chars,
        max_tool_payload_chars=max_tool_payload_chars,
    )
    tool_registry = ToolRegistry(configuration.tools)
    runtime = AssistantRuntime(
        agent=selected_agent,
        tool_registry=tool_registry,
        memory_store=memory_store,
        project_logger=project_logger,
        available_agents=_build_agent_summaries(configuration.get_agent_summaries(), model_override),
        max_history_chars=max_history_chars,
        max_tool_output_chars=max_tool_output_chars,
        openai_client=openai_client,
    )
    return AssistantService(runtime=runtime)


def _build_agent_summaries(agent_summaries, model_override):
    if not model_override:
        return agent_summaries
    return [
        {
            **agent_summary,
            "model": model_override,
        }
        for agent_summary in agent_summaries
    ]


def _get_env_int(name: str, default: int, *, minimum: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(parsed, minimum)
