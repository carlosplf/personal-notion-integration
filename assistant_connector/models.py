from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: str
    write_operation: bool = False
    prompt_guidance: str = ""
    guidance_priority: int = 100


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    description: str
    model: str
    system_prompt: str
    tools: list[str]
    max_tool_rounds: int = 6
    memory_window: int = 20


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    project_logger: Any
    agent: AgentDefinition
    available_tools: list[dict[str, Any]]
    available_agents: list[dict[str, Any]]
    user_credential_store: Any = None  # UserCredentialStore | None
    memories_dir: str | None = None
    file_store: Any = None  # FileStore | None
