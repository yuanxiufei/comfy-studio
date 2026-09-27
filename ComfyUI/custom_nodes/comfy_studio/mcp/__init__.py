"""mcp：把引擎能力以 MCP（Model Context Protocol）工具的形式暴露出去。"""

from __future__ import annotations

from .protocol import RpcError, StdioRpcServer
from .server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    create_server,
    default_registry,
    main,
    serve_stdio,
    skills_dir,
)
from .tools import Tool, build_tools, error_result, schema_for, skill_entry, text_result

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "RpcError",
    "StdioRpcServer",
    "Tool",
    "build_tools",
    "create_server",
    "default_registry",
    "error_result",
    "main",
    "schema_for",
    "serve_stdio",
    "skill_entry",
    "skills_dir",
    "text_result",
]
