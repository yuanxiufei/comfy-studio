"""桌面侧 agent 层：带工具调用（复用 MCP 工具表）的对话循环。"""

from __future__ import annotations

from ..cancel import CancelToken, Cancelled
from .catalog import (
    AGENTS_SUBDIR,
    BUILTIN_PROFILES,
    GENERAL_AGENT_ID,
    AgentCatalog,
    AgentCatalogError,
    AgentListing,
    AgentProblem,
    AgentProfile,
    SUMMARY_CHARS,
)
from .llm import LLMConfig, LLMError, OpenAIChatClient
from .loop import (
    BASE_SYSTEM_PROMPT,
    CLOSING_SYSTEM_PROMPT,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DEFAULT_MAX_STEPS,
    DEFAULT_SYSTEM_PROMPT,
    AgentError,
    AgentEvent,
    AgentSession,
    EventListener,
    compose_system_prompt,
    create_session,
    tool_schemas,
)
from .types import ChatMessage, Role, ToolCall, system_message, tool_message, user_message

__all__ = [
    "AGENTS_SUBDIR",
    "AgentCatalog",
    "AgentCatalogError",
    "AgentError",
    "AgentEvent",
    "AgentListing",
    "AgentProblem",
    "AgentProfile",
    "AgentSession",
    "BASE_SYSTEM_PROMPT",
    "BUILTIN_PROFILES",
    "CLOSING_SYSTEM_PROMPT",
    "CancelToken",
    "Cancelled",
    "ChatMessage",
    "DEFAULT_MAX_PARALLEL_TOOLS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SYSTEM_PROMPT",
    "EventListener",
    "GENERAL_AGENT_ID",
    "LLMConfig",
    "LLMError",
    "OpenAIChatClient",
    "Role",
    "SUMMARY_CHARS",
    "ToolCall",
    "compose_system_prompt",
    "create_session",
    "system_message",
    "tool_message",
    "tool_schemas",
    "user_message",
]
