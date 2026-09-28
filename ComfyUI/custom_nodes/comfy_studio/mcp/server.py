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
from ..web import BING_SEARCH_URL, SEARCH_BACKEND_SEARXNG, WebConfig, WebFetcher
from .protocol import INVALID_PARAMS, RpcError, StdioRpcServer
from .tools import (
    NO_WEB_ENV,
    SEARXNG_ENV,
    Tool,
    build_tools,
    error_result,
    text_result,
    web_config,
    web_enabled,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "comfy-studio"
SERVER_VERSION = "0.1.0"

#: 覆盖随包自带的 skill 目录（默认用包里的 workflows/）。
SKILLS_DIR_ENV = "COMFY_SKILLS_DIR"


def skills_dir() -> Path:
    override = os.environ.get(SKILLS_DIR_ENV)
    return Path(override).expanduser() if override else WORKFLOWS_DIR


def default_registry() -> SkillRegistry:
    """默认的 skill 目录视图：随包自带的只读目录 + 用户自己的可写目录。"""
    return SkillRegistry(builtin_dir=skills_dir(), user_dir=user_skills_dir())


def create_server(
    engine: EngineClient | None = None,
    skills: tuple[Skill, ...] | None = None,
    registry: SkillRegistry | None = None,
    web: bool = True,
    fetcher: WebFetcher | None = None,
) -> StdioRpcServer:
    """组装协议方法 + 工具集，返回可直接 serve 的实例。

    ``registry`` 与 ``skills`` 二选一：给了 ``skills``（测试里塞内存 skill 常用）就包成
    一份内存视图；都没给就按环境变量拼出默认两个目录。

    ``web`` 决定要不要挂联网那三把（``web__search`` / ``web__fetch`` / ``web__crawl``），
    默认挂。挂上会**往外面发请求**（只抓公网地址，本机 / 内网 / 云元数据一律挡掉），
    不想让它出门就 ``web=False``，或设环境变量 ``COMFY_NO_WEB=1``（后者由 :func:`main` 读）。
    ``fetcher`` 是外部塞进来的联网句柄（测试用）；不给自己造一个，**造出来的这个由本模块
    负责关** —— 见 :func:`serve_stdio`。
    """
    resolved_engine = engine if engine is not None else get_engine()
    if registry is None:
        if skills is not None:
            registry = SkillRegistry.in_memory(skills)
        else:
            registry = default_registry()
            registry.reload()
    resolved_fetcher = fetcher if fetcher is not None else (WebFetcher() if web else None)
    tools: list[Tool] = build_tools(resolved_engine, registry, resolved_fetcher)
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


def web_banner_note(enabled: bool, config: WebConfig) -> str:
    """就绪横幅里"联网"那一截的话。

    **把走哪条搜索路一起报出来**：搜不到东西时第一个要看的就是它，而在引擎侧这件事只由
    一个环境变量决定（:data:`~comfy_studio.mcp.tools.SEARXNG_ENV`），日志里不说清就得去翻代码
    —— 与宿主侧面板那行小字是同一条口径。单独成函数是为了能离线把三种话都验一遍（起进程
    只能验到当时设的那种）。
    """
    if not enabled:
        return f"关（{NO_WEB_ENV}）"
    if config.search_backend == SEARCH_BACKEND_SEARXNG:
        return f"开（自建 SearXNG: {config.searxng_url}）"
    # 换过入口就把入口报出来：日志里没地址就没法排障（与自建实例那条同一个理由）。
    if config.search_url != BING_SEARCH_URL:
        return f"开（必应 RSS 入口: {config.search_url}）"
    return "开（必应 RSS）"


async def serve_stdio(engine: EngineClient | None = None, web: bool | None = None) -> None:
    """起服务并在 stdin/stdout 上服务到 EOF。

    ``web=None`` 表示按环境变量 :data:`~comfy_studio.mcp.tools.NO_WEB_ENV` 决定挂不挂联网。
    搜索后端与搜索入口都读环境变量（:data:`~comfy_studio.mcp.tools.SEARXNG_ENV` /
    :data:`~comfy_studio.mcp.tools.SEARCH_URL_ENV`）：都没给就是必应 RSS，两个都给会报错。
    联网句柄由**这里**建、也由这里关：它握着一条 aiohttp 连接，进程退出时得有人收尾。
    """
    enabled = web_enabled() if web is None else web
    # 关着就不解析联网配置：两个入口变量都设了的机器，不该因为一份**用不上**的配置起不来
    # （宿主侧 `__main__.main` 同一个口径：`--no-web` 时不校验那两个参数）。
    config = web_config() if enabled else WebConfig()
    fetcher = WebFetcher(config) if enabled else None
    server = create_server(engine, web=enabled, fetcher=fetcher)
    kind = "进程内直连队列" if in_engine_process() else "HTTP"
    print(
        f"[{SERVER_NAME}] MCP stdio 就绪（引擎访问方式: {kind}，"
        f"skill 目录: {skills_dir()}，用户 skill 目录: {user_skills_dir()}，"
        f"联网: {web_banner_note(enabled, config)}）",
        file=sys.stderr,
        flush=True,
    )
    try:
        await server.serve()
    finally:
        if fetcher is not None:
            await fetcher.close()
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
    "NO_WEB_ENV",
    "create_server",
    "default_registry",
    "main",
    "serve_stdio",
    "skills_dir",
    "web_banner_note",
    "text_result",
]
