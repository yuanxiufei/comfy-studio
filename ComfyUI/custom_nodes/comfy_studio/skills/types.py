"""skill 的数据模型。

skill = 一份 ComfyUI API 格式工作流 + 一张参数表。运行期把参数值写进
``workflow[node_id]["inputs"][field]``，再提交给引擎队列执行。

字段与校验规则对齐本仓最初的 TypeScript 实现
（``packages/comfy-skills/src/types.ts``），这里是它在引擎侧（Python）的对应物。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# 与 TS 版 SkillParamType 一一对应；也是 JSON 里 type 字段的合法取值。
SkillParamType = Literal["string", "integer", "number", "boolean"]

PARAM_TYPES: frozenset[str] = frozenset({"string", "integer", "number", "boolean"})

# ComfyUI API 格式工作流：{节点 id: {"class_type": str, "inputs": {...}}}
PromptWorkflow = dict[str, dict[str, Any]]


class _NoDefault:
    """参数未声明 default 的哨兵。

    不能用 None 表示“没有默认值”，否则无法区分 ``"default": null``。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅用于报错信息
        return "<无默认值>"


NO_DEFAULT = _NoDefault()


@dataclass(frozen=True)
class SkillParam:
    """skill 的一个参数，描述它注入到哪个节点的哪个输入。"""

    name: str
    type: SkillParamType
    node: str
    field: str
    description: str | None = None
    required: bool = False
    default: Any = NO_DEFAULT

    @property
    def has_default(self) -> bool:
        return self.default is not NO_DEFAULT

    def hint(self) -> str:
        """给报错与工具 schema 用的一句话说明。"""
        return self.description or f"注入到节点 {self.node} 的 {self.field}"


@dataclass(frozen=True)
class Skill:
    """一个可运行的 skill。"""

    id: str
    title: str
    description: str
    workflow: PromptWorkflow
    params: tuple[SkillParam, ...]
    tags: tuple[str, ...] = ()
    source: str = "<内存>"

    def param(self, name: str) -> SkillParam | None:
        for p in self.params:
            if p.name == name:
                return p
        return None


@dataclass(frozen=True)
class SkillOutputMedia:
    """一次运行产出的单个文件（图 / 视频 / 音频）。

    ``kind`` 只能按扩展名判，不能按键名：``SaveVideo`` 的视频同样挂在 history 的
    ``images`` 键下（出处见 ``skills/outputs.py`` 顶部）。判据是 ``outputs.guess_kind``。
    """

    node: str
    filename: str
    subfolder: str
    type: str
    kind: str

    def url(self, base_url: str) -> str:
        """拼出可直接 GET 的 /view 地址（与 server.py 的 view_image 参数一致）。"""
        from urllib.parse import urlencode

        query = urlencode({"filename": self.filename, "subfolder": self.subfolder, "type": self.type})
        return f"{base_url.rstrip('/')}/view?{query}"

    def to_json(self, base_url: str) -> dict[str, Any]:
        return {
            "node": self.node,
            "filename": self.filename,
            "subfolder": self.subfolder,
            "type": self.type,
            "kind": self.kind,
            "url": self.url(base_url),
        }


@dataclass(frozen=True)
class SkillRunResult:
    """run_skill 的返回值。"""

    prompt_id: str
    media: tuple[SkillOutputMedia, ...]
    outputs: dict[str, Any]

    @property
    def images(self) -> tuple[SkillOutputMedia, ...]:
        return tuple(item for item in self.media if item.kind == "image")

    @property
    def videos(self) -> tuple[SkillOutputMedia, ...]:
        return tuple(item for item in self.media if item.kind == "video")

    @property
    def audios(self) -> tuple[SkillOutputMedia, ...]:
        return tuple(item for item in self.media if item.kind == "audio")

    def to_json(self, base_url: str) -> dict[str, Any]:
        # images 保持原样（面板与 MCP 工具已在用），videos / audios 是这次补上的。
        return {
            "prompt_id": self.prompt_id,
            "images": [item.to_json(base_url) for item in self.images],
            "videos": [item.to_json(base_url) for item in self.videos],
            "audios": [item.to_json(base_url) for item in self.audios],
        }
