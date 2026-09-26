"""comfy-studio 的 MCP stdio server。

用法（给 Claude Desktop / Cursor 等宿主在配置里写）::

    {
      "mcpServers": {
        "comfy-studio": {
          "command": "<ComfyUI venv>/Scripts/python.exe",
          "args": ["-m", "comfy_studio.mcp"],
          "cwd": "<ComfyUI>/custom_nodes",
          "env": { "COMFY_URL": "http://127.0.0.1:8188" }
        }
      }
    }

它自己不会去启动引擎：引擎在本进程内（被当 custom node 加载）就直连队列，
否则按 ``COMFY_URL`` 说 HTTP（默认 http://127.0.0.1:8188）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from ..engine import EngineClient, in_engine_process
from ..engine import get_engine
from ..skills import WORKFLOWS_DIR, Skill, SkillRegistry, load_skills, user_skills_dir
from .protocol import INVALID_PARAMS, RpcError, StdioRpcServer
from .tools import Tool, build_tools, error_result, text_result

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "comfy-studio"
SERVER_VERSION = "0.1.0"

#: 覆盖随包自带的 skill 目录（默认用包里的 workflows/）。
SKILLS_DIR_ENV = "COMFY_SKILLS_DIR"


def skills_dir() -> Path:
    override = os.environ.get(SKILLS_DIR_ENV)
    return Path(override).expanduser() if override else WORKFLOWS_DIR


def load_default_skills() -> tuple[Skill, ...]:
    """内置 + 用户 skill 的一次性列表（工具集请用 :func:`default_registry`，那个是活的）。"""
    registry = default_registry()
    registry.reload()
    return registry.all()


def default_registry() -> SkillRegistry:
    """默认的 skill 目录视图：随包自带的只读目录 + 用户自己的可写目录。"""
    return SkillRegistry(builtin_dir=skills_dir(), user_dir=user_skills_dir())


def create_server(
    engine: EngineClient | None = None,
    skills: tuple[Skill, ...] | None = None,
    registry: SkillRegistry | None = None,
) -> StdioRpcServer:
    """组装协议方法 + 工具集，返回可直接 serve 的实例。

    ``registry`` 与 ``skills`` 二选一：给了 ``skills``（测试里塞内存 skill 常用）就包成
    一份内存视图；都没给就按环境变量拼出默认两个目录。
    """
    resolved_engine = engine if engine is not None else get_engine()
    if registry is None:
        if skills is not None:
            registry = SkillRegistry.in_memory(skills)
        else:
            registry = default_registry()
            registry.reload()
    tools: list[Tool] = build_tools(resolved_engine, registry)
    by_name = {t.name: t for t in tools}

    server = StdioRpcServer({"name": SERVER_NAME, "version": SERVER_VERSION})

    def initialize(_params: object) -> dict[str, object]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def ping(_params: object) -> dict[str, object]:
        return {}

    def list_tools(_params: object) -> dict[str, object]:
        return {"tools": [t.describe() for t in tools]}

    async def call_tool(params: object) -> dict[str, object]:
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "tools/call 的 params 必须是对象")
        name = params.get("name")
        if not isinstance(name, str):
            raise RpcError(INVALID_PARAMS, "tools/call 缺少 name")
        tool = by_name.get(name)
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"未知工具 {name}；可用: {', '.join(by_name)}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "tools/call 的 arguments 必须是对象")
        try:
            return await tool.handler(arguments)
        except Exception as err:  # 工具内部失败按 MCP 约定回 isError，而不是 JSON-RPC 错误
            return error_result(err)

    server.on("initialize", initialize)
    server.on("notifications/initialized", lambda _params: None)
    server.on("ping", ping)
    server.on("tools/list", list_tools)
    server.on("tools/call", call_tool)
    return server


async def serve_stdio(engine: EngineClient | None = None) -> None:
    server = create_server(engine)
    kind = "进程内直连队列" if in_engine_process() else "HTTP"
    print(
        f"[{SERVER_NAME}] MCP stdio 就绪（引擎访问方式: {kind}，"
        f"skill 目录: {skills_dir()}，用户 skill 目录: {user_skills_dir()}）",
        file=sys.stderr,
        flush=True,
    )
    try:
        await server.serve()
    finally:
        closer = getattr(engine, "close", None)
        if closer is not None:
            await closer()


def main() -> int:
    asyncio.run(serve_stdio())
    return 0


__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "SKILLS_DIR_ENV",
    "create_server",
    "default_registry",
    "load_default_skills",
    "main",
    "serve_stdio",
    "skills_dir",
    "text_result",
]
