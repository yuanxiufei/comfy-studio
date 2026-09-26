"""MCP server 从哪里来。

两个来源：

1. **引擎侧内建**：``<ComfyUI>/custom_nodes/comfy_studio`` 里的 ``comfy_studio.mcp``
   （skills / 队列 / 历史那一整套），用引擎自己的 venv python 拉起来。
2. **用户自定义**：环境变量 ``COMFY_STUDIO_MCP_SERVERS``，一个 JSON 数组，
   元素形如 ``{"name": "...", "command": "...", "args": [...], "env": {...}, "cwd": "..."}``。

路径一律由调用方（桌面壳知道自己装在哪）或环境变量给出，不在代码里写死盘符。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .client import McpError, McpServerConfig

#: 内建的那个 server 的名字，工具会以 ``comfy-studio__<tool>`` 的形式出现。
ENGINE_SERVER_NAME = "comfy-studio"

#: 用户自定义 server 的环境变量名。
SERVERS_ENV = "COMFY_STUDIO_MCP_SERVERS"


def engine_python(comfyui_dir: str | os.PathLike[str]) -> Path:
    """引擎 venv 里的解释器（Windows 是 Scripts/python.exe，其余是 bin/python3）。"""
    venv = Path(comfyui_dir) / ".venv"
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python3"


def engine_server(
    comfyui_dir: str | os.PathLike[str],
    python: str | os.PathLike[str] | None = None,
    comfy_url: str | None = None,
) -> McpServerConfig:
    """内建 server 的启动方式：cwd 放在 custom_nodes，好让 ``comfy_studio`` 可导入。"""
    resolved_python = Path(python) if python is not None else engine_python(comfyui_dir)
    custom_nodes = Path(comfyui_dir) / "custom_nodes"
    if not custom_nodes.is_dir():
        raise McpError(f"找不到 custom_nodes 目录: {custom_nodes}")
    env = {"COMFY_URL": comfy_url or os.environ.get("COMFY_URL", "http://127.0.0.1:8188")}
    return McpServerConfig(
        name=ENGINE_SERVER_NAME,
        command=str(resolved_python),
        args=("-X", "utf8", "-m", "comfy_studio.mcp"),
        env=env,
        cwd=str(custom_nodes),
    )


def parse_extra_servers(raw: str | None = None) -> list[McpServerConfig]:
    """解析用户自定义 server 列表。"""
    text = raw if raw is not None else os.environ.get(SERVERS_ENV, "")
    if text.strip() == "":
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        raise McpError(f"{SERVERS_ENV} 不是合法 JSON: {err}") from err
    if not isinstance(parsed, list):
        raise McpError(f"{SERVERS_ENV} 必须是 JSON 数组")

    servers: list[McpServerConfig] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise McpError(f"{SERVERS_ENV}[{index}] 必须是对象")
        name = item.get("name")
        command = item.get("command")
        if not isinstance(name, str) or name == "" or not isinstance(command, str) or command == "":
            raise McpError(f"{SERVERS_ENV}[{index}] 需要非空的 name 与 command")
        if name == ENGINE_SERVER_NAME:
            raise McpError(f"{SERVERS_ENV}[{index}] 的 name 不能占用内建名 {ENGINE_SERVER_NAME}")
        args = item.get("args", [])
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
            raise McpError(f"{SERVERS_ENV}[{index}].args 必须是字符串数组")
        env = item.get("env", {})
        if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
            raise McpError(f"{SERVERS_ENV}[{index}].env 必须是字符串到字符串的对象")
        cwd = item.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise McpError(f"{SERVERS_ENV}[{index}].cwd 必须是字符串")
        servers.append(
            McpServerConfig(
                name=name, command=command, args=tuple(args), env=dict(env), cwd=cwd
            )
        )
    return servers


def collect_servers(
    comfyui_dir: str | os.PathLike[str] | None = None,
    python: str | os.PathLike[str] | None = None,
    comfy_url: str | None = None,
    extra_raw: str | None = None,
) -> list[McpServerConfig]:
    """内建 server（若 ComfyUI 目录已知）+ 用户自定义 server。"""
    servers: list[McpServerConfig] = []
    resolved_dir = comfyui_dir if comfyui_dir is not None else os.environ.get("COMFYUI_DIR")
    if resolved_dir:
        servers.append(engine_server(resolved_dir, python, comfy_url))
    servers.extend(parse_extra_servers(extra_raw))
    if not servers:
        raise McpError(
            "没有任何 MCP server：请给出 ComfyUI 目录（--comfyui-dir 或 COMFYUI_DIR），"
            f"或用 {SERVERS_ENV} 配置外部 server"
        )
    return servers


__all__ = [
    "ENGINE_SERVER_NAME",
    "SERVERS_ENV",
    "collect_servers",
    "engine_python",
    "engine_server",
    "parse_extra_servers",
]
