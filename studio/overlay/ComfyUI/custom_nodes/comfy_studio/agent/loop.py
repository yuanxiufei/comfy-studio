"""对话式 agent 循环。

一轮 ask 的流程：把用户这句话追加进历史 → 交给模型 → 模型要工具就执行、把结果
以 tool 消息喂回去 → 反复直到模型不再要工具，最后一条 assistant 文本就是回答。

工具集**不另起一套**：直接复用 ``comfy_studio.mcp.tools.build_tools`` 产出的那批
工具，所以「MCP 宿主能用的能力」与「面板里对话能用的能力」永远一致。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..engine import EngineClient
from ..mcp.tools import Tool
from ..skills import SkillRegistry
from .llm import LLMConfig, LLMError, OpenAIChatClient
from .types import ChatMessage, ToolCall, system_message, tool_message, user_message

#: 面板里对话时的默认人设。
DEFAULT_SYSTEM_PROMPT = (
    "你是运行在用户本机的 ComfyUI 助手。你可以调用工具查看本机模型、列出并运行 skill、"
    "提交工作流、查看队列与历史。\n"
    "规则：\n"
    "1) 需要模型文件名时先用 comfy_list_models 查，不要凭空编造文件名；\n"
    "2) 不确定某个 skill 有哪些参数时先用 comfy_list_skills；\n"
    "3) 运行任务会真的占用用户的显卡，动手前用一句话说明你要做什么；\n"
    "4) 拿到结果后用一句中文总结，图片用返回的 url 原样给出。"
)

#: 一次 ask 里最多允许几轮「模型要工具 → 执行」。
DEFAULT_MAX_STEPS = 8


class AgentError(RuntimeError):
    """agent 循环层面的错误（模型不可用、轮次用尽等）。"""


@dataclass(frozen=True)
class AgentEvent:
    """流式事件：面板可以据此边跑边显示。"""

    type: str  # assistant | tool_call | tool_result | final
    data: dict[str, Any] = field(default_factory=dict)


EventListener = Callable[[AgentEvent], "Awaitable[None] | None"]


def tool_schemas(tools: list[Tool]) -> list[dict[str, Any]]:
    """转成 OpenAI 的 tools 参数形状。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def tool_result_text(result: Any) -> str:
    """把工具返回值压成一段文本喂给模型。

    MCP 的工具返回形如 ``{"content": [{"type": "text", "text": ...}]}``；
    这里把里面的文本拼起来，出错时显式标上 ERROR，别让模型把失败当成功。
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        parts = [block.get("text", "") for block in result.get("content") or [] if isinstance(block, dict)]
        text = "\n".join(p for p in parts if p) or json.dumps(result, ensure_ascii=False)
        return f"ERROR: {text}" if result.get("isError") else text
    return json.dumps(result, ensure_ascii=False, default=str)


class AgentSession:
    """一次对话（多轮）的会话状态。"""

    def __init__(
        self,
        engine: EngineClient,
        tools: list[Tool],
        llm: OpenAIChatClient | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self.engine = engine
        self.tools = tools
        self.llm = llm if llm is not None else OpenAIChatClient(LLMConfig.from_env())
        self.max_steps = max_steps
        self._handlers = {t.name: t.handler for t in tools}
        self._schemas = tool_schemas(tools)
        self.messages: list[ChatMessage] = [system_message(system_prompt)]

    def reset(self) -> None:
        self.messages = self.messages[:1]

    async def _emit(self, listener: EventListener | None, event: AgentEvent) -> None:
        if listener is None:
            return
        result = listener(event)
        if result is not None:
            await result

    async def _run_tool(self, call: ToolCall) -> str:
        handler = self._handlers.get(call.name)
        if handler is None:
            return f"ERROR: 没有工具 {call.name}；可用: {', '.join(self._handlers)}"
        try:
            return tool_result_text(await handler(call.arguments))
        except Exception as err:  # 工具报错要回给模型让它自己改，而不是把整轮对话打断
            return f"ERROR: {type(err).__name__}: {err}"

    async def ask(self, text: str, on_event: EventListener | None = None) -> str:
        """问一句，返回最终回答文本。"""
        self.messages.append(user_message(text))

        for _step in range(self.max_steps):
            reply = await self.llm.complete(self.messages, self._schemas)
            self.messages.append(reply)

            if not reply.tool_calls:
                await self._emit(on_event, AgentEvent("final", {"text": reply.content}))
                return reply.content

            for call in reply.tool_calls:
                await self._emit(
                    on_event, AgentEvent("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments})
                )
                output = await self._run_tool(call)
                await self._emit(on_event, AgentEvent("tool_result", {"id": call.id, "name": call.name, "text": output}))
                self.messages.append(tool_message(call, output))

        raise AgentError(
            f"{self.max_steps} 轮之内模型一直在调用工具而没有给出结论；"
            "可以让它换个说法再试，或调大 max_steps"
        )

    async def close(self) -> None:
        await self.llm.close()


def create_session(engine: EngineClient, registry: SkillRegistry | None = None) -> AgentSession:
    """按需组装一个会话：加载 skill、生成工具集、读环境变量里的模型配置。"""
    from ..mcp.server import default_registry
    from ..mcp.tools import build_tools

    resolved = registry if registry is not None else default_registry()
    if registry is None:
        resolved.reload()
    tools = build_tools(engine, resolved)
    return AgentSession(engine, tools)


__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentSession",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SYSTEM_PROMPT",
    "EventListener",
    "LLMError",
    "create_session",
    "tool_result_text",
    "tool_schemas",
]
