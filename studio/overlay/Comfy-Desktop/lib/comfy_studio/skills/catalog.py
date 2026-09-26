"""桌面侧的 skill 目录。

前端**不自己跑工作流**：skill 的权威定义（workflow + 参数表）与执行都在引擎侧。
这边只做两件事——

1. 用 MCP 把引擎的 ``comfy_list_skills`` 读进来，变成面板能直接渲染的目录；
2. 按 id 调 ``comfy_run_skill`` 去跑，把结果（含图片 url）原样交回。

``comfy_list_skills`` / ``comfy_run_skill`` 这两个工具名是引擎
``<ComfyUI>/custom_nodes/comfy_studio/mcp/tools.py`` 里定死的，属于跨进程契约：
引擎那边改名，这里必须同步改。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..mcp import ENGINE_SERVER_NAME, McpHub, error_message, result_json, result_text

#: 引擎侧提供 skill 目录的工具名。
LIST_SKILLS_TOOL = "comfy_list_skills"
#: 引擎侧执行 skill 的工具名。
RUN_SKILL_TOOL = "comfy_run_skill"


class SkillsError(RuntimeError):
    """skill 目录层面的错误（引擎没这个工具、返回结构不对、要跑的 skill 不存在）。"""


class _NoDefault:
    """参数未声明默认值的哨兵——``None`` 无法区分「没有默认值」与「默认值是 null」。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅出现在报错文本里
        return "<无默认值>"


NO_DEFAULT = _NoDefault()


@dataclass(frozen=True)
class SkillParam:
    """引擎报回来的一个 skill 参数。"""

    name: str
    type: str
    required: bool
    description: str
    default: Any = NO_DEFAULT

    @property
    def has_default(self) -> bool:
        return self.default is not NO_DEFAULT

    @staticmethod
    def from_engine(raw: Any, where: str) -> "SkillParam":
        if not isinstance(raw, dict):
            raise SkillsError(f"{where} 不是对象: {raw!r}")
        name = raw.get("name")
        type_ = raw.get("type")
        if not isinstance(name, str) or name == "":
            raise SkillsError(f"{where}.name 缺失或不是非空字符串")
        if not isinstance(type_, str) or type_ == "":
            raise SkillsError(f"{where}.type 缺失或不是非空字符串")
        required = raw.get("required", False)
        if not isinstance(required, bool):
            raise SkillsError(f"{where}.required 必须是布尔值")
        description = raw.get("description") or ""
        if not isinstance(description, str):
            raise SkillsError(f"{where}.description 必须是字符串")
        # 引擎明确用 null 表示「没有默认值」（skills 侧 SkillParam.has_default 为假）。
        default: Any = raw["default"] if raw.get("default") is not None else NO_DEFAULT
        return SkillParam(
            name=name, type=type_, required=required, description=description, default=default
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "default": self.default if self.has_default else None,
            "hasDefault": self.has_default,
        }


@dataclass(frozen=True)
class SkillEntry:
    """面板里的一条 skill。"""

    id: str
    title: str
    description: str
    tags: tuple[str, ...]
    params: tuple[SkillParam, ...]

    @staticmethod
    def from_engine(raw: Any, where: str) -> "SkillEntry":
        if not isinstance(raw, dict):
            raise SkillsError(f"{where} 不是对象: {raw!r}")
        skill_id = raw.get("id")
        title = raw.get("title")
        description = raw.get("description")
        if not isinstance(skill_id, str) or skill_id == "":
            raise SkillsError(f"{where}.id 缺失或不是非空字符串")
        if not isinstance(title, str):
            raise SkillsError(f"{where}.title 必须是字符串")
        if not isinstance(description, str):
            raise SkillsError(f"{where}.description 必须是字符串")
        tags_raw = raw.get("tags") or []
        if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
            raise SkillsError(f"{where}.tags 必须是字符串数组")
        params_raw = raw.get("params") or []
        if not isinstance(params_raw, list):
            raise SkillsError(f"{where}.params 必须是数组")
        return SkillEntry(
            id=skill_id,
            title=title,
            description=description,
            tags=tuple(tags_raw),
            params=tuple(
                SkillParam.from_engine(p, f"{where}.params[{i}]") for i, p in enumerate(params_raw)
            ),
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
            "tags": list(self.tags),
            "params": [p.to_json() for p in self.params],
        }


