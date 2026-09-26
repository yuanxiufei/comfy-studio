"""让对话能操作 ComfyUI 画布：读用户此刻正在编辑的图、把工作流载回画布。

**为什么需要一条"回程"通道**：真正拿着画布的是浏览器页面里的 ComfyUI 前端
（``window.comfyAPI.app.app`` 那个 ComfyApp 实例，事实取自引擎 venv 里的
``comfyui_frontend_package`` 打包产物），宿主进程与引擎进程都看不到用户手头这张
**未保存**的图。所以一次动作要绕一圈：

    宿主 agent 工具 → ``agent/event``（type=``canvas_call``）→ 桌面壳（Electron 主进程）
      → 该安装的画布 webContents 里执行 ``canvasCall(op, args)``
      → 壳用 ``agent/canvas_result`` 把结果回给宿主 → 唤醒这里等着的 future

因此这张工具表**只有桌面壳在场时才有意义**：谁都没接这条通道的场合（例如直接
``setup/run-mcp.mjs`` 喂给别的 MCP 客户端），动作会等到超时然后明确报错，绝不静默
返回一个空图。桌面壳要显式启动它（``__main__.py`` 的 ``--canvas``）。

工具汇进 hub 后叫 ``canvas__snapshot`` / ``canvas__load_workflow``（``<server>__<tool>``）。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .cancel import CancelToken, race
from .mcp import McpError, McpTool

#: 汇进工具表时用的 server 名。
CANVAS_SERVER = "canvas"

#: 一次画布动作的等待上限。动作本身就是页面里的一次同步调用，30 秒足够；等不到
#: 说明通道那头没人接，早点报错比让模型干等好。
DEFAULT_CALL_TIMEOUT = 30.0


class CanvasError(RuntimeError):
    """画布通道层面的错误：没人接、动作失败、超时。"""


@dataclass(frozen=True)
class CanvasServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这条通道只需要名字。"""

    name: str = CANVAS_SERVER


#: 往本轮 RPC 现场推一条通知的形状。
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

#: 当前这一轮的 emit（由 :meth:`~comfy_studio.server.StudioHost.agent_chat` 起跑前绑定）。
#: 用 contextvars 而不是成员变量：一个宿主进程里可以同时跑好几个会话的一轮，工具执行
#: 又都在 ``asyncio.create_task`` 里，正好顺着 context 传下去。
_CURRENT_EMIT: contextvars.ContextVar[Emit | None] = contextvars.ContextVar(
    "comfy_studio_canvas_emit", default=None
)


def bind_emit(emit: Emit) -> contextvars.Token[Emit | None]:
    """把这一轮的 emit 绑到当前 context；返回的 token 用来 :func:`unbind_emit`。"""
    return _CURRENT_EMIT.set(emit)


def unbind_emit(token: contextvars.Token[Emit | None]) -> None:
    _CURRENT_EMIT.reset(token)


class CanvasChannel:
    """画布动作的往返：发一条事件出去，等 ``agent/canvas_result`` 回来。"""

    def __init__(self, timeout: float = DEFAULT_CALL_TIMEOUT) -> None:
        self.timeout = timeout
        #: call_id → 等结果的 future；页面回话或超时后都必须摘掉，别攒着。
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0

    @property
    def pending(self) -> int:
        """还等着的动作数（面板/诊断用）。"""
        return len(self._pending)

    async def call(
        self,
        op: str,
        args: dict[str, Any],
        *,
        cancel: CancelToken | None = None,
        timeout: float | None = None,
    ) -> Any:
        """派一个动作出去并等结果；失败/超时/取消一律往上抛，不返回半成品。"""
        emit = _CURRENT_EMIT.get()
        if emit is None:
            raise CanvasError("这一轮没有绑定桌面壳通道：画布工具只能在 agent/chat 里用")
        if cancel is not None:
            cancel.raise_if_cancelled(f"画布动作 {op}")

        self._next_id += 1
        call_id = f"canvas-{self._next_id}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        limit = self.timeout if timeout is None else timeout
        try:
            await emit(
                "agent/event",
                {"type": "canvas_call", "call_id": call_id, "op": op, "args": args},
            )
            try:
                payload = await race(
                    lambda: asyncio.wait_for(future, limit), cancel, what=f"画布动作 {op}"
                )
            except asyncio.TimeoutError as err:
                raise CanvasError(
                    f"画布动作 {op} 等了 {limit:g} 秒没有回音：桌面壳没接这条通道，"
                    "或者画布页面没在跑"
                ) from err
        finally:
            self._pending.pop(call_id, None)

        if payload.get("ok") is not True:
            raise CanvasError(str(payload.get("error") or f"画布动作 {op} 失败"))
        return payload.get("result")

    def resolve(
        self, call_id: str, *, ok: bool, result: Any = None, error: str | None = None
    ) -> bool:
        """收下页面回的结果；返回是否真的有人收（false = 这一轮已经不等了）。"""
        future = self._pending.get(call_id)
        if future is None or future.done():
            return False
        future.set_result({"ok": ok, "result": result, "error": error})
        return True

    def fail_all(self, reason: str) -> int:
        """宿主关停时把还等着的动作都放掉，别让它们拖到超时。"""
        waiting = [f for f in self._pending.values() if not f.done()]
        for future in waiting:
            future.set_exception(CanvasError(reason))
        self._pending.clear()
        return len(waiting)


