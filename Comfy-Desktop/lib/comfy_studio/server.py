"""comfy-studio 宿主的进程接口（桌面壳 ↔ Python）。

协议见 :mod:`comfy_studio.rpc`：行分隔 JSON-RPC 2.0，stdout 只跑协议。
本模块提供的方法（参数与返回一律 snake_case，TS 侧自己映射）：

======================  ==============================================
方法                     说明
======================  ==============================================
``ping``                 探活
``host/info``            版本、方法清单、server 状态、工具数
``mcp/servers``          每个 MCP server 的启动方式与存活/报错尾巴
``mcp/tools``            汇总后的工具表（``<server>__<tool>`` 命名）
``skills/list``          从引擎刷新 skill 目录并返回
``skills/run``           ``{skill_id, params}`` → 运行结果（含图片 url）
``agent/config``         模型是否配好（读环境变量，不回显密钥）
``agent/models``         面板下拉用：可选模型清单（问服务端 ``/models``）+ 当前模型
``agent/model``          ``{model?}`` → 读当前模型 / 切到指定模型（会话内当场生效）
``agent/chat``           ``{text, session_id?}`` → 最终回答；过程中推 ``agent/event`` 通知。
                         被 ``agent/cancel`` 叫停时回 ``cancelled: true``（不是错误）
``agent/cancel``         ``{session_id?}`` → 让正在跑的那一轮尽快停下（幂等）
``agent/canvas_result``   画布通道的回程：桌面壳把页面执行画布动作的结果送回来
``agent/answer``         审核通道的回程：``{call_id, answer}`` → 唤醒等着的提问
``agent/reset``          清空某个会话的历史
======================  ==============================================

``agent/canvas_result`` 与 ``agent/answer`` 是两条「回程」：桌面壳要显式打开
``--canvas`` / ``--review``，接住 ``agent/event`` 里的动作、办完再把结果送回来
（见 :mod:`comfy_studio.canvas` 与 :mod:`comfy_studio.review`）。

本机文件那几张工具（``localfiles__*``，见 :mod:`comfy_studio.localfiles`）不走回程：
它只要知道 ComfyUI 装在哪，因此由 ``--comfyui-dir`` 决定挂不挂，不需要额外开关。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Any

from .agent import AgentError, AgentSession, LLMConfig, LLMError, OpenAIChatClient, create_session
from .canvas import CanvasChannel, CanvasClient
from .cancel import CancelToken, Cancelled
from .channel import bind_emit, unbind_emit
from .localfiles import LocalFiles, LocalFilesClient
from .mcp import McpHub, McpServerConfig
from .review import ReviewChannel, ReviewClient
from .rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcContext, RpcError, StdioRpcServer
from .skills import SkillCatalog, SkillsError

SERVER_NAME = "comfy-studio-desktop"
SERVER_VERSION = "0.1.0"

#: 同时最多留几个对话会话，防止面板反复点造成泄露。
MAX_SESSIONS = 8

#: 不指定 session_id 时用的会话。
DEFAULT_SESSION = "default"

#: 单次 MCP 调用的默认超时：跑 skill 会长时间占用这一次调用，所以给得比通常宽。
DEFAULT_REQUEST_TIMEOUT = 1800.0


def _object(params: Any, method: str) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, f"{method} 的 params 必须是对象")
    return params


def _text(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise RpcError(INVALID_PARAMS, f"{key} 必须是非空字符串")
    return value


class StudioHost:
    """把 hub / skill 目录 / agent 会话收在一个对象里，并注册到 RPC server 上。"""

    def __init__(
        self,
        hub: McpHub,
        catalog: SkillCatalog,
        comfyui_dir: str | None = None,
        comfy_url: str | None = None,
        max_sessions: int = MAX_SESSIONS,
        canvas: CanvasChannel | None = None,
        review: ReviewChannel | None = None,
        local_files: LocalFilesClient | None = None,
    ) -> None:
        self.hub = hub
        self.catalog = catalog
        self.comfyui_dir = comfyui_dir
        self.comfy_url = comfy_url
        self.max_sessions = max_sessions
        #: 画布通道（桌面壳在场时才有）；None 时工具表里也不会有 canvas__* 那两个。
        self.canvas = canvas
        #: 审核通道（同上）；None 时工具表里不会有 review__ask_user。
        self.review = review
        #: 本机文件工具（知道 ComfyUI 装在哪才有）；None 时工具表里不会有 localfiles__*。
        self.local_files = local_files
        #: 面板里切过的模型；None = 用环境变量里那个（进程内有效，不落盘）。
        self.default_model: str | None = None
        self._sessions: dict[str, AgentSession] = {}
        #: 正在跑一轮的会话：session_id → 那一轮的取消令牌。
        #: 这些会话不能被换模型打断（换客户端会把在飞的一轮劈了）。
        self._turns: dict[str, CancelToken] = {}
        self.server = StdioRpcServer({"name": SERVER_NAME, "version": SERVER_VERSION})
        self._register()

    # ---- 注册 -----------------------------------------------------------

    def _register(self) -> None:
        self.server.on("ping", lambda _params, _ctx: {})
        self.server.on("host/info", self.info)
        self.server.on("mcp/servers", self.mcp_servers)
        self.server.on("mcp/tools", self.mcp_tools)
        self.server.on("skills/list", self.skills_list)
        self.server.on("skills/run", self.skills_run)
        self.server.on("agent/config", self.agent_config)
        self.server.on("agent/models", self.agent_models)
        self.server.on("agent/model", self.agent_model)
        self.server.on("agent/chat", self.agent_chat)
        self.server.on("agent/cancel", self.agent_cancel)
        self.server.on("agent/canvas_result", self.agent_canvas_result)
        self.server.on("agent/answer", self.agent_answer)
        self.server.on("agent/reset", self.agent_reset)

    # ---- 方法 -----------------------------------------------------------

    def info(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "host/info")
        return {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "methods": list(self.server.methods),
            "comfyui_dir": self.comfyui_dir,
            "comfy_url": self.comfy_url,
            "tool_count": len(self.hub.tools),
            "sessions": sorted(self._sessions),
            "skills_cached": len(self.catalog.entries),
            "default_model": self.default_model,
            "busy": sorted(self._turns),
            "canvas": self.canvas is not None,
            "review": self.review is not None,
            "local_files": self.local_files is not None,
        }

    def mcp_servers(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "mcp/servers")
        return {"servers": self.hub.servers()}

    def mcp_tools(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "mcp/tools")
        return {
            "tools": [
                {
                    "server": t.server,
                    "name": t.name,
                    "qualified_name": t.qualified_name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in self.hub.tools
            ]
        }

    async def skills_list(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "skills/list")
        try:
            entries = await self.catalog.refresh()
        except SkillsError as err:
            raise RpcError(INTERNAL_ERROR, f"读 skill 目录失败: {err}") from err
        return {"skills": [e.to_json() for e in entries]}

    async def skills_run(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        args = _object(params, "skills/run")
        skill_id = _text(args, "skill_id")
        run_params = args.get("params") or {}
        if not isinstance(run_params, dict):
            raise RpcError(INVALID_PARAMS, "params 必须是对象")
        try:
            run = await self.catalog.run(skill_id, run_params)
        except SkillsError as err:
            raise RpcError(INVALID_PARAMS, str(err)) from err
        return run.to_json()

    def agent_config(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "agent/config")
        tools = sorted(t.qualified_name for t in self.hub.tools)
        try:
            config = LLMConfig.from_env()
        except LLMError as err:
            return {"configured": False, "error": str(err), "tools": tools}
        return {
            "configured": True,
            "model": self._selected_model(config),
            "base_url": config.base_url,
            "temperature": config.temperature,
            "tools": tools,
        }

    async def agent_models(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """面板下拉用：可选模型清单 + 当前值。

        清单问服务端要（OpenAI 兼容的 ``GET {base_url}/models``）。拉不到**不抛错**，
        而是只回当前这一个并带上 ``error`` 说明原因——下拉要是因此空掉，用户连
        正在用的模型都看不见了。``source`` 标明这份清单从哪来。
        """
        _object(params, "agent/models")
        config = self._llm_config()
        current = self._selected_model(config)

        client = OpenAIChatClient(config)
        try:
            models = await client.list_models()
            source, error = "endpoint", None
        except LLMError as err:
            models, source, error = [], "config", str(err)
        finally:
            await client.close()

        if current not in models:
            # 环境变量指定的那个未必在服务端清单里（比如刚被删掉的别名）。
            models = [current, *models]
        return {"current": current, "models": models, "source": source, "error": error}

    async def agent_model(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """不带 ``model`` 是读，带上就是切。

        切换改的是**宿主级默认值**：新会话直接用它，已经建好的会话也当场换掉
        （历史保留）。正忙的会话跳过——那会儿换客户端会把在飞的一轮打断，改由
        调用方决定是等它跑完、``agent/cancel`` 掉它，还是换个 session。
        """
        args = _object(params, "agent/model")
        config = self._llm_config()
        requested = args.get("model")
        if requested is None:
            return {"model": self._selected_model(config), "changed": False, "applied": [], "skipped": []}
        if not isinstance(requested, str) or requested.strip() == "":
            raise RpcError(INVALID_PARAMS, "model 必须是非空字符串")

        name = requested.strip()
        self.default_model = name
        applied: list[str] = []
        skipped: list[str] = []
        for session_id, session in self._sessions.items():
            if session_id in self._turns:
                skipped.append(session_id)
                continue
            await session.use_model(name)
            applied.append(session_id)
        return {"model": name, "changed": True, "applied": sorted(applied), "skipped": sorted(skipped)}

    async def agent_chat(self, params: Any, ctx: RpcContext) -> dict[str, Any]:
        args = _object(params, "agent/chat")
        text = _text(args, "text")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        if session_id in self._turns:
            raise RpcError(
                INVALID_PARAMS,
                f"会话 {session_id} 已有一轮在跑；等它结束、agent/cancel 掉它，或换个 session_id",
            )
        session = self._session(session_id)

        async def on_event(event: object) -> None:
            to_json = getattr(event, "to_json", None)  # AgentEvent
            if to_json is None:  # pragma: no cover - 只会是 AgentEvent
                return
            await ctx.emit("agent/event", {"session_id": session_id, **to_json()})

        cancel = CancelToken()
        self._turns[session_id] = cancel
        # 画布工具靠这条 ctx 把动作推给桌面壳：绑在当前 context 上，工具执行时
        # （`asyncio.create_task` 起的任务会继承 context）才找得到这一轮的出口。
        token = bind_emit(ctx.emit)
        try:
            answer = await session.ask(text, on_event, cancel=cancel)
        except Cancelled as err:
            # 取消**不是失败**：回一个正常结果，面板把气泡收成"已停止"就行。
            return {"session_id": session_id, "text": "", "cancelled": True, "reason": str(err)}
        except (LLMError, AgentError) as err:
            raise RpcError(INTERNAL_ERROR, f"{type(err).__name__}: {err}") from err
        finally:
            unbind_emit(token)
            self._turns.pop(session_id, None)
        return {"session_id": session_id, "text": answer, "cancelled": False}

    def agent_cancel(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """让某一轮尽快停下。幂等：没有在跑的轮次就回 ``cancelled: false``。

        "停下"的分工要说清：宿主这边**立刻**不再等模型、也不再等引擎（在飞的 HTTP
        请求会被真的断开）；引擎那侧目前收不到这个消息（``mcp/protocol.py`` 把通知
        一律丢掉），所以已经排进 ComfyUI 队列的活还会自己跑完。要真停下队列里的事，
        得等引擎侧认 ``notifications/cancelled``。
        """
        args = _object(params, "agent/cancel")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        token = self._turns.get(session_id)
        if token is None:
            return {"session_id": session_id, "cancelled": False}
        token.cancel()
        return {"session_id": session_id, "cancelled": True}

    def agent_canvas_result(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """画布通道的回程：桌面壳把页面执行画布动作的结果送回来。

        幂等：这一轮已经不等了（超时、被取消、已经收过）就回 ``delivered: false``——
        结果来晚了不是错误，桌面壳不需要为此报错。
        """
        args = _object(params, "agent/canvas_result")
        call_id = _text(args, "call_id")
        ok = args.get("ok")
        if not isinstance(ok, bool):
            raise RpcError(INVALID_PARAMS, "ok 必须是布尔值")
        error = args.get("error")
        if error is not None and not isinstance(error, str):
            raise RpcError(INVALID_PARAMS, "error 必须是字符串")
        if self.canvas is None:
            return {"call_id": call_id, "delivered": False}
        delivered = self.canvas.resolve(call_id, ok=ok, result=args.get("result"), error=error)
        return {"call_id": call_id, "delivered": delivered}

    def agent_answer(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """审核通道的回程：面板把用户对 ``ask_user`` 的回答送回来。

        幂等和 :meth:`agent_canvas_result` 一样：这一轮已经不等了（超时、被取消、
        已经收过）就回 ``delivered: false``——人答晚了不是错误。
        """
        args = _object(params, "agent/answer")
        call_id = _text(args, "call_id")
        answer = _text(args, "answer")
        if self.review is None:
            return {"call_id": call_id, "delivered": False}
        delivered = self.review.resolve(call_id, ok=True, result=answer)
        return {"call_id": call_id, "delivered": delivered}

    def agent_reset(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        args = _object(params, "agent/reset")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        session = self._sessions.get(session_id)
        if session is None:
            return {"session_id": session_id, "reset": False}
        session.reset()
        return {"session_id": session_id, "reset": True}

    # ---- 生命周期 -------------------------------------------------------

    def _llm_config(self) -> LLMConfig:
        """环境变量给的基配置；模型没配好就直接报错（切换也救不了没地址的情况）。"""
        try:
            return LLMConfig.from_env()
        except LLMError as err:
            raise RpcError(INTERNAL_ERROR, str(err)) from err

    def _selected_model(self, config: LLMConfig) -> str:
        """当前生效的模型：面板切过就用切过的，否则用环境变量里的。"""
        return self.default_model or config.model

    def _session_config(self) -> LLMConfig:
        config = self._llm_config()
        return replace(config, model=self._selected_model(config))

    def _session(self, session_id: str) -> AgentSession:
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        if len(self._sessions) >= self.max_sessions:
            raise RpcError(
                INVALID_PARAMS,
                f"会话数已达上限 {self.max_sessions}；先 agent/reset 掉不用的，或复用已有 session_id",
            )
        try:
            session = create_session(self.hub, config=self._session_config())
        except (LLMError, AgentError) as err:
            raise RpcError(INTERNAL_ERROR, str(err)) from err
        self._sessions[session_id] = session
        return session

    def cancel_turns(self, reason: str) -> list[str]:
        """把正在跑的一轮都要求停下，返回被叫停的 session_id（已排序）。

        宿主退出时会用（见 :func:`serve_stdio`）：面板把 stdin 关掉之后，不该还等着
        一轮跑 skill 的对话慢慢收尾——那一次等待最长能到工具的 1800 秒超时上。
        """
        return sorted(sid for sid, token in self._turns.items() if token.cancel(reason))

    async def close(self) -> None:
        # 先叫停在飞的轮次（它们会补齐历史后抛 Cancelled），再关会话。
        self.cancel_turns("宿主退出")
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()
        self._turns.clear()


async def serve_stdio(
    configs: list[McpServerConfig],
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    comfyui_dir: str | None = None,
    comfy_url: str | None = None,
    canvas: bool = False,
    review: bool = False,
    input_dir: str | None = None,
    output_dir: str | None = None,
) -> None:
    """拉起全部 MCP server，然后在 stdin/stdout 上服务到 EOF。

    ``canvas=True`` / ``review=True`` 各挂一条「回程」通道（画布动作见
    :mod:`comfy_studio.canvas`；向用户提问见 :mod:`comfy_studio.review`）：那两张工具表
    都要靠桌面壳接住 ``agent/event``、办完再把结果送回 ``agent/canvas_result`` /
    ``agent/answer``。所以默认**不开**——单独给别的 MCP 客户端用时开了也没人接，
    动作只会等到超时。本机文件那几张（:mod:`comfy_studio.localfiles`）不需要谁接话，
    只要 ``comfyui_dir`` 给了就挂上；``input_dir`` / ``output_dir`` 用来对应引擎
    启动参数 ``--input-directory`` / ``--output-directory``（默认就是 comfyui_dir 下的同名目录）。
    """
    canvas_channel = CanvasChannel() if canvas else None
    review_channel = ReviewChannel() if review else None
    local_files = (
        LocalFilesClient(LocalFiles(comfyui_dir, input_dir=input_dir, output_dir=output_dir))
        if comfyui_dir
        else None
    )
    extra: list[Any] = []
    if canvas_channel is not None:
        extra.append(CanvasClient(canvas_channel))
    if review_channel is not None:
        extra.append(ReviewClient(review_channel))
    if local_files is not None:
        extra.append(local_files)
    hub = McpHub(configs, request_timeout=request_timeout, extra_clients=extra)
    await hub.start()
    host: StudioHost | None = None
    try:
        host = StudioHost(
            hub,
            SkillCatalog(hub),
            comfyui_dir=comfyui_dir,
            comfy_url=comfy_url,
            canvas=canvas_channel,
            review=review_channel,
            local_files=local_files,
        )
        # stdin 一关（面板退出）就先叫停在飞的轮次，别让退出卡在长任务上。
        host.server.on_close = lambda: host.cancel_turns("宿主退出")
        names = ", ".join(str(s["name"]) for s in hub.servers())
        print(
            f"[{SERVER_NAME}] MCP server: {names}；工具 {len(hub.tools)} 个",
            file=sys.stderr,
            flush=True,
        )
        await host.server.serve()
    finally:
        if host is not None:
            await host.close()
        await hub.close()


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_SESSION",
    "MAX_SESSIONS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "StudioHost",
    "serve_stdio",
]
