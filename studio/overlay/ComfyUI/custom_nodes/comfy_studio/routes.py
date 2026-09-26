"""给前端面板用的 HTTP 路由。

挂在引擎自己的 aiohttp app 上（``PromptServer.instance.routes``），因此和上游路由
一样会同时出现在 ``/`` 与 ``/api`` 两个前缀下（``ComfyUI/server.py:1231-1242``）。
路由在 custom node 导入期注册：上游 main.py 是先建 PromptServer（第 520 行）
再 init_extra_nodes（第 526 行），所以那时 instance 已经就绪。

约定：一律返回 JSON；失败时 ``{"error": "..."}`` + 合适的 4xx/5xx，
不静默返回空结果。agent 对话走 SSE（text/event-stream），方便面板边跑边渲染。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from .agent import AgentError, AgentEvent, LLMConfig, LLMError, OpenAIChatClient
from .agent.loop import AgentSession
from .engine import EngineError, get_engine
from .mcp.server import load_default_skills, skills_dir
from .mcp.tools import build_tools

PREFIX = "/comfy-studio"

#: 同时在内存里保留多少个对话会话（按最近使用淘汰，超出的关闭其模型连接）。
MAX_SESSIONS = 8

_skill_cache: tuple[float, tuple[Any, ...]] | None = None
_sessions: dict[str, AgentSession] = {}


def _skills() -> tuple[Any, ...]:
    """加载 skill，目录内文件的时间戳没变就复用上次结果。"""
    global _skill_cache
    directory = Path(skills_dir())
    stamp = 0.0
    if directory.is_dir():
        stamp = max((f.stat().st_mtime for f in directory.iterdir() if f.suffix == ".json"), default=0.0)
    if _skill_cache is not None and _skill_cache[0] == stamp:
        return _skill_cache[1]
    loaded = load_default_skills()
    _skill_cache = (stamp, loaded)
    return loaded


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


def _session(session_id: str, engine: Any, skills: tuple[Any, ...]) -> AgentSession:
    """取（或建）一个对话会话；超出上限就淘汰最久未用的那个。"""
    existing = _sessions.get(session_id)
    if existing is not None:
        _sessions.pop(session_id)
        _sessions[session_id] = existing  # 重新插到末尾 = 最近使用
        return existing

    while len(_sessions) >= MAX_SESSIONS:
        oldest_id, oldest = next(iter(_sessions.items()))
        _sessions.pop(oldest_id, None)
        # 连接交给事件循环回收；这里只保证不泄漏 session 对象。
        oldest.messages.clear()

    created = AgentSession(engine, build_tools(engine, skills), OpenAIChatClient(LLMConfig.from_env()))
    _sessions[session_id] = created
    return created


def register_routes() -> None:
    """把 /comfy-studio/* 挂到引擎的 router 上。"""
    from server import PromptServer  # type: ignore[import-not-found]

    router = PromptServer.instance.routes
    engine = get_engine()

    @router.get(f"{PREFIX}/skills")
    async def list_skills(_request: web.Request) -> web.Response:
        loaded = _skills()
        return web.json_response(
            {
                "skills_dir": str(skills_dir()),
                "skills": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "description": s.description,
                        "tags": list(s.tags),
                        "params": [
                            {
                                "name": p.name,
                                "type": p.type,
                                "required": p.required,
                                "default": p.default if p.has_default else None,
                                "description": p.hint(),
                            }
                            for p in s.params
                        ],
                    }
                    for s in loaded
                ],
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
        return web.json_response(await engine.queue())

    @router.post(f"{PREFIX}/interrupt")
    async def interrupt(_request: web.Request) -> web.Response:
        await engine.interrupt()
        return web.json_response({"ok": True})

    @router.post(f"{PREFIX}/skills/{{skill_id}}/run")
    async def run_skill(request: web.Request) -> web.Response:
        skill_id = request.match_info["skill_id"]
        skill = next((s for s in _skills() if s.id == skill_id), None)
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
                "tool_count": len(build_tools(engine, _skills())),
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
            session = _session(session_id, engine, _skills())
        except LLMError as err:
            return _error(503, str(err))

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
