"""mcp：把引擎能力以 MCP（Model Context Protocol）工具的形式暴露出去。"""

from __future__ import annotations

from .protocol import RpcError, StdioRpcServer
from .server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    create_server,
    load_default_skills,
    main,
    serve_stdio,
    skills_dir,
)
from .tools import Tool, build_tools, error_result, schema_for, text_result

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "RpcError",
    "StdioRpcServer",
    "Tool",
    "build_tools",
    "create_server",
    "error_result",
    "load_default_skills",
    "main",
    "schema_for",
    "serve_stdio",
    "skills_dir",
    "text_result",
]