@dataclass(frozen=True)
class SkillRun:
    """一次 skill 运行的结果。

    分两类：**协议层**的问题（skill 不存在、工具不存在）直接抛 :class:`SkillsError`；
    工具**执行**失败（显存不够、模型名写错）落在这里的 ``is_error`` 上，面板照原样显示。
    """

    skill_id: str
    is_error: bool
    text: str
    data: Any = None

    def to_json(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "isError": self.is_error, "text": self.text, "data": self.data}


class SkillCatalog:
    """把引擎报出来的 skill 目录缓存在本地，供面板/agent 查。"""

    def __init__(self, hub: McpHub, server: str = ENGINE_SERVER_NAME) -> None:
        self._hub = hub
        self._server = server
        self._entries: tuple[SkillEntry, ...] = ()

    # ---- 目录 -----------------------------------------------------------

    @property
    def entries(self) -> tuple[SkillEntry, ...]:
        return self._entries

    def get(self, skill_id: str) -> SkillEntry:
        if not self._entries:
            raise SkillsError("skill 目录还是空的：先调 refresh() 从引擎读一遍")
        for entry in self._entries:
            if entry.id == skill_id:
                return entry
        raise SkillsError(
            f"没有 skill {skill_id}；可用: {', '.join(e.id for e in self._entries) or '（无）'}"
        )

    async def refresh(self) -> tuple[SkillEntry, ...]:
        """从引擎重新读一遍目录。"""
        result = await self._hub.call_tool(self._tool(LIST_SKILLS_TOOL), {})
        payload = result_json(result, LIST_SKILLS_TOOL)
        if not isinstance(payload, list):
            raise SkillsError(f"{LIST_SKILLS_TOOL} 应返回数组，实际是 {type(payload).__name__}")
        entries = tuple(
            SkillEntry.from_engine(item, f"{LIST_SKILLS_TOOL}[{i}]") for i, item in enumerate(payload)
        )
        ids = [e.id for e in entries]
        if len(set(ids)) != len(ids):
            raise SkillsError(f"{LIST_SKILLS_TOOL} 返回了重复的 skill id: {sorted(ids)}")
        self._entries = entries
        return entries

    # ---- 执行 -----------------------------------------------------------

    async def run(self, skill_id: str, params: dict[str, Any] | None = None) -> SkillRun:
        """跑一个 skill。参数校验由引擎负责（``skills/params.py``），这边不重复实现。"""
        self.get(skill_id)  # 先确认它存在，不存在就显式报错
        arguments = {"skill_id": skill_id, "params": dict(params or {})}
        result = await self._hub.call_tool(self._tool(RUN_SKILL_TOOL), arguments)
        message = error_message(result)
        if message is not None:
            return SkillRun(skill_id=skill_id, is_error=True, text=message)
        text = result_text(result)
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError:
            data = None
        return SkillRun(skill_id=skill_id, is_error=False, text=text, data=data)

    # ---- 内部 -----------------------------------------------------------

    def _tool(self, tool: str) -> str:
        name = f"{self._server}__{tool}"
        available = {t.qualified_name for t in self._hub.tools}
        if name not in available:
            listed = ", ".join(sorted(available)) or "（无）"
            if not available:
                raise SkillsError("手上一个 MCP 工具都没有：MCP server 还没 start()？")
            raise SkillsError(f"MCP server {self._server} 没有工具 {tool}；可用: {listed}")
        return name


__all__ = [
    "LIST_SKILLS_TOOL",
    "NO_DEFAULT",
    "RUN_SKILL_TOOL",
    "SkillCatalog",
    "SkillEntry",
    "SkillParam",
    "SkillRun",
    "SkillsError",
]
