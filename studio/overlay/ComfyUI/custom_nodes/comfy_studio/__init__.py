"""comfy-studio 的引擎侧（后端）能力包，以标准 ComfyUI custom node 的形式加载。

三块能力各自独立，互不依赖：

============  ==========================================================
``skills``    参数化工作流：定义 / 严格校验 / 参数注入 / 入队执行
``mcp``       stdio JSON-RPC（MCP）server，把上面这些暴露成工具给外部 agent
``agent``     对话式 tool-calling 循环，工具集直接复用 ``mcp`` 那套
``routes``    给前端面板的 HTTP 接口（``/comfy-studio/*``，SSE 推送对话）
============  ==========================================================

本包**不注册画布节点**（``NODE_CLASS_MAPPINGS`` 为空），它加的是能力而不是节点。
"""

from __future__ import annotations

import sys

__version__ = "0.1.0"

# 空映射：本包不往画布上加节点。保留这两个常量是因为 ComfyUI 的 custom node 加载器
# 就是按它们来识别的（``ComfyUI/nodes.py`` 的 load_custom_node / init_extra_nodes）。
NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]


def _register_routes() -> None:
    """引擎进程内就把 /comfy-studio/* 挂上；不在引擎里（例如只被当库 import）则跳过。"""
    from .engine import in_engine_process

    if not in_engine_process():
        print(
            "[comfy_studio] 不在 ComfyUI 引擎进程内，跳过 /comfy-studio/* 路由注册"
            "（skills / mcp / agent 仍可直接使用）",
            file=sys.stderr,
            flush=True,
        )
        return

    from .routes import register_routes

    register_routes()
    print(
        "[comfy_studio] 已挂载 /comfy-studio/*（skills、models、queue、interrupt、agent/chat）",
        file=sys.stderr,
        flush=True,
    )


_register_routes()
