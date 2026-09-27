"""agent：对话式工具调用循环（供面板对话使用）。

工具集来自 :mod:`comfy_studio.mcp.tools`，所以 MCP 宿主与面板看到的工具完全一致。
模型走 OpenAI 兼容的 chat completions 接口，配置见 :class:`~.llm.LLMConfig`。
"""

from __future__ import annotations

from .llm import LLMConfig, LLMError, OpenAIChatClient
from .loop import (
    DEFAULT_MAX_STEPS,
    DEFAULT_SYSTEM_PROMPT,
    AgentError,
    AgentEvent,
    AgentSession,
    EventListener,
    tool_result_text,
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
    "system_message",
    "tool_message",
    "tool_result_text",
    "tool_schemas",
    "user_message",
]
