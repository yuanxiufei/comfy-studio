"""任务拆解：把用户的一句想法拆成多步计划，先让用户过一眼，再一步一步走。

对应产品介绍里的第 1 步「灵感输入」——*给出想法或参考，系统拆出任务清单*。用户说的话
常常是「做一张赛博朋克风格的猫，海报感」这种，看不出该用哪套工作流、几步能跑完；
让模型直接在脑子里编排、闷头做到底，用户就只看到一个黑盒。这里把它落成两张工具：

* ``plan__submit``  —— 交出拆好的清单并**等用户确认**：面板画成一张清单卡，用户点
  「就按这个来」，或者写一句「第 2 步换成 Flux 那套」再退回来。走的是与审核通道同一条
  回程（骨架见 :mod:`comfy_studio.channel`）：宿主推 ``agent/event``（type=``plan``）→
  面板画卡片 → 用户点完用 ``agent/plan_result`` 把态度回给宿主 → 唤醒这里等着的 future。
* ``plan__progress`` —— 某一步开始跑 / 跑完 / 失败时各报一次，让面板把那一步打上勾。
  这条是**单向通知**（不建 future、不等回话）：进度播报不该再把一轮对话卡住。

因此它和审核通道一样**只有桌面壳在场时才成立**：没人接的场合（例如直接
``setup/run-mcp.mjs`` 喂给别的 MCP 客户端），``plan__submit`` 会等到超时然后明确报错，
绝不替用户点头。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .cancel import CancelToken
from .channel import Channel, ChannelError
from .mcp import McpError, McpTool

#: 汇进工具表时用的 server 名。
PLAN_SERVER = "plan"

#: 等用户过目计划的上限。和审核一样问的是人，所以量级相同；但也必须有头。
DEFAULT_PLAN_TIMEOUT = 600.0

#: 计划至少要几步 / 最多几步。一步的事不值得拆，拆过八步就不是给人看的了。
MIN_STEPS = 2
MAX_STEPS = 8

#: 步骤状态。``done`` / ``skipped`` 是终态，面板据此决定要不要还在那儿转圈。
PROGRESS_STATES: tuple[str, ...] = ("running", "done", "failed", "skipped")


class PlanError(ChannelError):
    """计划通道层面的错误：没人接、没人确认、等超时、清单形状不对。"""


@dataclass(frozen=True)
class PlanServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这条通道只需要名字。"""

    name: str = PLAN_SERVER


class PlanChannel(Channel):
    """一次计划的往返：推 ``plan`` 出去，等 ``agent/plan_result`` 回来。"""

    def __init__(self, timeout: float = DEFAULT_PLAN_TIMEOUT) -> None:
        super().__init__(
            event_type="plan",
            timeout=timeout,
            id_prefix="plan",
            peer="对话面板没在响应",
            error_type=PlanError,
        )

    async def submit(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        notes: str | None = None,
        *,
        cancel: CancelToken | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """把清单交给用户过目并等他的态度；没答/超时/取消一律往上抛。"""
        reply = await self._round_trip(
            {"goal": goal, "steps": list(steps), "notes": notes},
            what="等用户过目计划",
            cancel=cancel,
            timeout=timeout,
        )
        if not isinstance(reply, dict):
            raise PlanError("面板回的计划结果不是对象")
        approved = reply.get("approved")
        if not isinstance(approved, bool):
            raise PlanError("面板回的计划结果里没有 approved（布尔值）")
        feedback = reply.get("feedback")
        if feedback is None:
            feedback = ""
        if not isinstance(feedback, str):
            raise PlanError("面板回的计划 feedback 必须是字符串")
        feedback = feedback.strip()
        if not approved and feedback == "":
            # 否掉却不说话，等于让模型瞎猜——宁可报错让面板补上要改什么。
            raise PlanError("用户否掉了计划却没说改哪里（feedback 不能为空）")
        return {"approved": approved, "feedback": feedback}

    async def progress(
        self,
        step: int,
        status: str,
        note: str | None = None,
        *,
        cancel: CancelToken | None = None,
    ) -> None:
        """报一步的进展；只推事件不等回话。"""
        await self.notify(
            {"step": step, "status": status, "note": note},
            event_type="plan_progress",
            what="播报计划进度",
            cancel=cancel,
        )


@dataclass(frozen=True)
class _Spec:
    """一个计划工具：MCP 工具名 + 说明与参数表。"""

    name: str
    description: str
    input_schema: dict[str, Any]


#: 两张工具：交清单（要人点头）与报进度（单向）。
PLAN_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="submit",
        description=(
            "用户给的是一句想法、还看不出该怎么落地时，先把它拆成一份多步清单交给他过一眼。"
            "什么时候用：用户说来意却没说清路线（“做张赛博朋克海报感的猫”）、或者这件事要"
            "好几步才能做完（先跑一套工作流，再拿产出当素材接着做）。什么时候别用：用户已经在"
            "清楚地下一条命令（“用 SDXL 跑 4 张”），直接做就行。"
            f"steps 至少 {MIN_STEPS} 步、最多 {MAX_STEPS} 步，每步写清做什么，能定下用哪把工具或"
            "哪个 skill 就写上。交出去之后会停住等用户回话：approved=true 就照它做；"
            "approved=false 表示用户要改，必须按 feedback 改完再提一次，别装作没看见。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "这次要做成什么（一句话）"},
                "steps": {
                    "type": "array",
                    "description": (
                        "步骤清单；每项可以是字符串，也可以是 "
                        '{"title": "...", "detail": "...", "tool": "..."} 对象'
                    ),
                    "items": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string", "description": "这一步做什么"},
                                    "detail": {"type": "string", "description": "可选：具体参数/注意事项"},
                                    "tool": {"type": "string", "description": "可选：打算用哪把工具或哪个 skill"},
                                },
                                "required": ["title"],
                            },
                        ]
                    },
                },
                "notes": {"type": "string", "description": "可选：要提醒用户的话（比如哪一步最费显存）"},
            },
            "required": ["goal", "steps"],
        },
    ),
    _Spec(
        name="progress",
        description=(
            "计划里某一步开始跑 / 跑完 / 失败时各报一次，让用户在清单上看到进展。"
            "step 是他在清单里看到的第几步（从 1 数），status 取 "
            + " / ".join(PROGRESS_STATES)
            + "。它不是总结：最后还是要用文字把结果讲清楚，别只靠打勾。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "step": {"type": "integer", "description": "第几步（从 1 数，对应清单里的序号）"},
                "status": {
                    "type": "string",
                    "enum": list(PROGRESS_STATES),
                    "description": "running=正在跑 / done=跑完了 / failed=没成 / skipped=跳过了",
                },
                "note": {"type": "string", "description": "可选：一句话说明（例如失败原因、换了什么参数）"},
            },
            "required": ["step", "status"],
        },
    ),
)


