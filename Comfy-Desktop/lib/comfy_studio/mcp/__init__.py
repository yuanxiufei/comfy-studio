"""MCP 宿主层：连 server、汇工具、按名路由调用。"""

from __future__ import annotations

from .client import McpError, McpServerConfig, McpStdioClient, McpTool
from .config import (
    ENGINE_SERVER_NAME,
    SERVERS_ENV,
    collect_servers,
    engine_python,
    engine_server,
    engine_web_tools,
    parse_extra_servers,
)
from .hub import McpHub
from .result import error_message, result_json, result_text, tool_text

__all__ = [
    "ENGINE_SERVER_NAME",
    "SERVERS_ENV",
    "McpError",
    "McpHub",
    "McpServerConfig",
    "McpStdioClient",
    "McpTool",
    "collect_servers",
    "engine_python",
    "engine_server",
    "engine_web_tools",
    "error_message",
    "parse_extra_servers",
    "result_json",
    "result_text",
    "tool_text",
]
