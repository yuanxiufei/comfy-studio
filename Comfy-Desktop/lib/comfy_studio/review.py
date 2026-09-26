"""审核节点：让 agent 在关键节点停下来问用户，别自己替用户拍板。

参考产品的功能介绍把它写成第 5 步「审核节点 · OUTPUT SYNC」——*Agent 在关键节点主动询问
你的核心方向*。这里落地成一张工具表加一条回程通道，形状与画布通道完全一致
（骨架见 :mod:`comfy_studio.channel`）：

    宿主 agent 工具 → ``agent/event``（type=``ask_user``）→ 面板渲染成一张问答卡
      → 用户答完，面板用 ``agent/answer`` 把答案回给宿主 → 唤醒这里等着的 future

因此它**只有桌面壳在场时才有意义**：没人接这条通道的场合（例如直接 ``setup/run-mcp.mjs``
喂给别的 MCP 客户端），提问会等到超时然后明确报错，绝不替用户编一个答案。桌面壳要显式
启动它（``__main__.py`` 的 ``--review``）。

工具汇进 hub 后叫 ``review__ask_user``（``<server>__<tool>``）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .cancel import CancelToken
from .channel import Channel, ChannelError
from .mcp import McpError, McpTool

#: 汇进工具表时用的 server 名。
REVIEW_SERVER = "review"

#: 等用户回答的上限。问的是人，比画布动作宽得多；但也得有个头——面板被关掉时，
#: 这一轮不能永远挂着。
DEFAULT_ASK_TIMEOUT = 600.0


class ReviewError(ChannelError):
    """审核通道层面的错误：没人接、没答、等超时、回答是空的。"""


@dataclass(frozen=True)
class ReviewServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这条通道只需要名字。"""

    name: str = REVIEW_SERVER


class ReviewChannel(Channel):
    """一次提问的往返：推 ``ask_user`` 出去，等 ``agent/answer`` 回来。"""

    def __init__(self, timeout: float = DEFAULT_ASK_TIMEOUT) -> None:
        super().__init__(
            event_type="ask_user",
            timeout=timeout,
            id_prefix="ask",
            peer="对话面板没在响应",
            error_type=ReviewError,
        )

    async def ask(
        self,
        question: str,
        options: list[str],
        *,
        cancel: CancelToken | None = None,
        timeout: float | None = None,
    ) -> str:
        """问用户一句并等回答；没答/超时/取消一律往上抛，不返回空字符串。"""
        answer = await self._round_trip(
            {"question": question, "options": list(options)},
            what="等用户回答",
            cancel=cancel,
            timeout=timeout,
        )
        if not isinstance(answer, str) or answer.strip() == "":
            # 空回答不算回答：宁可报错让模型重问，也别把沉默当成"随便你"。
            raise ReviewError("用户没有给出有效回答（空回答不算答案）")
        return answer.strip()


@dataclass(frozen=True)
class _Spec:
    """一个审核工具：MCP 工具名 + 说明与参数表。"""

    name: str
    description: str
    input_schema: dict[str, Any]


#: 第一版就一个动作：问一句、等回答。刻意不做"一次问一串"——真实对话里用户一次只回
#: 一句，把好几个问题打包只会让人挑着答、剩下的被默认掉。
REVIEW_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="ask_user",
        description=(
            "在关键节点停下来问用户，等他回答之后再继续。以下情形必须用它，"
            "不要自己替用户猜、也不要把猜测写进结论：需要用户拍板方向时"
            "（走哪条工作流、用哪个模型、要不要覆盖现有画布、成品要什么规格）。"
            "question 要说清在问什么；可以带上 options 给几个候选让用户点选，"
            "用户也能自由作答。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题（一句话说清要拍板什么）"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：给几个候选答案让用户点选（不给就是自由回答）",
                },
            },
            "required": ["question"],
        },
    ),
)


def _validate(args: dict[str, Any]) -> tuple[str, list[str]]:
    """参数在本地先挡一道：模型给的形状不对，就别拿去打扰用户。"""
    question = args.get("question")
    if not isinstance(question, str) or question.strip() == "":
        raise ReviewError("question 必须是非空字符串")
    raw = args.get("options")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ReviewError("options 必须是字符串数组")
    options: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item.strip() == "":
            raise ReviewError("options 里的每一项都必须是非空字符串")
        options.append(item.strip())
    return question.strip(), options


class ReviewClient:
    """鸭子型的 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表（与画布通道同一个做法）。
    """

    def __init__(self, channel: ReviewChannel, config: ReviewServerConfig | None = None) -> None:
        self.channel = channel
        self.config = config if config is not None else ReviewServerConfig()

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
            for spec in REVIEW_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        spec = next((s for s in REVIEW_TOOLS if s.name == name), None)
        if spec is None:
            known = ", ".join(s.name for s in REVIEW_TOOLS)
            raise McpError(f"审核通道没有工具 {name}；可用: {known}")
        try:
            question, options = _validate(dict(arguments or {}))
            answer = await self.channel.ask(question, options, cancel=cancel)
        except ReviewError as err:
            # 用户没答（超时/被取消之外的失败）不算协议错误：回 isError 让模型看到
            # 并自己决定是重问、换问法还是先干别的。取消（Cancelled）不在这里吞掉，
            # 它得冒到 agent 循环去收尾——与画布通道一致。
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"question": question, "answer": answer}, ensure_ascii=False
                    ),
                }
            ],
            "isError": False,
        }


__all__ = [
    "DEFAULT_ASK_TIMEOUT",
    "REVIEW_SERVER",
    "REVIEW_TOOLS",
    "ReviewChannel",
    "ReviewClient",
    "ReviewError",
    "ReviewServerConfig",
]
