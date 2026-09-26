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
    parser.add_argument(
        "--canvas",
        action="store_true",
        help=(
            "挂上画布工具（canvas__snapshot / canvas__load_workflow）。"
            "这些动作要靠桌面壳接住 agent/event 并回 agent/canvas_result，"
            "单独喂给别的 MCP 客户端时别开"
        ),
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "挂上审核工具（review__ask_user）：agent 在关键节点问用户、等回答。"
            "要靠桌面壳把 agent/event 里的 ask_user 画成问答卡，并回 agent/answer，"
            "单独喂给别的 MCP 客户端时别开"
        ),
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help=(
            "挂上计划工具（plan__submit / plan__progress）：agent 把一句想法拆成多步清单，"
            "交用户过目后再逐步执行。要靠桌面壳把 agent/event 里的 plan 画成清单卡、"
            "并回 agent/plan_result，单独喂给别的 MCP 客户端时别开"
        ),
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help=(
            "ComfyUI 的 input 目录（localfiles 工具往里接本地素材）；"
            "默认取 <comfyui-dir>/input（也可用 COMFY_INPUT_DIR），"
            "引擎用 --input-directory 改过时才需要给"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "ComfyUI 的 output 目录（localfiles 工具据此报产出路径）；"
            "默认取 <comfyui-dir>/output（也可用 COMFY_OUTPUT_DIR），"
            "引擎用 --output-directory 改过时才需要给"
        ),
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help=(
            "关掉长期记忆（memory__* 工具与系统提示词里的记忆段）。"
            "默认是开的：记忆落在用户数据目录，见 --memory-dir"
        ),
    )
    parser.add_argument(
        "--memory-dir",
        default=None,
        help=(
            "长期记忆的存放目录（memory.json 落在里面）；"
            "默认按操作系统惯例取用户数据目录（也可用 COMFY_STUDIO_MEMORY_DIR）。"
            "记忆是**用户级**的：放在这里而不是 ComfyUI 检出里，换个检出也还认得你"
        ),
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
                canvas=args.canvas,
                review=args.review,
                plan=args.plan,
                input_dir=args.input_dir or os.environ.get("COMFY_INPUT_DIR"),
                output_dir=args.output_dir or os.environ.get("COMFY_OUTPUT_DIR"),
                memory=not args.no_memory,
                memory_dir=args.memory_dir or os.environ.get("COMFY_STUDIO_MEMORY_DIR"),
            )
        )
    except KeyboardInterrupt:  # 桌面壳正常退出时是关掉 stdin，这条只为手动 Ctrl+C
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