def _normalize_steps(raw: Any) -> list[dict[str, Any]]:
    """把模型给的清单收成统一的 ``{title, detail, tool}``；形状不对就地退回。"""
    if not isinstance(raw, list):
        raise PlanError("steps 必须是数组")
    if len(raw) < MIN_STEPS or len(raw) > MAX_STEPS:
        raise PlanError(f"steps 要有 {MIN_STEPS}~{MAX_STEPS} 步，现在是 {len(raw)} 步")
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        tool: Any = None
        if isinstance(item, str):
            title, detail = item, ""
        elif isinstance(item, dict):
            title = item.get("title")
            detail = item.get("detail") or ""
            tool = item.get("tool")
            if detail is not None and not isinstance(detail, str):
                raise PlanError(f"第 {index} 步的 detail 必须是字符串")
        else:
            raise PlanError(f"第 {index} 步必须是字符串或者对象")
        if not isinstance(title, str) or title.strip() == "":
            raise PlanError(f"第 {index} 步没有 title（要说清这一步做什么）")
        if tool is not None and not isinstance(tool, str):
            raise PlanError(f"第 {index} 步的 tool 必须是字符串")
        steps.append(
            {
                "title": title.strip(),
                "detail": (detail or "").strip(),
                "tool": tool.strip() if isinstance(tool, str) and tool.strip() else None,
            }
        )
    return steps


def _validate(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """参数在本地先挡一道：清单形状不对，就别拿去让用户白看一遍。"""
    if name == "submit":
        goal = args.get("goal")
        if not isinstance(goal, str) or goal.strip() == "":
            raise PlanError("goal 必须是非空字符串")
        notes = args.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise PlanError("notes 必须是字符串")
        return {
            "goal": goal.strip(),
            "steps": _normalize_steps(args.get("steps")),
            "notes": notes.strip() if isinstance(notes, str) and notes.strip() else None,
        }
    if name == "progress":
        step = args.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise PlanError("step 必须是从 1 数的正整数")
        status = args.get("status")
        if status not in PROGRESS_STATES:
            raise PlanError(f"status 必须是 {' / '.join(PROGRESS_STATES)} 之一")
        note = args.get("note")
        if note is not None and not isinstance(note, str):
            raise PlanError("note 必须是字符串")
        return {
            "step": step,
            "status": status,
            "note": note.strip() if isinstance(note, str) and note.strip() else None,
        }
    raise McpError(f"计划通道没有工具 {name}")


class PlanClient:
    """鸭子型的 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表（与画布/审核同一个做法）。
    """

    def __init__(self, channel: PlanChannel, config: PlanServerConfig | None = None) -> None:
        self.channel = channel
        self.config = config if config is not None else PlanServerConfig()

    @property
    def alive(self) -> bool:
        return True

    def stderr_tail(self) -> str:
        return ""

    async def start(self) -> None:
        """没有子进程要拉：这张工具表一直都在。"""

    async def close(self) -> None:
        self.channel.fail_all("宿主关停")

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                server=self.config.name,
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in PLAN_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        spec = next((s for s in PLAN_TOOLS if s.name == name), None)
        if spec is None:
            known = ", ".join(s.name for s in PLAN_TOOLS)
            raise McpError(f"计划通道没有工具 {name}；可用: {known}")
        try:
            kwargs = _validate(name, dict(arguments or {}))
            if name == "submit":
                outcome = await self.channel.submit(cancel=cancel, **kwargs)
                result: dict[str, Any] = {**kwargs, **outcome}
            else:
                await self.channel.progress(cancel=cancel, **kwargs)
                result = kwargs
        except PlanError as err:
            # 没确认成不算协议错误：回 isError 让模型看到原因（改清单 / 换做法），
            # 与画布、审核一致。取消（Cancelled）不在这里吞掉，它得冒到 agent 循环去收尾。
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": False,
        }


__all__ = [
    "DEFAULT_PLAN_TIMEOUT",
    "MAX_STEPS",
    "MIN_STEPS",
    "PLAN_SERVER",
    "PLAN_TOOLS",
    "PROGRESS_STATES",
    "PlanChannel",
    "PlanClient",
    "PlanError",
    "PlanServerConfig",
]
