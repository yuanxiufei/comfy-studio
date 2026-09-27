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
from .agent.loop import AgentSession
from .engine import EngineError, get_engine
from .mcp.server import skills_dir
from .mcp.tools import build_tools, skill_entry
from .skills import Skill, SkillRegistry, user_skills_dir

PREFIX = "/comfy-studio"

#: 同时在内存里保留多少个对话会话（按最近使用淘汰，超出的关闭其模型连接）。
MAX_SESSIONS = 8

_registry: SkillRegistry | None = None
_skill_stamp: tuple[tuple[str, float], ...] | None = None
_sessions: dict[str, AgentSession] = {}


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

    created = AgentSession(engine, build_tools(engine, registry), OpenAIChatClient(LLMConfig.from_env()))
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

    @router.get(f"{PREFIX}/agent/config")
    async def agent_config(_request: web.Request) -> web.Response:
        try:
            config = LLMConfig.from_env()
        except LLMError as err:
            return web.json_response({"configured": False, "reason": str(err)})
        return web.json_response(
            {
                "configured": True,
                "model": config.model,
                "base_url": config.base_url,
                "tool_count": len(build_tools(engine, await _skill_registry())),
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
