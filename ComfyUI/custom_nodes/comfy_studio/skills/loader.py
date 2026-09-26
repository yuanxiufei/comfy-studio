"""skill 文件的加载与严格校验。

加载规则（对齐 TS 版 ``packages/comfy-skills/src/loader.ts``）：
目录下所有 ``*.json`` 按文件名排序逐个加载；任何一个文件不合法就直接抛错，
不做静默跳过 —— 少加载一个 skill 而无人察觉比直接报错更糟。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import NO_DEFAULT
from .types import PARAM_TYPES
from .types import PromptWorkflow
from .types import Skill
from .types import SkillParam


def _require_nonempty_str(raw: dict[str, Any], key: str, source: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{source}: {key} 必须是非空字符串")
    return value


def _validate_workflow(raw: Any, source: str) -> PromptWorkflow:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: workflow 必须是节点映射（ComfyUI API 格式）")
    if not raw:
        raise ValueError(f"{source}: workflow 不能为空")
    for node_id, node in raw.items():
        if not isinstance(node, dict):
            raise ValueError(f"{source}: workflow 节点 {node_id} 必须是对象")
        if not isinstance(node.get("class_type"), str):
            raise ValueError(f"{source}: workflow 节点 {node_id} 缺少 class_type")
        if not isinstance(node.get("inputs"), dict):
            raise ValueError(f"{source}: workflow 节点 {node_id} 缺少 inputs")
    return raw  # type: ignore[return-value]


def _validate_params(raw: Any, workflow: PromptWorkflow, source: str) -> tuple[SkillParam, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{source}: params 必须是数组")

    params: list[SkillParam] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{source}: params 里的每一项都必须是对象")
        name = item.get("name")
        if not isinstance(name, str) or name == "":
            raise ValueError(f"{source}: 每个参数必须有非空 name")
        if name in seen:
            raise ValueError(f"{source}: 参数 {name} 重复定义")
        seen.add(name)

        ptype = item.get("type")
        if ptype not in PARAM_TYPES:
            raise ValueError(f"{source}: 参数 {name} 的 type 必须是 {'/'.join(sorted(PARAM_TYPES))}")

        node = item.get("node")
        if not isinstance(node, str) or node not in workflow:
            raise ValueError(
                f"{source}: 参数 {name} 引用的节点 {node!r} 不在 workflow 里"
                f"（可用节点: {', '.join(map(str, workflow))}）"
            )

        field = item.get("field")
        if not isinstance(field, str) or field == "":
            raise ValueError(f"{source}: 参数 {name} 缺少 field")
        inputs = workflow[node]["inputs"]
        if field not in inputs:
            raise ValueError(
                f"{source}: 参数 {name} 的字段 {field} 不是节点 {node} 的输入"
                f"（可用: {', '.join(map(str, inputs))}）"
            )

        params.append(
            SkillParam(
                name=name,
                type=ptype,  # type: ignore[arg-type]
                node=node,
                field=field,
                description=item.get("description"),
                required=bool(item.get("required", False)),
                default=item["default"] if "default" in item else NO_DEFAULT,
            )
        )
    return tuple(params)


def validate_skill(raw: Any, source: str) -> Skill:
    """把一份已解析的 JSON 变成 Skill；任何不合规都抛 ValueError。"""
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: skill 必须是 JSON 对象")

    skill_id = _require_nonempty_str(raw, "id", source)
    title = _require_nonempty_str(raw, "title", source)
    description = _require_nonempty_str(raw, "description", source)
    workflow = _validate_workflow(raw.get("workflow"), source)
    params = _validate_params(raw.get("params"), workflow, source)

    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
        raise ValueError(f"{source}: tags 必须是字符串数组")

    return Skill(
        id=skill_id,
        title=title,
        description=description,
        workflow=workflow,
        params=params,
        tags=tuple(tags_raw),
        source=source,
    )


def skill_to_json(skill: Skill) -> dict[str, Any]:
    """把 Skill 还原成 skill 文件的内容（:func:`validate_skill` 的逆）。

    写盘与回显都走这里：这样"存进去的文件"和"读出来的内存对象"是同一套字段，
    不会出现存进去能读、读出来再存字段却丢了的情况（``default: null`` 与"没声明
    default"的区分也靠它保住）。
    """
    params: list[dict[str, Any]] = []
    for p in skill.params:
        item: dict[str, Any] = {
            "name": p.name,
            "type": p.type,
            "node": p.node,
            "field": p.field,
            "required": p.required,
        }
        if p.description is not None:
            item["description"] = p.description
        if p.has_default:
            item["default"] = p.default
        params.append(item)
    return {
        "id": skill.id,
        "title": skill.title,
        "description": skill.description,
        "tags": list(skill.tags),
        "workflow": skill.workflow,
        "params": params,
    }


def load_skill_file(path: str | Path) -> Skill:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"skill 文件 {p} 不是合法 JSON: {err}") from err
    return validate_skill(raw, str(p))


def load_skills(directory: str | Path) -> tuple[Skill, ...]:
    """加载目录下全部 skill，按文件名排序。目录为空直接报错。"""
    d = Path(directory)
    if not d.is_dir():
        raise NotADirectoryError(f"skill 目录不存在: {d}")
    files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".json")
    if not files:
        raise ValueError(f"skill 目录 {d} 里没有任何 .json 文件")
    return tuple(load_skill_file(f) for f in files)


__all__ = ["load_skill_file", "load_skills", "skill_to_json", "validate_skill"]
