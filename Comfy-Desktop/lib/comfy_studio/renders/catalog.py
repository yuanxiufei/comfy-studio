"""桌面侧的渲染目标目录。

与 :mod:`comfy_studio.skills.catalog` 同一套路：**目标定义（这台机器上那 12 张生产工作流 +
参数表）与组装/执行都在引擎侧**，这边只用 MCP 读进来、按 id 触发。

``comfy_list_renders`` / ``comfy_render`` 是引擎
``<ComfyUI>/custom_nodes/comfy_studio/mcp/tools.py`` 里定死的跨进程契约：引擎那边改名，这里
必须同步改。

与 skill 那层只有两处不同，都不是随意的：

1. 引擎回的清单是个**对象**（``workflows_dir`` / ``note`` / ``targets``），不是裸数组 ——
   "工作流目录在哪、哪张图缺了"必须如实带到面板，不能让人以为列出来的都能跑；
2. 参数解析**直接复用** :class:`comfy_studio.skills.SkillParam`：引擎两边用的是同一套键名
   （见引擎 ``skills/params.py::param_entry``），所以面板只认一套字段。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..mcp import ENGINE_SERVER_NAME, McpHub, error_message, resolve_tool, result_json, result_text
from ..skills import NO_DEFAULT, SkillParam, SkillsError

#: 引擎侧提供渲染目标清单的工具名。
LIST_RENDERS_TOOL = "comfy_list_renders"
#: 引擎侧执行渲染目标的工具名。
RENDER_TOOL = "comfy_render"


class RendersError(RuntimeError):
    """渲染目录层面的错误（引擎没这把工具、返回结构不对、要跑的目标不存在）。"""


@dataclass(frozen=True)
class RenderTarget:
    """面板里的一条渲染目标。

    ``file_exists`` 是引擎**照实报**的那个字段（缺图时 false）：面板据此把"这张还没配"画出来，
    而不是让人点下去才发现跑不起来。
    """

    id: str
    title: str
    description: str
    file: str
    tags: tuple[str, ...]
    params: tuple[SkillParam, ...]
    file_exists: bool
    reference_images: bool = False

    @staticmethod
    def from_engine(raw: Any, where: str) -> "RenderTarget":
        if not isinstance(raw, dict):
            raise RendersError(f"{where} 不是对象: {raw!r}")
        target_id = raw.get("id")
        title = raw.get("title")
        description = raw.get("description")
        file = raw.get("file")
        if not isinstance(target_id, str) or target_id == "":
            raise RendersError(f"{where}.id 缺失或不是非空字符串")
        if not isinstance(title, str):
            raise RendersError(f"{where}.title 必须是字符串")
        if not isinstance(description, str):
            raise RendersError(f"{where}.description 必须是字符串")
        if not isinstance(file, str) or file == "":
            raise RendersError(f"{where}.file 缺失或不是非空字符串")
        tags_raw = raw.get("tags") or []
        if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
            raise RendersError(f"{where}.tags 必须是字符串数组")
        params_raw = raw.get("params") or []
        if not isinstance(params_raw, list):
            raise RendersError(f"{where}.params 必须是数组")
        # 引擎没报 file_exists 就是契约变了：不默认成 True（那正是"假装能跑"）。
        file_exists = raw.get("file_exists")
        if not isinstance(file_exists, bool):
            raise RendersError(f"{where}.file_exists 缺失或不是布尔值")
        reference_images = raw.get("reference_images", False)
        if not isinstance(reference_images, bool):
            raise RendersError(f"{where}.reference_images 必须是布尔值")
        try:
            params = tuple(
                SkillParam.from_engine(p, f"{where}.params[{i}]") for i, p in enumerate(params_raw)
            )
        except SkillsError as err:  # 参数形状由 skills 那份解析器把关，错误并回这一族
            raise RendersError(str(err)) from err
        return RenderTarget(
            id=target_id,
            title=title,
            description=description,
            file=file,
            tags=tuple(tags_raw),
            params=params,
            file_exists=file_exists,
            reference_images=reference_images,
        )

    def param(self, name: str) -> SkillParam | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "file": self.file,
            "tags": list(self.tags),
            "params": [p.to_json() for p in self.params],
            "fileExists": self.file_exists,
            "referenceImages": self.reference_images,
        }


@dataclass(frozen=True)
class RenderRun:
    """一次渲染运行的结果。

    与 :class:`comfy_studio.skills.SkillRun` 分两类问题的方式一致：**协议层**的问题（目标不存在、
    工具不存在）直接抛 :class:`RendersError`；工具**执行**失败（显存不够、图缺了）落在
    ``is_error`` 上，面板照原样显示。

    ``notes`` 不在这里另开字段：它在引擎回的 ``data`` 里（组装期的让步 —— 时长按帧数折算、
    接了外部组），面板从 ``data`` 取。
    """

    target_id: str
    is_error: bool
    text: str
    data: Any = None

    def to_json(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "isError": self.is_error,
            "text": self.text,
            "data": self.data,
        }


class RenderCatalog:
    """把引擎报出来的渲染目标缓存在本地，供面板查/跑。"""

    def __init__(self, hub: McpHub, server: str = ENGINE_SERVER_NAME) -> None:
        self._hub = hub
        self._server = server
        self._targets: tuple[RenderTarget, ...] = ()
        self._workflows_dir: str | None = None
        self._note: str | None = None

    # ---- 目录 -----------------------------------------------------------

    @property
    def targets(self) -> tuple[RenderTarget, ...]:
        return self._targets

    @property
    def workflows_dir(self) -> str | None:
        """引擎报的工作流目录（还没 refresh 过就是 None）。"""
        return self._workflows_dir

    @property
    def note(self) -> str | None:
        """引擎如实报的那句话（目录不存在时才有），面板照原样显示。"""
        return self._note

    def get(self, target_id: str) -> RenderTarget:
        if not self._targets:
            raise RendersError("渲染目标还是空的：先调 refresh() 从引擎读一遍")
        for target in self._targets:
            if target.id == target_id:
                return target
        raise RendersError(
            f"没有渲染目标 {target_id}；可用: {', '.join(t.id for t in self._targets) or '（无）'}"
        )

    async def refresh(self) -> tuple[RenderTarget, ...]:
        """从引擎重新读一遍目标表。"""
        result = await self._hub.call_tool(self._tool(LIST_RENDERS_TOOL), {})
        payload = result_json(result, LIST_RENDERS_TOOL)
        if not isinstance(payload, dict):
            raise RendersError(
                f"{LIST_RENDERS_TOOL} 应返回对象（workflows_dir/note/targets），"
                f"实际是 {type(payload).__name__}"
            )
        directory = payload.get("workflows_dir")
        if not isinstance(directory, str) or directory == "":
            raise RendersError(f"{LIST_RENDERS_TOOL}.workflows_dir 缺失或不是非空字符串")
        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            raise RendersError(f"{LIST_RENDERS_TOOL}.note 必须是字符串或 null")
        targets_raw = payload.get("targets")
        if not isinstance(targets_raw, list):
            raise RendersError(f"{LIST_RENDERS_TOOL}.targets 必须是数组")
        targets = tuple(
            RenderTarget.from_engine(item, f"{LIST_RENDERS_TOOL}.targets[{i}]")
            for i, item in enumerate(targets_raw)
        )
        ids = [t.id for t in targets]
        if len(set(ids)) != len(ids):
            raise RendersError(f"{LIST_RENDERS_TOOL} 返回了重复的目标 id: {sorted(ids)}")
        self._targets = targets
        self._workflows_dir = directory
        self._note = note
        return targets

    # ---- 执行 -----------------------------------------------------------

    async def run(
        self,
        target_id: str,
        params: dict[str, Any] | None = None,
        *,
        images: Iterable[str | Path] = (),
        duration_sec: float | None = None,
        output_dir: str | Path | None = None,
    ) -> RenderRun:
        """跑一个渲染目标。

        ``images`` 是**这台机器上的文件路径**，按顺序对应提示词里的"图片1、图片2…"（只有视频
        目标收），引擎会先搬进它自己的 ``input/``。

        参数的**规则**校验（必填、时长要正数）由引擎负责 —— 组装期是唯一说了算的地方，
        这边不重复实现一份（见引擎 ``skills/render.py``）。
        """
        self.get(target_id)  # 先确认它存在，不存在就显式报错
        arguments: dict[str, Any] = {"target_id": target_id, "params": dict(params or {})}
        names = [str(path) for path in images]
        if names:
            arguments["images"] = names
        if duration_sec is not None:
            arguments["duration_sec"] = duration_sec
        if output_dir is not None:
            arguments["output_dir"] = str(output_dir)
        result = await self._hub.call_tool(self._tool(RENDER_TOOL), arguments)
        message = error_message(result)
        if message is not None:
            return RenderRun(target_id=target_id, is_error=True, text=message)
        text = result_text(result)
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError:
            data = None
        return RenderRun(target_id=target_id, is_error=False, text=text, data=data)

    # ---- 内部 -----------------------------------------------------------

    def _tool(self, tool: str) -> str:
        return resolve_tool(self._hub, self._server, tool, error=RendersError)


__all__ = [
    "LIST_RENDERS_TOOL",
    "RENDER_TOOL",
    "NO_DEFAULT",
    "RenderCatalog",
    "RenderRun",
    "RenderTarget",
    "RendersError",
]
