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
``agent/agents``         面板下拉用：可选智能体清单（内置 + 用户目录里的 md）+ 当前项
``agent/agent``          ``{agent?}`` → 读当前智能体 / 切到指定智能体（所有会话下一轮生效）
``agent/chat``           ``{text, session_id?}`` → 最终回答；过程中推 ``agent/event`` 通知。
                         被 ``agent/cancel`` 叫停时回 ``cancelled: true``（不是错误）
``agent/cancel``         ``{session_id?}`` → 让正在跑的那一轮尽快停下（幂等）
``agent/canvas_result``   画布通道的回程：桌面壳把页面执行画布动作的结果送回来
``agent/answer``         审核通道的回程：``{call_id, answer}`` → 唤醒等着的提问
``agent/plan_result``    计划通道的回程：``{call_id, approved, feedback?}`` → 唤醒等着的确认
``agent/history``        ``{session_id?}`` → 这个会话说过的话（面板重开时照着重画）
``agent/sessions``       面板那份会话清单：活着的 + 存档里的，一行一段（含标题、条数、在跑）
``agent/close``          ``{session_id?}`` → 关掉一段对话（腾出会话位，对话留在存档里）
``agent/reset``          清空某个会话的历史与它的存档（这一轮在跑就拒绝，免得被收尾写回来）
======================  ==============================================

``agent/canvas_result`` / ``agent/answer`` / ``agent/plan_result`` 是三条「回程」：桌面壳要
显式打开 ``--canvas`` / ``--review`` / ``--plan``，接住 ``agent/event`` 里的动作、办完再把
结果送回来（见 :mod:`comfy_studio.canvas`、:mod:`comfy_studio.review` 与
:mod:`comfy_studio.plan`）。

本机文件那几张工具（``localfiles__*``，见 :mod:`comfy_studio.localfiles`）不走回程：
它只要知道 ComfyUI 装在哪，因此由 ``--comfyui-dir`` 决定挂不挂，不需要额外开关。
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .agent import (
    AGENTS_SUBDIR,
    DEFAULT_SYSTEM_PROMPT,
    GENERAL_AGENT_ID,
    AgentCatalog,
    AgentCatalogError,
    AgentError,
    AgentProfile,
    AgentSession,
    ChatMessage,
    LLMConfig,
    LLMError,
    OpenAIChatClient,
    compose_system_prompt,
    create_session,
)
from .canvas import CanvasChannel, CanvasClient
from .cancel import CancelToken, Cancelled
from .channel import bind_emit, unbind_emit
from .history import (
    SESSION_SUBDIR,
    HistoryError,
    SessionHistoryStore,
    entries as history_entries,
    title_of,
)
from .localfiles import LocalFiles, LocalFilesClient
from .memory import MemoryClient, MemoryStore, MemoryStoreError, memory_home
from .mcp import McpHub, McpServerConfig
from .plan import PlanChannel, PlanClient
from .review import ReviewChannel, ReviewClient
from .rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcContext, RpcError, StdioRpcServer
from .skills import SkillCatalog, SkillsError

SERVER_NAME = "comfy-studio-desktop"
SERVER_VERSION = "0.1.0"

#: 同时最多留几个**活着**的对话会话（每个握着一条 HTTP 连接、一份对话内存），防止面板
#: 反复点造成泄露。到上限不是硬墙：再开新的就淘汰最久没用的那个（见 :meth:`StudioHost._make_room`）。
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


