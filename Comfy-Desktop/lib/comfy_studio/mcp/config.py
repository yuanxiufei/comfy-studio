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
from typing import Iterable

from .client import McpError, McpServerConfig, McpTool

#: 内建的那个 server 的名字，工具会以 ``comfy-studio__<tool>`` 的形式出现。
ENGINE_SERVER_NAME = "comfy-studio"

#: 用户自定义 server 的环境变量名。
SERVERS_ENV = "COMFY_STUDIO_MCP_SERVERS"

#: 告诉内建 server"联网不用你管"的环境变量：名字出自引擎侧
#: （``ComfyUI/custom_nodes/comfy_studio/mcp/tools.py`` 的 ``NO_WEB_ENV``），两处必须一致。
#:
#: 为什么要替引擎那个 child 关掉联网：面板那条对话的联网**只该有一套**，而它由宿主出网
#: （宿主自己挂着 ``web__search`` / ``web__fetch`` / ``web__crawl``，响应可取消、能按
#: ``--no-web`` / ``--searxng-url`` 配）。不带这一条时引擎那个 server 会照旧带上自己那三张，
#: 于是面板的工具表里同时有 ``web__*`` 与 ``comfy-studio__web__*`` 两套：模型在两套里随便挑，
#: 两套又各有各的环境变量与后端，"搜不到"时该看哪一份配置成了说不清的事；更要紧的是
#: ``--no-web`` 只关掉了宿主那三张，另外三张还在，这个开关就等于没关（它承诺的是
#: "不想让它出门"）。名字对不上时它**不会报错**，只会悄悄失效 —— 端到端用例盯着这件事
#: （tests/test_host_e2e.py 里"联网工具只有一套"那条断言）。
ENGINE_NO_WEB_ENV = "COMFY_NO_WEB"

#: 上面那个变量的取值。取 ``"1"`` 是因为引擎侧只认 ``1/true/yes/on``（见 mcp/tools.py 的
#: ``_FALSEY``）：写成 ``"0"`` 在那边不算关，会变成"设了变量却照样联网"。
ENGINE_NO_WEB_VALUE = "1"

#: 引擎侧那三把联网工具的名字前缀（``ComfyUI/custom_nodes/comfy_studio/mcp/tools.py`` 里
#: ``web__search`` / ``web__fetch`` / ``web__crawl``）。宿主既然吩咐过引擎"联网不用你管"
#: （见 :data:`ENGINE_NO_WEB_ENV`），引擎的工具表里就不该再有它们。
ENGINE_WEB_TOOL_PREFIX = "web__"


def engine_web_tools(
    tools: Iterable[McpTool], engine_name: str = ENGINE_SERVER_NAME
) -> list[str]:
    """内建 server 名下多出来的联网工具名；正常情况下是空表。

    为什么值得单留一个问句：名字对不上时**两边都不会报错**（:data:`ENGINE_NO_WEB_ENV` 是照
    抄的一份拷贝，两边没有 import 关系），面板只是安静地多出 ``comfy-studio__web__*`` 三张，
    于是"搜不到"时又有两套配置可选。启动日志（``server.py``）拿它喊一声，用例拿它守契约。

    只看 ``tool.server == engine_name`` 那批：宿主自己那三张 ``web__*`` 是**该在**的
    （它们的 server 是 ``web``、名字是 ``search`` 这种），一起算进来就成了永远报警。
    """
    return sorted(
        tool.qualified_name
        for tool in tools
        if tool.server == engine_name and tool.name.startswith(ENGINE_WEB_TOOL_PREFIX)
    )


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
    """内建 server 的启动方式：cwd 放在 custom_nodes，好让 ``comfy_studio`` 可导入。

    环境里固定带两条：引擎 HTTP 地址（``COMFY_URL``）与"联网不用你管"
    （:data:`ENGINE_NO_WEB_ENV`，理由见那个常量）。真想改由引擎那份出网，就别走这个内建条目 ——
    自己加一个 server（``COMFY_STUDIO_MCP_SERVERS``）指向同一个模块、不带这条开关即可，
    这里不提供"半边开关"是因为面板看到的两套联网工具正是这个问题的来源。
    """
    resolved_python = Path(python) if python is not None else engine_python(comfyui_dir)
    custom_nodes = Path(comfyui_dir) / "custom_nodes"
    if not custom_nodes.is_dir():
        raise McpError(f"找不到 custom_nodes 目录: {custom_nodes}")
    env = {
        "COMFY_URL": comfy_url or os.environ.get("COMFY_URL", "http://127.0.0.1:8188"),
        ENGINE_NO_WEB_ENV: ENGINE_NO_WEB_VALUE,
    }
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
    "ENGINE_NO_WEB_ENV",
    "ENGINE_NO_WEB_VALUE",
    "ENGINE_SERVER_NAME",
    "SERVERS_ENV",
    "collect_servers",
    "engine_python",
    "engine_server",
    "engine_web_tools",
    "parse_extra_servers",
]