@dataclass(frozen=True)
class _Spec:
    """一个画布工具：MCP 工具名 + 页面侧的 op 名 + 说明与参数表。"""

    name: str
    op: str
    description: str
    input_schema: dict[str, Any]


#: 第一版只做两件事：**看清**用户手头的图、**放回**一张图。改节点参数/连线那些
#: 破坏性更大的动作，等页面侧把 op 补齐、并且有明确的撤销路径再加。
CANVAS_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="canvas_snapshot",
        op="snapshot",
        description=(
            "读用户此刻正在编辑的 ComfyUI 画布：工作流名、节点（类型/标题，可选参数值）与连线。"
            " 回答“我这张图里有什么”“照着我现在的图改”这类问题之前先调它，别凭印象猜。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "include_widgets": {
                    "type": "boolean",
                    "description": "连每个节点的参数值一起读（默认 false：只要结构，省 token）",
                }
            },
        },
    ),
    _Spec(
        name="canvas_load_workflow",
        op="load_workflow",
        description=(
            "把一份工作流 JSON 载入用户的画布。注意：这会**替换**当前画布，用户没保存的改动会没。"
            "参数是 ComfyUI 图数据（含 nodes 与 links，例如 skill 返回或用户给的工作流）。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "graph": {"type": "object", "description": "工作流 JSON（含 nodes / links 的图数据）"},
                "name": {"type": "string", "description": "载入后在画布上显示的名字"},
            },
            "required": ["graph"],
        },
    ),
)


def _validate(op: str, args: dict[str, Any]) -> dict[str, Any]:
    """参数在本地先挡一道：模型给的形状不对就别往页面送了。"""
    if op == "load_workflow":
        graph = args.get("graph")
        if not isinstance(graph, dict):
            raise CanvasError("graph 必须是工作流 JSON 对象（含 nodes / links）")
        name = args.get("name")
        if name is not None and not isinstance(name, str):
            raise CanvasError("name 必须是字符串")
    elif op == "snapshot":
        include = args.get("include_widgets", False)
        if not isinstance(include, bool):
            raise CanvasError("include_widgets 必须是布尔值")
        args["include_widgets"] = include
    return args


class CanvasClient:
    """鸭子型的 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表，agent 循环那边一行都不用改。
    """

    def __init__(self, channel: CanvasChannel, config: CanvasServerConfig | None = None) -> None:
        self.channel = channel
        self.config = config if config is not None else CanvasServerConfig()

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
            for spec in CANVAS_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        spec = next((s for s in CANVAS_TOOLS if s.name == name), None)
        if spec is None:
            known = ", ".join(s.name for s in CANVAS_TOOLS)
            raise McpError(f"画布没有工具 {name}；可用: {known}")
        try:
            args = _validate(spec.op, dict(arguments or {}))
            result = await self.channel.call(spec.op, args, cancel=cancel)
        except CanvasError as err:
            # 工具没干成不算协议错误：回 isError 让模型看到并自己改，跟引擎侧一致。
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}
            ],
            "isError": False,
        }


__all__ = [
    "CANVAS_SERVER",
    "CANVAS_TOOLS",
    "DEFAULT_CALL_TIMEOUT",
    "CanvasChannel",
    "CanvasClient",
    "CanvasError",
    "CanvasServerConfig",
    "bind_emit",
    "unbind_emit",
]
