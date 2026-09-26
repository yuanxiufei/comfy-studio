"""对话式 agent 循环。

一轮 ask 的流程：把用户这句话追加进历史 → 交给模型 → 模型要工具就通过 MCP 执行、
把结果以 tool 消息喂回去 → 反复直到模型不再要工具，最后那条 assistant 文本就是回答。

工具集**不另起一套**：直接用 :class:`~comfy_studio.mcp.McpHub` 汇出来的那张表
（引擎的 skills / 队列 / 历史，加上用户自己配的 server），所以「谁能当 MCP 宿主
调到的能力」与「面板里对话能用的能力」永远一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from ..mcp import McpError, McpHub, McpTool, tool_text
from .llm import LLMConfig, LLMError, OpenAIChatClient
from .types import ChatMessage, ToolCall, system_message, tool_message, user_message

#: 面板里对话时的默认人设。
DEFAULT_SYSTEM_PROMPT = (
    "你是运行在用户电脑上的 ComfyUI 助手，工作在一个叫 comfy-studio 的桌面工作台里。"
    "你可以调用工具：查本机模型、列出并运行 skill（参数化工作流模板）、提交工作流、"
    "查看队列与历史、中断任务。\n"
    "规则：\n"
    "1) 需要模型文件名时先用模型列表工具查，不要凭空编造文件名；\n"
    "2) 不确定某个 skill 有哪些参数时先列一遍 skill；\n"
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

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


EventListener = Callable[[AgentEvent], "Awaitable[None] | None"]


def tool_schemas(tools: list[McpTool]) -> list[dict[str, Any]]:
    """把 MCP 工具表转成 OpenAI 的 ``tools`` 参数形状。"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.qualified_name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


class AgentSession:
    """一次对话（多轮）的会话状态。"""

    def __init__(
        self,
        hub: McpHub,
        tools: list[McpTool],
        llm: OpenAIChatClient | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        if not tools:
            raise AgentError("一个工具都没有：MCP server 还没 start()，或工具表是空的")
        self.hub = hub
        self.tools = tools
        self.llm = llm if llm is not None else OpenAIChatClient(LLMConfig.from_env())
        self.max_steps = max_steps
        self._schemas = tool_schemas(tools)
        self.messages: list[ChatMessage] = [system_message(system_prompt)]

    @property
    def model(self) -> str:
        """这个会话当前用的模型名。"""
        return self.llm.config.model

    async def use_model(self, model: str) -> str:
        """换一个模型：同一个 base_url / api_key 上重建客户端，**历史保留**。

        历史是通用的 chat 消息（含 tool 调用与结果），换模型不用重开对话；
        旧客户端在这里关掉，免得连接攒着。注意调用方得保证这会儿没有在飞的一轮
        （正在 ``await self.llm.complete`` 时换掉会让那一轮失败）。
        """
        name = model.strip()
        if name == "":
            raise AgentError("模型名不能是空字符串")
        if name == self.model:
            return self.model
        previous = self.llm
        self.llm = OpenAIChatClient(replace(previous.config, model=name))
        await previous.close()
        return self.model

    def reset(self) -> None:
        self.messages = self.messages[:1]

    async def _emit(self, listener: EventListener | None, event: AgentEvent) -> None:
        if listener is None:
            return
        result = listener(event)
        if result is not None:
            await result

    async def _run_tool(self, call: ToolCall) -> str:
        try:
            result = await self.hub.call_tool(call.name, call.arguments)
        except McpError as err:
            return f"ERROR: {err}"
        return tool_text(result)

    async def ask(self, text: str, on_event: EventListener | None = None) -> str:
        """问一句，返回最终回答文本。"""
        self.messages.append(user_message(text))

        for _step in range(self.max_steps):
            reply = await self.llm.complete(self.messages, self._schemas)
            self.messages.append(reply)

            if not reply.tool_calls:
                await self._emit(on_event, AgentEvent("final", {"text": reply.content}))
                return reply.content

            if reply.content:
                await self._emit(on_event, AgentEvent("assistant", {"text": reply.content}))
            for call in reply.tool_calls:
                await self._emit(
                    on_event,
                    AgentEvent("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments}),
                )
                output = await self._run_tool(call)
                await self._emit(
                    on_event, AgentEvent("tool_result", {"id": call.id, "name": call.name, "text": output})
                )
                self.messages.append(tool_message(call, output))

        raise AgentError(
            f"{self.max_steps} 轮之内模型一直在调用工具而没有给出结论；"
            "可以让它换个说法再试，或调大 max_steps"
        )

    async def close(self) -> None:
        await self.llm.close()


def create_session(
    hub: McpHub,
    tools: list[McpTool] | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_steps: int = DEFAULT_MAX_STEPS,
    config: LLMConfig | None = None,
) -> AgentSession:
    """按 MCP hub 汇出来的工具表组装一个会话。

    不给 ``config`` 就读环境变量（默认模型）；调用方想在 env 之外再指定模型
    （面板里切过的那种）就自己传一份 ``LLMConfig`` 进来。
    """
    return AgentSession(
        hub,
        tools if tools is not None else hub.tools,
        llm=OpenAIChatClient(config) if config is not None else None,
        system_prompt=system_prompt,
        max_steps=max_steps,
    )


__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentSession",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SYSTEM_PROMPT",
    "EventListener",
    "LLMError",
    "create_session",
    "tool_schemas",
]
