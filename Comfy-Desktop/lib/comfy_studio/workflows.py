"""桌面侧的工作流库：工作流目录里有哪些图，面板照着列。

与 :mod:`comfy_studio.renders.catalog` 是同一套路 —— **目录的真相与读写的规则都在引擎侧**
（``<ComfyUI>/custom_nodes/comfy_studio/skills/workflows.py``），这边只用 MCP 读进来。

为什么这边一条规则都不重写：越界（名字只能落在目录里那一个文件）、乐观锁（必须带读回来的
``digest``）、写前试转（转不成 API 格式就不落盘）这三条挡的是"文件被盖掉"和"图坏了"，而它们要
拿节点定义才判得了 —— 那东西只有引擎那侧有。在宿主再抄一份判断，两份迟早不一致，而不一致的那
一份会写坏用户的图。

``comfy_list_workflows`` 是引擎 ``mcp/tools.py`` 里定死的跨进程契约：引擎那边改名，这里必须同步改。

**写路径不在这儿**：改图/建图走对话窗口里模型手上的那几把 MCP 工具（``comfy_read_workflow`` /
``comfy_write_workflow``），宿主不额外开一条 RPC —— 多一条通道就多一处能绕过乐观锁的地方。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mcp import ENGINE_SERVER_NAME, McpHub, resolve_tool, result_json

#: 引擎侧列出工作流目录的工具名。
LIST_WORKFLOWS_TOOL = "comfy_list_workflows"


class WorkflowsError(RuntimeError):
    """工作流库层面的错误（引擎没这把工具、返回结构不对）。"""


@dataclass(frozen=True)
class WorkflowFile:
    """面板工作流列表里的一条。

    ``used_by`` 为空表示这张图**还没登记成渲染目标** —— 它照样能用 ``renders/run`` 的 ``file``
    跑（全按图上原值）。这个区分必须带到面板上：那批图正是用户自己存的、改了一半的。
    """

    file: str
    bytes: int
    modified: str
    digest: str
    used_by: tuple[str, ...]

    @staticmethod
    def from_engine(raw: Any, where: str) -> "WorkflowFile":
        if not isinstance(raw, dict):
            raise WorkflowsError(f"{where} 不是对象: {raw!r}")
        file = raw.get("file")
        size = raw.get("bytes")
        modified = raw.get("modified")
        digest = raw.get("digest")
        if not isinstance(file, str) or file == "":
            raise WorkflowsError(f"{where}.file 缺失或不是非空字符串")
        # bool 是 int 的子类：True 混进来当字节数会一路带到面板，得单独挡掉。
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise WorkflowsError(f"{where}.bytes 缺失或不是非负整数")
        if not isinstance(modified, str):
            raise WorkflowsError(f"{where}.modified 必须是字符串")
        if not isinstance(digest, str) or digest == "":
            raise WorkflowsError(f"{where}.digest 缺失或不是非空字符串")
        used_by_raw = raw.get("used_by") or []
        if not isinstance(used_by_raw, list) or any(not isinstance(item, str) for item in used_by_raw):
            raise WorkflowsError(f"{where}.used_by 必须是字符串数组")
        return WorkflowFile(
            file=file,
            bytes=size,
            modified=modified,
            digest=digest,
            used_by=tuple(used_by_raw),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "bytes": self.bytes,
            "modified": self.modified,
            "digest": self.digest,
            "usedBy": list(self.used_by),
        }


class WorkflowLibrary:
    """把引擎报出来的工作流清单缓存在本地，供面板列。"""

    def __init__(self, hub: McpHub, server: str = ENGINE_SERVER_NAME) -> None:
        self._hub = hub
        self._server = server
        self._files: tuple[WorkflowFile, ...] = ()
        self._workflows_dir: str | None = None
        self._note: str | None = None

    @property
    def files(self) -> tuple[WorkflowFile, ...]:
        return self._files

    @property
    def workflows_dir(self) -> str | None:
        """引擎报的工作流目录（还没 refresh 过就是 None）。"""
        return self._workflows_dir

    @property
    def note(self) -> str | None:
        """引擎如实报的那句话（目录不存在时才有），面板照原样显示。"""
        return self._note

    def get(self, file: str) -> WorkflowFile:
        if not self._files:
            raise WorkflowsError("工作流清单还是空的：先调 refresh() 从引擎读一遍")
        for item in self._files:
            if item.file == file:
                return item
        raise WorkflowsError(
            f"没有工作流 {file}；可用: {', '.join(item.file for item in self._files) or '（无）'}"
        )

    async def refresh(self) -> tuple[WorkflowFile, ...]:
        """从引擎重新读一遍清单。

        与 :meth:`RenderCatalog.refresh` 的差别只在 payload 的形状（``files`` 而不是 ``targets``）：
        引擎报什么这儿就记什么，一句都不改口径 —— 那句 ``note`` 是面板用来解释"目录不在这台机器上"
        的唯一依据。
        """
        result = await self._hub.call_tool(self._tool(LIST_WORKFLOWS_TOOL), {})
        payload = result_json(result, LIST_WORKFLOWS_TOOL)
        if not isinstance(payload, dict):
            raise WorkflowsError(
                f"{LIST_WORKFLOWS_TOOL} 应返回对象（workflows_dir/note/workflows），"
                f"实际是 {type(payload).__name__}"
            )
        directory = payload.get("workflows_dir")
        if not isinstance(directory, str) or directory == "":
            raise WorkflowsError(f"{LIST_WORKFLOWS_TOOL}.workflows_dir 缺失或不是非空字符串")
        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            raise WorkflowsError(f"{LIST_WORKFLOWS_TOOL}.note 必须是字符串或 null")
        files_raw = payload.get("workflows")
        if not isinstance(files_raw, list):
            raise WorkflowsError(f"{LIST_WORKFLOWS_TOOL}.workflows 必须是数组")
        files = tuple(
            WorkflowFile.from_engine(item, f"{LIST_WORKFLOWS_TOOL}.workflows[{i}]")
            for i, item in enumerate(files_raw)
        )
        self._files = files
        self._workflows_dir = directory
        self._note = note
        return files

    # ---- 内部 -----------------------------------------------------------

    def _tool(self, tool: str) -> str:
        return resolve_tool(self._hub, self._server, tool, error=WorkflowsError)


__all__ = [
    "LIST_WORKFLOWS_TOOL",
    "WorkflowFile",
    "WorkflowLibrary",
    "WorkflowsError",
]
