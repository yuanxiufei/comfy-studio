"""桌面侧的渲染层：走 MCP 读引擎那 12 张生产工作流（渲染目标）并触发执行。"""

from __future__ import annotations

from .catalog import (
    LIST_RENDERS_TOOL,
    NO_DEFAULT,
    RENDER_TOOL,
    RenderCatalog,
    RenderRun,
    RenderTarget,
    RendersError,
)

__all__ = [
    "LIST_RENDERS_TOOL",
    "NO_DEFAULT",
    "RENDER_TOOL",
    "RenderCatalog",
    "RenderRun",
    "RenderTarget",
    "RendersError",
]
