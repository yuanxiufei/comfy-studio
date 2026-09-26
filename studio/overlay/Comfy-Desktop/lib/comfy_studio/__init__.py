"""Comfy-Desktop 侧的 comfy_studio 包。

与引擎侧 ``<ComfyUI>/custom_nodes/comfy_studio`` 是**同名不同物**的两份代码，
各自跑在各自的进程里：这边的职责是当 MCP **宿主**——把引擎那个 MCP server
（以及用户自定义的 server）拉起来，把它们的工具汇成一张表，再用它跑对话式
agent，最终供桌面壳的面板调用。

不在这里做 eager import：三个子包各自有依赖（agent 要 aiohttp），
按需导入可以让 ``python -c "import comfy_studio"`` 在任何环境都成立。
"""

from __future__ import annotations

__version__ = "0.1.0"

#: 子包名，仅作文档性声明；真正的导入交给调用方。
__all__ = ["__version__", "agent", "canvas", "mcp", "skills"]
