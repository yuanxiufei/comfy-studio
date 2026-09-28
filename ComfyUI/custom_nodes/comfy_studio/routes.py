"""给前端面板用的 HTTP 路由。

挂在引擎自己的 aiohttp app 上（``PromptServer.instance.routes``），因此和上游路由
一样会同时出现在 ``/`` 与 ``/api`` 两个前缀下（``ComfyUI/server.py:1231-1242``）。
路由在 custom node 导入期注册：上游 main.py 是先建 PromptServer（第 520 行）
再 init_extra_nodes（第 526 行），所以那时 instance 已经就绪。

约定：一律返回 JSON；失败时 ``{"error": "..."}`` + 合适的 4xx/5xx，
不静默返回空结果。agent 对话走 SSE（text/event-stream），方便面板边跑边渲染。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from .agent import AgentError, AgentEvent, LLMConfig, LLMError, OpenAIChatClient
from .agent.loop import DEFAULT_SYSTEM_PROMPT, AgentSession
from .engine import EngineError, get_engine
from .mcp.server import skills_dir
from .mcp.tools import build_tools, skill_entry, web_config, web_enabled
from .skills import Skill, SkillRegistry, user_skills_dir
from .skills.render import RenderError, prepare_render, render_listing, workflows_dir
from .web import SEARCH_BACKEND_BING, WEB_PROMPT_RULES, WebFetcher

PREFIX = "/comfy-studio"

#: 同时在内存里保留多少个对话会话（按最近使用淘汰，超出的关闭其模型连接）。
MAX_SESSIONS = 8

_registry: SkillRegistry | None = None
_skill_stamp: tuple[tuple[str, float], ...] | None = None
_sessions: dict[str, AgentSession] = {}
#: 面板里对话用的联网句柄：**进程一个、所有会话共用**。它不能被某个会话关掉（那个会话
#: 被淘汰时只关自己的模型连接），所以生命周期跟着进程走（见 :func:`_web_fetcher`）。
#:
#: 名字**不能叫** ``_web_fetcher``：那样它就和下面的函数同名，``def`` 一执行就把这个格子
#: 换成函数对象，于是函数里的 ``is None`` 永远不成立、缓存永远不生效，取回来的"句柄"
#: 其实是函数本身 —— 面板里真去搜一次才会炸。
_fetcher: WebFetcher | None = None


def _web_fetcher() -> WebFetcher | None:
    """取（或建）联网句柄；环境变量关了联网就回 ``None``（工具表里不会出现 ``web__*``）。

    搜索后端也走环境变量（``COMFY_SEARXNG_URL``，见 :func:`comfy_studio.mcp.tools.web_config`）：
    没给就是必应 RSS。这样"面板里这段对话"与"引擎侧 MCP"用的是同一份配置 —— 两处各读一次
    环境变量，而不是各写一份默认值。换**入口**的那个变量（``COMFY_WEB_SEARCH_URL``）同理；
    两个都设了**会在这里报错**（不是静默挑一个），修掉其中一个再问。

    句柄是懒建的：aiohttp 的 session 必须在事件循环里建（第一次真发请求时已经在了，
    见 :meth:`comfy_studio.web.WebFetcher._session`），而且不开联网的机器根本不会走到这儿。
    """
    global _fetcher
    if not web_enabled():
        return None
    if _fetcher is None:
        _fetcher = WebFetcher(web_config())
    return _fetcher


def _system_prompt() -> str:
    """面板对话的人设。挂了联网才把"你可以联网"那一段接上 —— 没挂却写进人设，
    等于教模型去调不存在的 ``web__search``（与宿主侧同一个做法）。"""
    if not web_enabled():
        return DEFAULT_SYSTEM_PROMPT
    return f"{DEFAULT_SYSTEM_PROMPT}\n{WEB_PROMPT_RULES}"


def _skills_stamp() -> tuple[tuple[str, float], ...]:
    """两个 skill 目录（内置 + 用户）的指纹：增删改任何一个文件都会变。

    同步函数，但会 stat 两个目录里的全部 ``.json``，所以调用方一律经
    :func:`asyncio.to_thread` 丢到线程里 —— 这是 aiohttp 的事件循环，别在这里排 IO 队。
    """
    entries: list[tuple[str, float]] = []
    for directory in (skills_dir(), user_skills_dir()):
        d = Path(directory)
        if not d.is_dir():
            continue
        entries.extend(
            (str(f), f.stat().st_mtime) for f in sorted(d.iterdir()) if f.is_file() and f.suffix == ".json"
        )
    return tuple(entries)


async def _skill_registry() -> SkillRegistry:
    """skill 目录视图：内容没变就复用上次加载结果。

    **只换内容、不换对象**（除非目录本身变了）：已经开着的会话把 registry 闭包进了工具集，
    每次请求都新建一个对象的话，"对话里刚存下的 skill"在同一个会话里就看不见了。

    stat 指纹与重新加载都可能读很多文件（用户写坏的 JSON 会在这里报错），所以都走线程。
    """
    global _registry, _skill_stamp
    dirs = (Path(skills_dir()), Path(user_skills_dir()))
    if _registry is None or (_registry.builtin_dir, _registry.user_dir) != dirs:
        _registry = SkillRegistry(builtin_dir=dirs[0], user_dir=dirs[1])
        _skill_stamp = None
    stamp = await asyncio.to_thread(_skills_stamp)
    if _skill_stamp != stamp:
        await asyncio.to_thread(_registry.reload)
        _skill_stamp = stamp
    return _registry


async def _skills() -> tuple[Skill, ...]:
    return (await _skill_registry()).all()


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _bad_request(err: BaseException) -> web.Response:
    return _error(400, f"{type(err).__name__}: {err}")


async def _read_json(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError as err:
        raise ValueError(f"请求体不是合法 JSON: {err}") from err
    if not isinstance(body, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return body


async def _session(session_id: str, engine: Any, registry: SkillRegistry) -> AgentSession:
    """取（或建）一个对话会话；超出上限就淘汰最久未用的那个。"""
    existing = _sessions.get(session_id)
    if existing is not None:
        _sessions.pop(session_id)
        _sessions[session_id] = existing  # 重新插到末尾 = 最近使用
        return existing

    while len(_sessions) >= MAX_SESSIONS:
        oldest_id, oldest = next(iter(_sessions.items()))
        _sessions.pop(oldest_id, None)
        oldest.messages.clear()
        # 关掉它手里的模型连接：aiohttp 的 session 不会因为对象被 GC 就自己关，
        # 只清 messages 会留下一堆没人管的连接（句柄泄漏 + "Unclosed client session"）。
        await oldest.close()

    created = AgentSession(
        engine,
        # 联网句柄是进程级的（不是每个会话一个）：三个会话各开一条 aiohttp 连接没必要，
        # 而且那样一来"哪个会话该关它"就没有答案了。
        build_tools(engine, registry, _web_fetcher()),
        OpenAIChatClient(LLMConfig.from_env()),
        system_prompt=_system_prompt(),
    )
    _sessions[session_id] = created
    return created


def register_routes() -> None:
    """把 /comfy-studio/* 挂到引擎的 router 上。"""
    from server import PromptServer  # type: ignore[import-not-found]

    router = PromptServer.instance.routes
    engine = get_engine()

    @router.get(f"{PREFIX}/skills")
    async def list_skills(_request: web.Request) -> web.Response:
        try:
            loaded = await _skills()
        except (ValueError, OSError) as err:  # 目录里混了坏文件：如实报出来，别给个空列表
            return _error(500, f"{type(err).__name__}: {err}")
        return web.json_response(
            {
                "skills_dir": str(skills_dir()),
                "user_skills_dir": str(user_skills_dir()),
                # 形状与 MCP 工具返回的 skill_entry 一致，前端只认一套字段。
                "skills": [skill_entry(s) for s in loaded],
            }
        )

    @router.get(f"{PREFIX}/models")
    async def list_models(request: web.Request) -> web.Response:
        folder = request.query.get("folder", "checkpoints")
        try:
            return web.json_response({"folder": folder, "models": await engine.list_models(folder)})
        except EngineError as err:
            return _error(400, str(err))

    @router.get(f"{PREFIX}/queue")
    async def queue(_request: web.Request) -> web.Response:
        # 引擎不可达时 engine.queue() 会抛（HTTP 那条路会）：照本模块的约定回 JSON 错误，
        # 别让 aiohttp 丢一个 HTML 错误页给按 JSON 解析的前端。
        try:
            return web.json_response(await engine.queue())
        except EngineError as err:
            return _error(500, str(err))

    @router.post(f"{PREFIX}/interrupt")
    async def interrupt(_request: web.Request) -> web.Response:
        try:
            await engine.interrupt()
        except EngineError as err:
            return _error(500, str(err))
        return web.json_response({"ok": True})

    @router.post(f"{PREFIX}/skills/{{skill_id}}/run")
    async def run_skill(request: web.Request) -> web.Response:
        skill_id = request.match_info["skill_id"]
        try:
            skill = (await _skill_registry()).get(skill_id)
        except (ValueError, OSError) as err:
            return _error(500, f"{type(err).__name__}: {err}")
        if skill is None:
            return _error(404, f"没有 skill {skill_id}")
        try:
            body = await _read_json(request)
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params 必须是对象")
            result = await engine.run_skill(skill, params)
        except ValueError as err:
            return _bad_request(err)
        except EngineError as err:
            return _error(500, str(err))
        return web.json_response(result.to_json(engine.base_url))

    @router.get(f"{PREFIX}/renders")
    async def list_renders(_request: web.Request) -> web.Response:
        """这台机器上配好的渲染目标（与 MCP 的 comfy_list_renders 同一份装配，只换传输）。"""
        return web.json_response(render_listing(workflows_dir()))

    @router.post(f"{PREFIX}/renders/{{target_id}}/run")
    async def run_render(request: web.Request) -> web.Response:
        """跑一个渲染目标：与 MCP 的 comfy_render 同一套组装（含参考图与外部组）。"""
        target_id = request.match_info["target_id"]
        try:
            body = await _read_json(request)
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params 必须是对象")
            images = body.get("images") or ()
            if isinstance(images, str) or not isinstance(images, (list, tuple)):
                raise ValueError('images 必须是数组（哪怕只有一项也要写成 ["…"]）')
            duration_sec = body.get("duration_sec")
            if duration_sec is not None and (
                isinstance(duration_sec, bool) or not isinstance(duration_sec, (int, float))
            ):
                raise ValueError("duration_sec 必须是数字")
            # 形状在这里挡；正数/上限那些规则住在 skills.render 里（组装期唯一说了算的地方）。
            plan = await prepare_render(engine, target_id, images=images, duration_sec=duration_sec)
        except (ValueError, RenderError) as err:
            return _bad_request(err)
        except EngineError as err:
            return _error(500, str(err))

        try:
            result = await engine.run_skill(plan.skill, params)
        except EngineError as err:
            return _error(500, str(err))
        payload: dict[str, Any] = {**result.to_json(engine.base_url), "target": plan.target.id}
        if plan.notes:  # 组装期的让步（时长折算、接了外部组）照实交给面板
            payload["notes"] = list(plan.notes)
        return web.json_response(payload)

    @router.get(f"{PREFIX}/agent/config")
    async def agent_config(_request: web.Request) -> web.Response:
        fetcher = _web_fetcher()
        # 联网这一档照实报，**字段名与宿主侧 host/info 完全一样**：能不能上网、走的是必应
        # 还是自建 SearXNG。两处各报一份是因为两边是不同的进程、各有各的环境变量，
        # 但话得是同一套 —— 前端照着同一个键名画同一句话，也就不会出现"面板说有网、
        # 引擎这边其实没有"这种各说各的。
        web_fields = {
            "web": fetcher is not None,
            # 搜索入口**只在真用它时才报**（走自建 SearXNG 时必应那条 RSS 根本没被请求过）：
            # 那种情况下入口就是 web_searxng_url，理由与宿主侧那份逐字相同。
            "web_search_url": fetcher.config.search_url
            if fetcher is not None and fetcher.config.search_backend == SEARCH_BACKEND_BING
            else None,
            "web_backend": fetcher.config.search_backend if fetcher is not None else None,
            # 没配自建实例时如实报 None 而不是空串：两种都是"没配"，但空串在 JSON 里
            # 看着像"配了一个空地址"（与宿主侧同一个理由）。
            "web_searxng_url": (fetcher.config.searxng_url or None) if fetcher is not None else None,
        }
        try:
            config = LLMConfig.from_env()
        except LLMError as err:
            # 没配好模型也把这几个字段带上：它们的形状不该随另一个字段的值变来变去，
            # 调用方也就不必写两套读法。
            return web.json_response({"configured": False, "reason": str(err), **web_fields})
        return web.json_response(
            {
                "configured": True,
                "model": config.model,
                "base_url": config.base_url,
                # 工具数要与会话里真正拿到的那批一致（不然面板显示的数字会骗人）。
                "tool_count": len(build_tools(engine, await _skill_registry(), fetcher)),
                **web_fields,
            }
        )

    @router.post(f"{PREFIX}/agent/chat")
    async def agent_chat(request: web.Request) -> web.StreamResponse:
        try:
            body = await _read_json(request)
            message = body.get("message")
            if not isinstance(message, str) or message.strip() == "":
                raise ValueError("缺少 message（非空字符串）")
            session_id = str(body.get("session_id") or "default")
        except ValueError as err:
            return _bad_request(err)

        try:
            session = await _session(session_id, engine, await _skill_registry())
        except LLMError as err:
            return _error(503, str(err))
        except (ValueError, OSError) as err:  # skill 目录里混了坏文件 / 读不动
            return _error(500, f"{type(err).__name__}: {err}")

        if body.get("reset"):
            session.reset()

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        async def send(event: str, payload: dict[str, Any]) -> None:
            chunk = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await response.write(chunk.encode("utf-8"))

        await send("start", {"session_id": session_id, "at": int(time.time() * 1000)})

        async def on_event(evt: AgentEvent) -> None:
            await send(evt.type, evt.data)

        try:
            answer = await session.ask(message, on_event)
            await send("done", {"text": answer})
        except (AgentError, LLMError, EngineError, ValueError) as err:
            await send("error", {"message": f"{type(err).__name__}: {err}"})
        except ConnectionResetError:  # 面板关掉了，正常收场
            return response
        await response.write_eof()
        return response


__all__ = ["MAX_SESSIONS", "PREFIX", "register_routes"]
