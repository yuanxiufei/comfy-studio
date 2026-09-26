"""对话消息模型。

贴着 OpenAI Chat Completions 的形状（role / content / tool_calls / tool_call_id），
因为它已经是事实标准的方言：Ollama、LM Studio、vLLM、各家网关都照它说话，
贴住它就不必为每家写适配。

与引擎侧 ``<ComfyUI>/custom_nodes/comfy_studio/agent/types.py`` 是同一套形状的两份实现
（两边是独立进程、独立取包路径，不共享代码）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """模型要求执行的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": self.role}
        # 带 tool_calls 的 assistant 消息 content 允许为 null；其余情况一律给字符串。
        if self.tool_calls:
            message["content"] = self.content or None
            message["tool_calls"] = [call.to_openai() for call in self.tool_calls]
        else:
            message["content"] = self.content
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            message["name"] = self.name
        return message


def system_message(text: str) -> ChatMessage:
    return ChatMessage(role="system", content=text)


def user_message(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


def tool_message(call: ToolCall, content: str) -> ChatMessage:
    return ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)


__all__ = [
    "ChatMessage",
    "Role",
    "ToolCall",
    "system_message",
    "tool_message",
    "user_message",
]
