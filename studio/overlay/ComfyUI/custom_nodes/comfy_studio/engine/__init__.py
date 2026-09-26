"""对 ComfyUI 引擎的统一入口。

同一套上层逻辑（MCP 工具、agent 工具、HTTP 路由）需要能在两种处境下工作：

* 作为 custom node 活在引擎进程里 → :class:`InProcessEngine`（直连队列）；
* 被外部宿主 spawn 出来 → :class:`HttpEngine`（说 HTTP）。

:func:`get_engine` 按「引擎在不在本进程」自动选一个。
"""

from __future__ import annotations

import os

from .base import MODEL_PROBES, EngineClient, EngineError
from .http import HttpEngine
from .inprocess import InProcessEngine

DEFAULT_BASE_URL = "http://127.0.0.1:8188"


def in_engine_process() -> bool:
    """当前是否在引擎进程内（PromptServer 已初始化）。"""
    try:
        from server import PromptServer  # type: ignore[import-not-found]
    except ImportError:
        return False
    return getattr(PromptServer, "instance", None) is not None


def get_engine(base_url: str | None = None) -> EngineClient:
    """引擎句柄工厂。默认优先进程内。"""
    if base_url is None:
        if in_engine_process():
            return InProcessEngine()
        return HttpEngine(os.environ.get("COMFY_URL", DEFAULT_BASE_URL))
    return HttpEngine(base_url)


__all__ = [
    "DEFAULT_BASE_URL",
    "EngineClient",
    "EngineError",
    "HttpEngine",
    "InProcessEngine",
    "MODEL_PROBES",
    "get_engine",
    "in_engine_process",
]
