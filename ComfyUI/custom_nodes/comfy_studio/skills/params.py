"""skill 参数的合并与类型校验。

纪律：只做显式失败，不做静默兜底 —— 未知参数、缺必填、类型不符一律抛错，
避免把错误的参数值悄悄写进工作流后让引擎报一堆看不懂的节点错误。
"""

from __future__ import annotations

from typing import Any

from .types import NO_DEFAULT, Skill
from .types import SkillParam

# 名为 seed 的参数传 -1 表示每次随机（对齐 TS 版 SEED_RANDOM）。
SEED_RANDOM = -1


def _check_type(param: SkillParam, value: Any) -> Any:
    """按声明的 type 校验并原样返回。

    bool 是 int 的子类，所以 integer/number 必须显式排除 bool。
    """
    t = param.type
    where = f"参数 {param.name}"
    if t == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{where} 需要 boolean，收到 {type(value).__name__}: {value!r}")
        return value
    if t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where} 需要 integer，收到 {type(value).__name__}: {value!r}")
        return value
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where} 需要 number，收到 {type(value).__name__}: {value!r}")
        return float(value)
    if t == "string":
        if not isinstance(value, str):
            raise ValueError(f"{where} 需要 string，收到 {type(value).__name__}: {value!r}")
        return value
    raise ValueError(f"{where} 声明了未知类型 {t!r}")


def merge_params(skill: Skill, params: dict[str, Any] | None) -> dict[str, Any]:
    """把调用方传入的参数与 skill 声明的默认值合并，并完成校验。

    返回的 dict 只包含 skill 声明过的参数名。
    """
    given = dict(params or {})

    # 未知参数直接报错，别让拼错的名字被当成“没传”而走默认值。
    known = {p.name for p in skill.params}
    unknown = sorted(set(given) - known)
    if unknown:
        raise ValueError(
            f"skill {skill.id} 不认识这些参数: {', '.join(unknown)}；可用: {', '.join(sorted(known)) or '（无）'}"
        )

    merged: dict[str, Any] = {}
    missing: list[str] = []
    for param in skill.params:
        if param.name in given:
            value = _check_type(param, given[param.name])
        elif param.has_default:
            value = _check_type(param, param.default)
        elif param.required:
            missing.append(param.name)
            continue
        else:
            continue
        merged[param.name] = value

    if missing:
        raise ValueError(f"skill {skill.id} 缺少必填参数: {', '.join(missing)}")
    return merged


__all__ = ["SEED_RANDOM", "merge_params", "NO_DEFAULT"]
