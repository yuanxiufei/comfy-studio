"""多 MCP server 的汇聚层：把 N 个 server 的工具并成一张表，按名路由调用。

工具名统一成 ``<server>__<tool>``（见 :attr:`McpTool.qualified_name`），
一是给模型看的函数名不重名，二是调用时能直接找到该发给哪个 server。
"""

from __future__ import annotations

from typing import Any

from ..cancel import CancelToken
from .client import McpError, McpServerConfig, McpStdioClient, McpTool


class McpHub:
    """管理若干 stdio server 的连接与工具表。"""

    def __init__(
        self,
        configs: list[McpServerConfig],
        request_timeout: float = 120.0,
        extra_clients: list[Any] | None = None,
    ) -> None:
        self._clients: list[Any] = [
            McpStdioClient(cfg, request_timeout=request_timeout) for cfg in configs
        ]
        #: 不是子进程的 client（目前只有画布通道那条，见 :mod:`comfy_studio.canvas`）。
        #: 只要形状对得上（``config.name`` / ``start`` / ``list_tools`` / ``call_tool``），
        #: 就能混进同一张工具表——agent 循环那边因此一行都不用改。
        self._clients.extend(extra_clients or [])
        self._tools: dict[str, McpTool] = {}
        self._by_server: dict[str, Any] = {}

    async def start(self) -> None:
        """全部拉起来并取工具表；任何一个起不来都直接抛错，不做静默跳过。"""
        for client in self._clients:
            await client.start()
            self._by_server[client.config.name] = client
            for tool in await client.list_tools():
                if tool.qualified_name in self._tools:
                    raise McpError(f"工具名冲突: {tool.qualified_name}")
                self._tools[tool.qualified_name] = tool

    async def close(self) -> None:
        for client in self._clients:
            await client.close()
        self._tools.clear()
        self._by_server.clear()

    @property
    def tools(self) -> list[McpTool]:
        return list(self._tools.values())

    def servers(self) -> list[dict[str, object]]:
        return [
            {
                "name": client.config.name,
                "command": client.config.command,
                "args": list(client.config.args),
                "cwd": client.config.cwd,
                "alive": client.alive,
                "stderr_tail": client.stderr_tail(),
            }
            for client in self._clients
        ]

    async def call_tool(
        self,
        qualified_name: str,
        arguments: dict[str, object],
        *,
        cancel: CancelToken | None = None,
    ) -> dict[str, object]:
        tool = self._tools.get(qualified_name)
        if tool is None:
            raise McpError(f"没有工具 {qualified_name}；可用: {', '.join(sorted(self._tools)) or '（无）'}")
        client = self._by_server[tool.server]
        return await client.call_tool(tool.name, arguments, cancel=cancel)


__all__ = ["McpHub"]
