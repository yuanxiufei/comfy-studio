"""对话式 agent 循环。

一轮 ask 的流程：把用户这句话追加进历史 → 交给模型 → 模型要工具就通过 MCP 执行、
把结果以 tool 消息喂回去 → 反复直到模型不再要工具，最后那条 assistant 文本就是回答。

一条 assistant 消息里要了多个工具时**并行跑、但按模型给的顺序落账**（见
:meth:`AgentSession._run_tools`）；整轮可以被 :class:`~comfy_studio.cancel.CancelToken`
取消，取消后历史仍然配对完整，会话还能接着用。

工具集**不另起一套**：直接用 :class:`~comfy_studio.mcp.McpHub` 汇出来的那张表
（引擎的 skills / 队列 / 历史，加上用户自己配的 server），所以「谁能当 MCP 宿主
调到的能力」与「面板里对话能用的能力」永远一致。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Sequence

from ..cancel import CancelToken, Cancelled
from ..mcp import McpError, McpHub, McpTool, tool_text
from .llm import LLMConfig, LLMError, OpenAIChatClient
from .types import ChatMessage, ToolCall, system_message, tool_message, user_message

#: 面板里对话时的默认人设（规则部分）。各能力可以往后面插自己的补充段，
#: 收尾要求永远排在最后 —— 见 :func:`compose_system_prompt`。
BASE_SYSTEM_PROMPT = (
    "你是运行在用户电脑上的 ComfyUI 助手，工作在一个叫 comfy-studio 的桌面工作台里。"
    "能用哪些工具以工具列表为准，大致包括：查本机模型类别与模型文件、列出/运行/保存 skill（参数化工作流模板）、"
    "提交工作流、查看队列与历史、中断任务、读写用户本机的文件，"
    "以及（若已开启）在画布上摆放、向用户提问、把一句想法拆成多步计划、记住用户的偏好。\n"
    "规则：\n"
    "1) 涉及本机模型一律先查再说，不要凭印象答：先 comfy_list_model_folders 问本机注册了哪些模型类别"
    "（有哪几类由 ComfyUI 的 folder_paths 说了算，第三方节点注册的目录也在里面），"
    "再拿类别名去 comfy_list_models 取具体文件；文件名照抄工具返回，不要凭空编造，"
    "查不到就说查不到；\n"
    "2) 问到「你是什么模型」「能不能装某个模型/某个功能」这类关乎你自己和这套系统边界的问题时，"
    "照实说手上有什么工具、能做到哪一步：做不到就直说做不到，并说清该归谁管"
    "（例如换或装对话模型是 Ollama 那类本地推理服务的事，不归这里），"
    "不要给「请访问官网」「联系技术支持」这类没有信息量的套话；\n"
    "3) 不确定某个 skill 有哪些参数时先列一遍 skill；\n"
    "4) 运行任务会真的占用用户的显卡，动手前用一句话说明你要做什么；\n"
    "5) 方向拿不准、要在几个方案里挑、或者要贴用户习惯时，先问用户，别替用户拍板；\n"
    "6) 用户说的是一句想法而不是清楚的一条命令（“做张海报感的猫”），或者这事得几步才做得完时，"
    "先用 plan__submit 把步骤清单交给他过一眼：approved=false 就按 feedback 改完再提一次，"
    "别装作没看见；照清单走的时候，每步开始与结束各用 plan__progress 报一次，让他看得见进展；\n"
    "7) 一套工作流跑通、参数也定下来了，就问清名字与说明，把它存成 skill —— 以后直接复用；\n"
    "8) 用户提到的本机文件走 localfiles 那几张工具：要当素材（参考图/音视频）先用 "
    "localfiles__import_file 接进 input，再把返回的 value 填进对应节点字段 —— "
    "ComfyUI 的加载类节点认不了磁盘绝对路径；问「产出存哪了」用 localfiles__list_files 查真实路径，"
    "别拿 filename 拼；要读提示词之类的文本才用 localfiles__read_text。"
)

#: 收尾要求：不管插进来多少补充段，它都在最后一条 —— 免得被补充段淹掉。
CLOSING_SYSTEM_PROMPT = "拿到结果后用一句中文总结，图片用返回的 url 原样给出。"

#: 一个补充段都不插时的人设，就是它。
DEFAULT_SYSTEM_PROMPT = f"{BASE_SYSTEM_PROMPT}\n\n{CLOSING_SYSTEM_PROMPT}"


def compose_system_prompt(*sections: str) -> str:
    """默认人设 + 各能力自己的补充段，收尾要求排在最后。

    补充段由能力自己写（记忆那边是 :meth:`comfy_studio.memory.MemoryStore.digest`）：
    "某段话该放在提示词的哪个位置"只由这里说了算，能力只管自己那段读得通、说得对。
    空段直接跳过，免得提示词里多出空行。
    """
    extra = [section.strip() for section in sections if section and section.strip()]
    return "\n\n".join([BASE_SYSTEM_PROMPT, *extra, CLOSING_SYSTEM_PROMPT])

#: 一次 ask 里最多允许几轮「模型要工具 → 执行」。
DEFAULT_MAX_STEPS = 8

#: 同一条 assistant 消息里的工具调用，最多几个同时在飞。
#:
#: 故意**不照抄**参考实现那个 10：我们这边多数工具是"真的去跑一张图"，并发吃的是
#: 显存而不是 CPU，而引擎的队列本来就会把任务串起来执行——同时放两个已经在重叠
#: "等"的时间了，再加只会把 VRAM 顶上去。要更激进就调大这个值，但先确认显存留得住。
DEFAULT_MAX_PARALLEL_TOOLS = 2


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
        system_prompt: str | Callable[[], str] = DEFAULT_SYSTEM_PROMPT,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS,
        history: Sequence[ChatMessage] | None = None,
    ) -> None:
        if not tools:
            raise AgentError("一个工具都没有：MCP server 还没 start()，或工具表是空的")
        if max_parallel_tools < 1:
            raise AgentError(f"max_parallel_tools 必须 ≥ 1，给的是 {max_parallel_tools}")
        self.hub = hub
        self.tools = tools
        self.llm = llm if llm is not None else OpenAIChatClient(LLMConfig.from_env())
        self.max_steps = max_steps
        self.max_parallel_tools = max_parallel_tools
        #: 人设文本，或者一个**每次重算**它的零参函数（记忆那种每轮都在变的补充段要用它）。
        self.system_prompt = system_prompt
        self._schemas = tool_schemas(tools)
        self.messages: list[ChatMessage] = [system_message(self._system_text()), *self._restore(history)]

    @staticmethod
    def _restore(history: Sequence[ChatMessage] | None) -> list[ChatMessage]:
        """上次的对话（见 :mod:`comfy_studio.history`），直接排在系统提示词后面接着聊。

        只挡一种情况：里面混进了 system。人设是每轮重算的，如果存档里也留了一条，
        就会变成"系统提示词有两条、其中一条还是过期的"，模型到底听谁的说不准 ——
        与其猜，不如当场报错（写存档那边本来就把 system 剔掉了，能混进来就是有人手改过）。
        """
        if not history:
            return []
        restored: list[ChatMessage] = []
        for index, message in enumerate(history):
            if not isinstance(message, ChatMessage):
                raise AgentError(f"history 第 {index} 条不是 ChatMessage：{type(message).__name__}")
            if message.role == "system":
                raise AgentError(
                    f"history 第 {index} 条是 system：人设每轮重算，不该从历史里来"
                )
            restored.append(message)
        return restored

    def _system_text(self) -> str:
        """当前的人设文本。是可调用对象时现算一次 —— 于是这一轮刚记住的事，下一轮就在提示词里。"""
        source = self.system_prompt
        text = source() if callable(source) else source
        if not isinstance(text, str) or text.strip() == "":
            raise AgentError("system_prompt 算出来是空的：补充段或人设本身不对劲")
        return text

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
        return await self.use_config(replace(self.llm.config, model=name))

    async def use_config(self, config: LLMConfig) -> str:
        """整套配置换掉（地址 / 密钥 / 模型），**同一个会话、历史保留**。

        面板上把地址或密钥改了之后走的就是这条：只换模型名的话（:meth:`use_model`）新客户端
        会继承旧地址 —— 用户明明改了地址，看到的还是一模一样的失败，那种错最难查。
        """
        previous = self.llm
        self.llm = OpenAIChatClient(config)
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

    async def _run_tool(self, call: ToolCall, cancel: CancelToken | None) -> str:
        """跑一个工具并把结果压成文本。

        MCP 层的失败翻成 ``ERROR: ...`` 交给模型自己消化（模型经常能换个参数再来一次）；
        :class:`~comfy_studio.cancel.Cancelled` **不在这里吞掉**，它要一路冒到
        :meth:`_run_tools` 去补账。
        """
        try:
            result = await self.hub.call_tool(call.name, call.arguments, cancel=cancel)
        except McpError as err:
            return f"ERROR: {err}"
        return tool_text(result)

    async def _run_tools(
        self, calls: list[ToolCall], on_event: EventListener | None, cancel: CancelToken | None
    ) -> None:
        """跑完一条 assistant 消息里的全部工具调用，结果**按模型给的顺序**写进历史。

        为什么不是逐条 await：模型经常一口气要查好几样东西（模型清单 + skill 目录 +
        队列），串着等纯属白等。这里用滚动池——最多 ``max_parallel_tools`` 个在飞，
        谁先回来不一定，但**只从头部按顺序落账**（``committed`` 只在连续前缀就绪时
        前进）：tool 消息必须与 assistant 的 ``tool_calls`` 顺序对齐，乱序写进历史，
        下一轮请求就是非法的。
        """
        results: list[str | None] = [None] * len(calls)
        in_flight: dict[asyncio.Task[None], int] = {}
        finished: set[int] = set()
        dispatched = 0
        committed = 0

        async def one(index: int) -> None:
            call = calls[index]
            await self._emit(
                on_event,
                AgentEvent("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments}),
            )
            results[index] = await self._run_tool(call, cancel)

        try:
            while committed < len(calls):
                while dispatched < len(calls) and len(in_flight) < self.max_parallel_tools:
                    task = asyncio.create_task(one(dispatched))
                    in_flight[task] = dispatched
                    dispatched += 1
                if not in_flight:
                    # 到不了的：还有没落账的结果，就一定还有在飞或等落账的
                    raise AgentError("工具调度器状态不一致：没有在飞的任务，但仍有调用未落账")
                done, _ = await asyncio.wait(set(in_flight), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    finished.add(in_flight.pop(task))
                    task.result()  # 工具自身的失败已在 _run_tool 里翻成文本；这里只重抛取消
                while committed in finished:
                    call = calls[committed]
                    text = results[committed] or ""
                    await self._emit(
                        on_event, AgentEvent("tool_result", {"id": call.id, "name": call.name, "text": text})
                    )
                    self.messages.append(tool_message(call, text))
                    committed += 1
        except BaseException:
            # 取消（或别的意外）：先把在飞的收干净，再给没落账的调用补上结果。
            for task in in_flight:
                task.cancel()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
            reason = cancel.reason if cancel is not None and cancel.cancelled else "本轮已中止"
            await self._fill_unrecorded(calls, results, dispatched, committed, on_event, reason)
            raise

    async def _fill_unrecorded(
        self,
        calls: list[ToolCall],
        results: list[str | None],
        dispatched: int,
        committed: int,
        on_event: EventListener | None,
        reason: str,
    ) -> None:
        """给还没落账的工具调用补一条 tool 消息。

        OpenAI 的形状要求 assistant 的每个 ``tool_call`` 都有对应的 tool 消息，缺一条
        下一轮请求就是非法的。取消之后用户还要接着聊，所以这一步**不是可选的**：
        跑了一半的、以及压根没派出去的，都得补上（跑了一半的那条用它的真实结果）。
        参考实现 deepseek-harness 在中断时补 ``TOOL_ABORTED_BEFORE_DISPATCH``
        合成结果，是同一个道理。
        """
        for index in range(committed, len(calls)):
            call = calls[index]
            text = results[index]
            if text is None:
                text = f"ERROR: {reason}（{'已中止' if index < dispatched else '未执行'}）"
            if index >= dispatched:
                # 没派出去的调用还没有 tool_call 事件，补一条，免得界面上的卡片对不上。
                await self._emit(
                    on_event,
                    AgentEvent("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments}),
                )
            await self._emit(
                on_event, AgentEvent("tool_result", {"id": call.id, "name": call.name, "text": text})
            )
            self.messages.append(tool_message(call, text))

    async def ask(
        self, text: str, on_event: EventListener | None = None, cancel: CancelToken | None = None
    ) -> str:
        """问一句，返回最终回答文本。

        ``cancel`` 置位（面板上点了停止）时这一轮尽快收敛：正在飞的模型请求与工具调用
        被真的放弃，历史补齐后抛 :class:`~comfy_studio.cancel.Cancelled`。会话本身**仍然
        可用**——历史是配对的，用户可以接着问下一句。
        """
        # 人设每轮重算一次：上一轮刚记下的偏好，这一轮就得看得见（记忆是这么进提示词的）。
        self.messages[0] = system_message(self._system_text())
        self.messages.append(user_message(text))

        async def report_retry(attempt: int, total: int, delay: float, reason: str) -> None:
            await self._emit(
                on_event,
                AgentEvent(
                    "retry",
                    {"attempt": attempt, "total": total, "delay": round(delay, 2), "reason": reason},
                ),
            )

        for _step in range(self.max_steps):
            if cancel is not None:
                cancel.raise_if_cancelled("下一轮模型请求")
            reply = await self.llm.complete(
                self.messages, self._schemas, cancel=cancel, on_retry=report_retry
            )
            self.messages.append(reply)

            if not reply.tool_calls:
                await self._emit(on_event, AgentEvent("final", {"text": reply.content}))
                return reply.content

            if reply.content:
                await self._emit(on_event, AgentEvent("assistant", {"text": reply.content}))
            await self._run_tools(reply.tool_calls, on_event, cancel)

        raise AgentError(
            f"{self.max_steps} 轮之内模型一直在调用工具而没有给出结论；"
            "可以让它换个说法再试，或调大 max_steps"
        )

    async def close(self) -> None:
        await self.llm.close()


def create_session(
    hub: McpHub,
    tools: list[McpTool] | None = None,
    system_prompt: str | Callable[[], str] = DEFAULT_SYSTEM_PROMPT,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS,
    config: LLMConfig | None = None,
    history: Sequence[ChatMessage] | None = None,
) -> AgentSession:
    """按 MCP hub 汇出来的工具表组装一个会话。

    不给 ``config`` 就读环境变量（默认模型）；调用方想在 env 之外再指定模型
    （面板里切过的那种）就自己传一份 ``LLMConfig`` 进来。
    ``system_prompt`` 也可以给一个零参函数（每轮重算，见 :meth:`AgentSession._system_text`）。
    ``history`` 是上次的对话（来自 :mod:`comfy_studio.history` 的存档），接着聊用。
    """
    return AgentSession(
        hub,
        tools if tools is not None else hub.tools,
        llm=OpenAIChatClient(config) if config is not None else None,
        system_prompt=system_prompt,
        max_steps=max_steps,
        max_parallel_tools=max_parallel_tools,
        history=history,
    )


__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentSession",
    "BASE_SYSTEM_PROMPT",
    "CLOSING_SYSTEM_PROMPT",
    "DEFAULT_MAX_PARALLEL_TOOLS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SYSTEM_PROMPT",
    "EventListener",
    "LLMError",
    "compose_system_prompt",
    "create_session",
    "tool_schemas",
]