def _agent_json(profile: AgentProfile) -> dict[str, Any]:
    """智能体清单里给面板看的那几个字段。

    不发 ``prompt``：那是拼进系统提示词的人设正文，面板不显示它，每次刷新下拉都把它搬
    一遍只是白费带宽（用户自己写的那种可能很长）。
    """
    return {
        "id": profile.id,
        "name": profile.name,
        "summary": profile.summary,
        "builtin": profile.builtin,
        "file": profile.file,
    }


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
        plan: PlanChannel | None = None,
        local_files: LocalFilesClient | None = None,
        memory: MemoryClient | None = None,
        history: SessionHistoryStore | None = None,
        agents: AgentCatalog | None = None,
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
        #: 计划通道（同上）；None 时工具表里不会有 plan__submit / plan__progress。
        self.plan = plan
        #: 本机文件工具（知道 ComfyUI 装在哪才有）；None 时工具表里不会有 localfiles__*。
        self.local_files = local_files
        #: 跨会话的长期记忆（默认就有，`--no-memory` 关掉）；None 时工具表里不会有 memory__*，
        #: 系统提示词里也不会带"你记得什么"那一段。
        self.memory = memory
        #: 对话存档（默认就有，`--no-history` 关掉）；None 时会话只活在内存里：宿主一退、
        #: 面板一重载，整段对话就没了。
        self.history = history
        #: 智能体目录：内置那几项 + 用户目录里的 md（没配目录就只有内置那几项）。
        self.agents = agents if agents is not None else AgentCatalog()
        #: 面板里切过的模型；None = 用环境变量里那个（进程内有效，不落盘）。
        self.default_model: str | None = None
        #: 面板里切过的智能体；None = 用内置的通用助手（同样只在进程内有效）。
        self.default_agent: str | None = None
        #: 活着的会话。顺序就是"最近用过"的顺序（用得越晚排得越靠后，见 :meth:`_session`），
        #: 到上限时淘汰队首那个 —— 所以这里得是 OrderedDict，普通 dict 改键不会挪位置。
        self._sessions: OrderedDict[str, AgentSession] = OrderedDict()
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
        self.server.on("agent/agents", self.agent_agents)
        self.server.on("agent/agent", self.agent_agent)
        self.server.on("agent/chat", self.agent_chat)
        self.server.on("agent/cancel", self.agent_cancel)
        self.server.on("agent/canvas_result", self.agent_canvas_result)
        self.server.on("agent/answer", self.agent_answer)
        self.server.on("agent/plan_result", self.agent_plan_result)
        self.server.on("agent/history", self.agent_history)
        self.server.on("agent/sessions", self.agent_sessions)
        self.server.on("agent/close", self.agent_close)
        self.server.on("agent/reset", self.agent_reset)

    # ---- 方法 -----------------------------------------------------------

    def info(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        _object(params, "host/info")
        memory_entries, memory_error = self._memory_status()
        agent_id, agent_name, agent_error = self._agent_status()
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
            # 当前生效的智能体：id + 名字 + 它自己的毛病（选中的文件被删掉/改坏时会说话）。
            # 目录整体读不了另走 agents_error —— 那时清单里只剩内置那几项。
            "agent": agent_id,
            "agent_name": agent_name,
            "agent_error": agent_error,
            "agents_dir": str(self.agents.directory) if self.agents.directory else None,
            "agents_error": self.agents.scan().error,
            "busy": sorted(self._turns),
            "canvas": self.canvas is not None,
            "review": self.review is not None,
            "plan": self.plan is not None,
            "local_files": self.local_files is not None,
            # 宿主认的素材/产出目录：引擎的 --input-directory / --output-directory 由桌面壳决定
            # （共享存储下是 Shared/input、Shared/output），这里如实报出来，好让"指偏了"一眼可见
            # —— 这一对目录对不上时，import_file 拷进去的素材引擎看不见、list_files 报的路径也是错的。
            "input_dir": str(self.local_files.files.input_dir)
            if self.local_files is not None
            else None,
            "output_dir": str(self.local_files.files.output_dir)
            if self.local_files is not None
            else None,
            "memory": self.memory is not None,
            "memory_file": str(self.memory.store.path) if self.memory is not None else None,
            "memory_entries": memory_entries,
            "memory_error": memory_error,
            "history": self.history is not None,
            "history_dir": str(self.history.directory) if self.history is not None else None,
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

    async def agent_agents(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """面板下拉用：可选智能体清单 + 当前项。

        清单每次现扫用户目录（往里丢一份 md 不用重启宿主）。``current`` 是**实际生效**的
        id；用户把自己加的那份删了、改名了或改坏了，``missing`` 写明原因，``problems`` 逐份
        报出读不了的文件 —— 面板照实画，不无声无息地少几项。

        目录整体读不了也不抛错：只回内置那几项 + ``error``，理由与 :meth:`agent_models`
        一样 —— 下拉要是因此空掉，用户连正在用的那个都看不见了。
        """
        _object(params, "agent/agents")
        listing = self.agents.scan()
        current = self._selected_agent_id()
        missing = None
        if not any(profile.id == current for profile in listing.profiles):
            missing = (
                f"选中的智能体 {current!r} 不在了（文件被删掉或改名了？）；"
                "换一个，或把文件放回原地"
            )
        return {
            "current": current,
            "missing": missing,
            "agents": [_agent_json(profile) for profile in listing.profiles],
            "problems": [
                {"file": problem.file, "error": problem.error} for problem in listing.problems
            ],
            "error": listing.error,
            "dir": str(self.agents.directory) if self.agents.directory else None,
        }

    async def agent_agent(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """不带 ``agent`` 是读，带上就是切。

        与 :meth:`agent_model` 有两点不同，都是有意的：

        * 切换**不跳过任何会话**，所以没有 ``skipped``。模型切换要给每个空闲会话换掉 HTTP
          客户端，跟正在飞的那一轮打架；智能体换的只是提示词里的角色段，而人设本来就是
          **每轮重算**的（见 :meth:`_prompt_source`）—— 正在跑的那一轮开头已经把提示词算好
          了，不受影响，下一轮自然用新的。
        * 切之前先**验明这个 id 在不在清单里**。模型名可以随便写（合不合法服务端说了算），
          智能体 id 就是我们自己那份目录，写错只会在聊天时才炸，不如当场拒绝。
        """
        args = _object(params, "agent/agent")
        requested = args.get("agent")
        if requested is None:
            agent_id, agent_name, agent_error = self._agent_status()
            return {
                "agent": agent_id,
                "changed": False,
                "name": agent_name,
                "error": agent_error,
            }
        if not isinstance(requested, str) or requested.strip() == "":
            raise RpcError(INVALID_PARAMS, "agent 必须是非空字符串")
        wanted = requested.strip()
        try:
            profile = self.agents.get(wanted)
        except AgentCatalogError as err:
            raise RpcError(INVALID_PARAMS, str(err)) from err
        self.default_agent = wanted
        return {"agent": profile.id, "changed": True, "name": profile.name, "error": None}

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
        session = await self._session(session_id)

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
            # 一轮收尾就落一次盘（被取消的那一轮也落）。放在 finally 里的理由：不管这一轮是
            # 怎么结束的，历史都已经补齐成"完整的一轮"了（见 agent/loop.py 的取消路径），
            # 存进去的存档喂回来不会半截。写失败只记一行 stderr：答案已经算出来交给用户了，
            # 不该因为存档写不进去就把这一轮判成失败。
            self._save_history(session_id, session)
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

    def agent_plan_result(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """计划通道的回程：面板把用户对 ``plan__submit`` 的态度送回来。

        ``approved=false`` 时必须带上 ``feedback``（要改哪里）——否掉却不说话，模型只能瞎猜。
        幂等和另外两条通道一样：这一轮已经不等了就回 ``delivered: false``。
        """
        args = _object(params, "agent/plan_result")
        call_id = _text(args, "call_id")
        approved = args.get("approved")
        if not isinstance(approved, bool):
            raise RpcError(INVALID_PARAMS, "approved 必须是布尔值")
        feedback = args.get("feedback")
        if feedback is not None and not isinstance(feedback, str):
            raise RpcError(INVALID_PARAMS, "feedback 必须是字符串")
        feedback = (feedback or "").strip()
        if not approved and feedback == "":
            raise RpcError(INVALID_PARAMS, "否掉计划时必须说清要改哪里（feedback 不能为空）")
        if self.plan is None:
            return {"call_id": call_id, "delivered": False}
        delivered = self.plan.resolve(
            call_id, ok=True, result={"approved": approved, "feedback": feedback}
        )
        return {"call_id": call_id, "delivered": delivered}

    def agent_history(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """这个会话说过的话，按面板那套画法给（面板重开时照着重画）。

        先看**活着的会话**：它手里的历史最全（存档要到一轮末尾才写）。会话不在内存里
        （宿主重启过、面板刚打开）才去读存档。两边都没有就是一段空对话 —— 还没聊过不是错误。

        ``source`` 说明这份是从哪拿的；``dropped`` 只在读存档时有意义（存档被裁掉、没画出来
        的条数），从内存里拿时一律是 0 —— 因为内存里的会话就是全长，裁只可能发生在读存档那一步。
        """
        args = _object(params, "agent/history")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        session = self._sessions.get(session_id)
        if session is not None:
            messages = [message for message in session.messages if message.role != "system"]
            return {
                "session_id": session_id,
                "source": "session",
                "entries": history_entries(messages),
                "messages": len(messages),
                "dropped": 0,
                "saved_at": "",
            }
        if self.history is None:
            return {
                "session_id": session_id,
                "source": "store",
                "entries": [],
                "messages": 0,
                "dropped": 0,
                "saved_at": "",
            }
        try:
            loaded = self.history.load(session_id)
        except HistoryError as err:
            # 坏存档如实报出来（面板画成一行错误，里面写着文件在哪、怎么重来）。
            # 假装"还没聊过"会让用户以为对话被吞了。
            raise RpcError(INTERNAL_ERROR, str(err)) from err
        return {
            "session_id": session_id,
            "source": "store",
            "entries": history_entries(loaded.messages),
            "messages": len(loaded.messages),
            "dropped": loaded.dropped,
            "saved_at": loaded.saved_at,
        }

    def agent_sessions(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """面板那份"你有几段对话"的清单：活着的会话与存档里的会话合成一行一段。

        同一段对话可能两边都在（活着、盘上也有存档）：那就以**活着的那份**为准（它手里的
        条数更全，存档要到一轮末尾才写），并标上 ``live`` / ``busy``。只有存档里有、内存里
        没有的，标 ``live: false`` —— 它下次被用时会从存档喂回来（见 :meth:`_session`）。

        坏存档**不让整份清单失败**：它作为一条带 ``error`` 的行报出来（``session_id`` 是空的，
        只认得出 ``file``），别的照旧列出来。一个坏文件把清单清空的话，用户连"换一段接着聊"
        都做不到，比多一行红字糟得多。

        只报**盘上有的**：一段新对话在说出第一句话之前不占任何地方，清单里就不该出现它。
        顺序按上次落盘时间倒序（活得久的、没时间的凭 live 排在前面），读不了的排最后。
        """
        _object(params, "agent/sessions")
        rows: list[dict[str, Any]] = []
        archived: dict[str, Any] = {}
        if self.history is not None:
            for item in self.history.list():
                if item.session_id == "":
                    rows.append(
                        {
                            "session_id": "",
                            "live": False,
                            "busy": False,
                            "messages": 0,
                            "saved_at": "",
                            "title": "",
                            "file": item.file,
                            "error": item.error,
                        }
                    )
                    continue
                archived[item.session_id] = item

        # 活会话在最前头（最近用过的排前面，见 _sessions 的顺序），标题与条数先取它手里的那份。
        for session_id, session in self._sessions.items():
            item = archived.pop(session_id, None)
            messages = [message for message in session.messages if message.role != "system"]
            title = item.title if item is not None and item.title else title_of(messages)
            rows.append(
                {
                    "session_id": session_id,
                    "live": True,
                    "busy": session_id in self._turns,
                    "messages": len(messages),
                    "saved_at": item.saved_at if item is not None else "",
                    "title": title,
                    "file": item.file if item is not None else "",
                    "error": None,
                }
            )
        for session_id, item in archived.items():
            rows.append(
                {
                    "session_id": session_id,
                    "live": False,
                    "busy": False,
                    "messages": item.messages,
                    "saved_at": item.saved_at,
                    "title": item.title,
                    "file": item.file,
                    "error": None,
                }
            )
        # 正常的一段排在前（落盘时间越新越前；活着的、还没落过盘的在同一时间档里排前面），
        # 读不了的排最后 —— 它们是"要你去修的文件"，不是能换过去聊的对话。
        rows.sort(
            key=lambda row: (
                row["error"] is None,
                row["saved_at"] or "",
                bool(row["live"]),
            ),
            reverse=True,
        )
        return {
            "sessions": rows,
            "live": len(self._sessions),
            "max_sessions": self.max_sessions,
            "history": self.history is not None,
            "saved_at_order": "desc",
        }

    async def agent_close(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        """关掉一段对话：把它从内存里请出去、放掉它手里的连接（会话位腾出来）。

        与 ``agent/reset`` 的分工要分清：reset 是**清对话**（连存档一起删），close 只是**关掉
        它** —— 对话留在存档里，下次用同一个 session_id 还会被原样喂回来接着聊（见
        :meth:`_session`）。会话位是有数的（见 :meth:`_make_room`），关掉一段就能多留一段。

        有一轮在跑就先别关：那一轮还在往它的 messages 里写，关掉等于把活劈了（而且它收尾时
        会把存档写回去）。想让那一轮现在停，先 ``agent/cancel`` 掉它。

        ``closed`` 说明内存里真的有这段（没有就是"本来也没活着"，不是错误）；``history_kept``
        说明关掉之后还能不能接回来 —— ``--no-history`` 时不能，那关掉就等于丢掉那段对话
        （这是用户自己点的，所以照办，但要如实说清）。
        """
        args = _object(params, "agent/close")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        if session_id in self._turns:
            raise RpcError(
                INVALID_PARAMS,
                f"会话 {session_id} 有一轮在跑；先 agent/cancel 掉它或等它结束再关",
            )
        closed = session_id in self._sessions
        await self._retire(session_id)
        return {
            "session_id": session_id,
            "closed": closed,
            "history_kept": self.history is not None,
            "live": len(self._sessions),
        }

    def agent_reset(self, params: Any, _ctx: RpcContext) -> dict[str, Any]:
        args = _object(params, "agent/reset")
        session_id = args.get("session_id") or DEFAULT_SESSION
        if not isinstance(session_id, str):
            raise RpcError(INVALID_PARAMS, "session_id 必须是字符串")
        # 有一轮在跑就先别清：那一轮收尾时会把它的历史落盘（见 agent_chat 的 finally），
        # 刚删掉的存档会被原样写回来 —— 用户看到的又是"清了个寂寞"，还白删一次文件。
        if session_id in self._turns:
            raise RpcError(
                INVALID_PARAMS,
                f"会话 {session_id} 有一轮在跑；先 agent/cancel 掉它或等它结束再清",
            )
        # 存档也要删。只清内存的话，下次重启会被存档原样复活 —— 用户看到的是"清了个寂寞"。
        cleared = self._clear_history(session_id)
        session = self._sessions.get(session_id)
        if session is None:
            return {"session_id": session_id, "reset": False, "history_cleared": cleared}
        session.reset()
        return {"session_id": session_id, "reset": True, "history_cleared": cleared}

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

    def _memory_status(self) -> tuple[int | None, str | None]:
        """记忆的条数与读盘错误，供 ``host/info`` 如实报出。

        读不了时**不抛**：连握手都失败了，面板就没法把"记忆文件坏了"这句话传到界面上，
        用户只会看到助手连不上。错误照样报出来（``memory_error``），只是不拿它挡门。
        """
        if self.memory is None:
            return None, None
        try:
            return self.memory.store.count, None
        except MemoryStoreError as err:
            return None, str(err)

    def _load_history(self, session_id: str) -> list[ChatMessage]:
        """把这个会话上次的对话读回来 —— 宿主重启之后还接得上，就靠这一步。

        存档坏了就把错误原样交给调用方（面板画成一行错误，写着文件在哪、怎么重来）：
        悄悄当成"还没聊过"会让用户以为对话被吞了。
        """
        if self.history is None:
            return []
        try:
            return list(self.history.load(session_id).messages)
        except HistoryError as err:
            raise RpcError(INTERNAL_ERROR, str(err)) from err

    def _save_history(self, session_id: str, session: AgentSession) -> None:
        """把会话历史落进存档。失败只记 stderr，不往上抛（见 :meth:`agent_chat` 的说明）。"""
        if self.history is None:
            return
        try:
            self.history.save(session_id, session.messages)
        except HistoryError as err:
            print(
                f"[{SERVER_NAME}] 对话存档没写成（{session_id}）：{err}",
                file=sys.stderr,
                flush=True,
            )

    def _clear_history(self, session_id: str) -> bool:
        """删掉一个会话的存档，返回是否真的删了文件（没开存档时恒为 False）。"""
        if self.history is None:
            return False
        try:
            return self.history.clear(session_id)
        except HistoryError as err:
            raise RpcError(INTERNAL_ERROR, str(err)) from err

    def _selected_agent_id(self) -> str:
        """当前生效的智能体 id。没切过就是内置的通用助手。"""
        return self.default_agent or GENERAL_AGENT_ID

    def _agent_status(self) -> tuple[str, str | None, str | None]:
        """(当前智能体 id, 显示名, 毛病)，供 ``host/info`` 与 ``agent/agent`` 如实报出。

        选中的那一项不在清单里（文件被删、改名或改坏了），名字给 None、毛病写清原因 ——
        这一档下每问一句都会报错（见 :meth:`_agent_section`），别让界面停在旧名字上装作没事。
        """
        agent_id = self._selected_agent_id()
        try:
            return agent_id, self.agents.get(agent_id).name, None
        except AgentCatalogError as err:
            return agent_id, None, str(err)

    def _agent_section(self) -> str:
        """选中智能体的角色段。读不了就**当场报错**，不悄悄退回通用助手。

        退回看着"更结实"，其实是把用户自己写的人设吞掉：他会以为那份文件生效了，直到某天
        发现助手答得不对劲才回头查。处置口径与记忆文件坏掉时一致（见 :mod:`comfy_studio.memory`）
        —— 说清是哪一份、怎么修：改好它、删掉它，或者在面板上换一个智能体。
        """
        agent_id = self._selected_agent_id()
        try:
            return self.agents.get(agent_id).prompt
        except AgentCatalogError as err:
            raise AgentError(f"选中的智能体 {agent_id!r} 用不了：{err}") from err

    def _prompt_source(self) -> Callable[[], str]:
        """会话的人设来源：一个**每次重算**的零参函数（:meth:`AgentSession.ask` 每轮都会叫它）。

        提示词 = 底座规则 + 选中智能体的角色段 + 收尾要求（``compose_system_prompt``），
        挂了记忆时再插一段"你记得什么"。所以这里有两件事值得每轮重算：用户可能刚换了个
        智能体，也可能刚被记下一件新事，两个都得在下一轮就看见。

        用的是通用助手（角色段是空串）、又没挂记忆时，拼出来就是 ``DEFAULT_SYSTEM_PROMPT``
        一个字不差 —— ``compose_system_prompt("")`` 会把空段丢掉，默认行为与从前完全一样。
        """
        store = self.memory.store if self.memory is not None else None

        def current() -> str:
            sections = [self._agent_section()]
            if store is not None:
                sections.append(store.digest())
            return compose_system_prompt(*sections)

        return current

    async def _make_room(self) -> None:
        """会话位满了，腾一个出来：淘汰**最久没用过**的那个。

        面板每换一个 session_id 就多留一个会话，上限是为了不让它无限涨。但"满了就报错"
        对用户是说不通的（他又没做错什么，只是想开个新对话），所以这里自动淘汰 —— 前提是
        淘汰**不丢东西**：每一轮收尾都把对话落了盘（:meth:`_save_history`），被淘汰的会话下次
        用同一个 session_id 会被 :meth:`_load_history` 从存档喂回来，用户看到的还是上次那段。

        因此只有**开着存档**时才敢这样淘汰。``--no-history`` 时没有这份兜底，淘汰就是真把
        对话丢了 —— 宁可拒绝，也不偷偷丢：如实说明原因，并把真能做的（复用 session_id、
        自己点 agent/close 关掉一段、重启宿主）讲清。别写成"先 agent/reset 掉不用的"：
        reset 只清对话，不腾会话位；真能腾位子的是 agent/close（那一档下它等于丢掉那段，
        所以只能由用户自己点，不能替用户点）。

        正在跑一轮的会话一律不动：那一轮还在往它的 messages 里写，关掉它等于把活劈了。
        挑不出空闲的就照旧拒绝，并报出卡在哪儿。
        """
        if self.history is None:
            raise RpcError(
                INVALID_PARAMS,
                f"会话数已达上限 {self.max_sessions}；这次启动没开对话存档（--no-history），"
                "淘汰一个会话就等于把它的对话丢掉，所以不自动淘汰。这一档下想腾位子只有两条路："
                "复用已有的 session_id，或者你自己点面板上的“关掉”（agent/close —— 这一档下"
                "关掉就等于丢掉那段对话，所以要你亲自点），也可以重启宿主（关掉桌面壳再开）",
            )
        victim = next((sid for sid in self._sessions if sid not in self._turns), None)
        if victim is None:
            busy = "、".join(sorted(self._turns)) or "（无）"
            raise RpcError(
                INVALID_PARAMS,
                f"会话数已达上限 {self.max_sessions}，而且这些会话都有一轮在跑（{busy}）："
                "等其中一轮结束，或复用已有的 session_id",
            )
        await self._retire(victim)

    async def _retire(self, session_id: str) -> None:
        """把会话从登记表里摘掉并关掉它（顺带放掉它手里的 HTTP 连接）。

        对话没丢：它每轮末尾都落过盘，同一个 session_id 再用会从存档读回来。
        """
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def _session(self, session_id: str) -> AgentSession:
        existing = self._sessions.get(session_id)
        if existing is not None:
            self._sessions.move_to_end(session_id)  # 用一次就算"最近用过"
            return existing
        if len(self._sessions) >= self.max_sessions:
            await self._make_room()
            # 腾位子时让出过执行权，其间可能已经有人把**同一个**会话建好了（面板重发一次请求
            # 就够了）：那就用它。建两个的话后建的那个会把前一个从表里顶掉，谁都不再关得上它。
            raced = self._sessions.get(session_id)
            if raced is not None:
                self._sessions.move_to_end(session_id)
                return raced
        history = self._load_history(session_id)
        try:
            session = create_session(
                self.hub,
                system_prompt=self._prompt_source(),
                history=history,
                config=self._session_config(),
            )
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
    plan: bool = False,
    input_dir: str | None = None,
    output_dir: str | None = None,
    memory: bool = True,
    memory_dir: str | None = None,
    agents_dir: str | None = None,
    history: bool = True,
) -> None:
    """拉起全部 MCP server，然后在 stdin/stdout 上服务到 EOF。

    ``canvas=True`` / ``review=True`` / ``plan=True`` 各挂一条「回程」通道（画布动作见
    :mod:`comfy_studio.canvas`；向用户提问见 :mod:`comfy_studio.review`；多步计划见
    :mod:`comfy_studio.plan`）：那几张工具表都要靠桌面壳接住 ``agent/event``、办完再把
    结果送回 ``agent/canvas_result`` / ``agent/answer`` / ``agent/plan_result``。
    所以默认**不开**——单独给别的 MCP 客户端用时开了也没人接，动作只会等到超时。
    本机文件那几张（:mod:`comfy_studio.localfiles`）不需要谁接话，只要 ``comfyui_dir``
    给了就挂上；``input_dir`` / ``output_dir`` 用来对应引擎启动参数
    ``--input-directory`` / ``--output-directory``（默认就是 comfyui_dir 下的同名目录）。
    长期记忆（:mod:`comfy_studio.memory`）同样不需要谁接话，而且它是这个工作台该有的
    记性，所以**默认开着**：一份落在用户数据目录的 JSON，``memory_dir`` 换地方，
    ``memory=False`` 整个关掉（工具表里就没有 memory__* 了）。
    对话存档（:mod:`comfy_studio.history`）也默认开着，落在同一个数据目录的 ``sessions/``
    下（``memory_dir`` 一并管着这两个落点 —— 它们是同一份"工作台在你用户目录里的数据"）：
    有了它，宿主重启 / 面板重载之后 ``agent/history`` 还能把上次的对话拉回来，接着聊。
    ``history=False`` 就退回内存里的会话，一退就没。它不影响工具表，只影响记忆。
    智能体清单（:mod:`comfy_studio.agent.catalog`）也用这份数据目录：内置那几项写死在代码里，
    用户自己写的 md 放 ``agents/`` 下（``agents_dir`` 换地方）。它只决定人设里的**角色段**，
    既不进工具表也不需要谁接话，所以没有开关 —— 面板上永远有的选。
    """
    canvas_channel = CanvasChannel() if canvas else None
    review_channel = ReviewChannel() if review else None
    plan_channel = PlanChannel() if plan else None
    local_files = (
        LocalFilesClient(LocalFiles(comfyui_dir, input_dir=input_dir, output_dir=output_dir))
        if comfyui_dir
        else None
    )
    memory_client = (
        MemoryClient(MemoryStore(memory_dir or memory_home())) if memory else None
    )
    # 对话存档与记忆共用同一个数据目录（--memory-dir / COMFY_STUDIO_MEMORY_DIR 管着它俩）：
    # 记忆是平铺的 memory.json，对话按会话分文件放在 sessions/ 下。
    data_root = memory_home() if memory_dir is None else Path(memory_dir).expanduser()
    history_store = SessionHistoryStore(data_root / SESSION_SUBDIR) if history else None
    # 智能体清单也落在这份数据目录里：内置那几项 + agents/ 下用户自己写的 md。
    agent_catalog = AgentCatalog(data_root / AGENTS_SUBDIR if agents_dir is None else agents_dir)
    extra: list[Any] = []
    if canvas_channel is not None:
        extra.append(CanvasClient(canvas_channel))
    if review_channel is not None:
        extra.append(ReviewClient(review_channel))
    if plan_channel is not None:
        extra.append(PlanClient(plan_channel))
    if local_files is not None:
        extra.append(local_files)
    if memory_client is not None:
        extra.append(memory_client)
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
            plan=plan_channel,
            local_files=local_files,
            memory=memory_client,
            history=history_store,
            agents=agent_catalog,
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
