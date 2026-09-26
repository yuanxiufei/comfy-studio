"""桌面侧 agent 层：带工具调用（复用 MCP 工具表）的对话循环。"""

from __future__ import annotations

from .llm import LLMConfig, LLMError, OpenAIChatClient
from .loop import (
    DEFAULT_MAX_STEPS,
    DEFAULT_SYSTEM_PROMPT,
    AgentError,
    AgentEvent,
    AgentSession,
    EventListener,
    create_session,
    tool_schemas,
)
from .types import ChatMessage, Role, ToolCall, system_message, tool_message, user_message

__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentSession",
    "ChatMessage",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SYSTEM_PROMPT",
    "EventListener",
    "LLMConfig",
    "LLMError",
    "OpenAIChatClient",
    "Role",
    "ToolCall",
    "create_session",
    "system_message",
    "tool_message",
    "tool_schemas",
    "user_message",
]
