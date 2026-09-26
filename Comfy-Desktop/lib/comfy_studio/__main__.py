"""``python -m comfy_studio``：桌面壳拉起来的 comfy-studio 宿主进程。

桌面壳（Electron 主进程）这样拉它::

    <引擎 venv>/python.exe -X utf8 -m comfy_studio --comfyui-dir <ComfyUI 目录>

cwd 必须是本包的**父目录**（即 Comfy-Desktop/lib），否则 ``-m comfy_studio`` 找不到包。
引擎那个 MCP server 由本进程内部再 spawn 一次（见 ``mcp/config.py``），
所以这里不需要引擎已经在跑；只是跑 skill 时会要求引擎在 ``--comfy-url`` 上活着。

不依赖任何新第三方包：aiohttp 是引擎 venv 自带的（ComfyUI 的依赖）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .mcp import SERVERS_ENV, McpError, collect_servers
from .server import DEFAULT_REQUEST_TIMEOUT, SERVER_NAME, serve_stdio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfy_studio", description="comfy-studio 桌面宿主（stdio JSON-RPC 服务）"
    )
    parser.add_argument(
        "--comfyui-dir",
        default=None,
        help="ComfyUI 检出目录（含 .venv 与 custom_nodes）；不传则读环境变量 COMFYUI_DIR",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="引擎 venv 的解释器；默认取 <comfyui-dir>/.venv 里的那个",
    )
    parser.add_argument(
        "--comfy-url",
        default=None,
        help="注入给 MCP server 的引擎地址；默认 http://127.0.0.1:8188（也可用 COMFY_URL）",
    )
    parser.add_argument(
        "--servers",
        default=None,
        help=f"额外的 MCP server（JSON 数组）；不传则读环境变量 {SERVERS_ENV}",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"单次 MCP 调用超时秒数（默认 {DEFAULT_REQUEST_TIMEOUT:g}；跑 skill 会长时间占用）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        configs = collect_servers(
            comfyui_dir=args.comfyui_dir,
            python=args.python,
            comfy_url=args.comfy_url,
            extra_raw=args.servers,
        )
    except McpError as err:
        print(f"[{SERVER_NAME}] {err}", file=sys.stderr, flush=True)
        return 2

    try:
        asyncio.run(
            serve_stdio(
                configs,
                request_timeout=args.request_timeout,
                comfyui_dir=args.comfyui_dir or os.environ.get("COMFYUI_DIR"),
                comfy_url=args.comfy_url,
            )
        )
    except KeyboardInterrupt:  # 桌面壳正常退出时是关掉 stdin，这条只为手动 Ctrl+C
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
