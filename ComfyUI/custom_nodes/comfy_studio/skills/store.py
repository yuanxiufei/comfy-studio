"""skill 的落盘与目录拼装：内置目录（只读）+ 用户目录（可写）。

**为什么要分开两个目录**：随包自带的 ``workflows/`` 是源码的一部分（本仓由
``studio/overlay`` 装配，上游升级会整份替换），往里写用户产出的东西既会被装配当成
"被就地改过的文件"，升级时也会丢。所以用户存下来的 skill 一律落到**用户目录**：

1. 环境变量 ``COMFY_USER_SKILLS_DIR``（测试、多份配置时用）；
2. 否则用户家目录下的 ``~/.comfy-studio/skills``。

内置那份仍然是"必须有"的（随包自带，缺了说明装坏了）；用户那份允许不存在、允许为空
——还没存过任何 skill 是正常状态，不是错误。

写入用"临时文件 + 原子替换"：:func:`~comfy_studio.skills.loader.load_skills` 是严格派，
**一个坏文件就让整个目录加载失败**，所以目标路径上绝不能出现半截 JSON。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from .loader import load_skill_file, load_skills, skill_to_json
from .types import Skill

#: 覆盖用户 skill 目录。
USER_SKILLS_DIR_ENV = "COMFY_USER_SKILLS_DIR"

#: 用户 skill 的默认落点（家目录下的一个固定位置，不是机器专有路径）。
DEFAULT_USER_SKILLS_DIR = Path.home() / ".comfy-studio" / "skills"

#: skill id 会成为文件名，所以只允许能安全当文件名的字符（不支持大写：Windows 上
#: 大小写不敏感的卷会把 ``Foo.json`` 和 ``foo.json`` 认成同一个文件）。
SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def user_skills_dir() -> Path:
    """用户 skill 目录：环境变量优先，否则家目录下的默认落点。"""
    override = os.environ.get(USER_SKILLS_DIR_ENV)
    return Path(override).expanduser() if override else DEFAULT_USER_SKILLS_DIR


def check_skill_id(skill_id: str) -> str:
    """id 要能当文件名用；不合适就明确报错，别拼出一个跑到目录外去的路径。"""
    if not SKILL_ID_PATTERN.match(skill_id):
        raise ValueError(
            f"skill id {skill_id!r} 不能当文件名（只允许小写字母、数字、- 与 _，且以字母或数字开头）"
        )
    return skill_id


def load_user_skills(directory: str | Path) -> tuple[Skill, ...]:
    """加载用户目录里的 skill；目录不存在或空着都返回空元组（还没存过而已）。"""
    d = Path(directory)
    if not d.is_dir():
        return ()
    files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".json")
    return tuple(load_skill_file(f) for f in files)


def merge_unique_skills(*groups: Iterable[Skill]) -> tuple[Skill, ...]:
    """把几组 skill 按给定顺序拼起来，id 撞车直接报错并指出两份来源。

    这层查重 :func:`load_all_skills` 与
    :class:`~comfy_studio.skills.registry.SkillRegistry` 都要用，所以只写一遍：
    skill 是能被 agent 直接调用的名字，静默让一份盖掉另一份会让人分不清跑的是哪一份。
    """
    seen: dict[str, Skill] = {}
    for group in groups:
        for skill in group:
            other = seen.get(skill.id)
            if other is not None:
                raise ValueError(
                    f"skill id 冲突: {skill.id} 同时来自 {other.source} 与 {skill.source}；请改掉其中一个"
                )
            seen[skill.id] = skill
    return tuple(seen.values())


def load_all_skills(
    builtin_dir: str | Path | None = None,
    user_dir: str | Path | None = None,
) -> tuple[Skill, ...]:
    """内置 + 用户的全部 skill（内置在前，各自按文件名排序）。

    ``None`` 表示这个来源不参与。
    """
    builtin = load_skills(builtin_dir) if builtin_dir is not None else ()
    user = load_user_skills(user_dir) if user_dir is not None else ()
    return merge_unique_skills(builtin, user)


def write_skill(skill: Skill, directory: str | Path) -> Path:
    """把 skill 写成 ``<directory>/<id>.json`` 并返回落点。"""
    check_skill_id(skill.id)
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{skill.id}.json"
    body = json.dumps(skill_to_json(skill), ensure_ascii=False, indent=2) + "\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, target)  # 原子替换：目标路径上不会出现半截文件
    return target


__all__ = [
    "DEFAULT_USER_SKILLS_DIR",
    "SKILL_ID_PATTERN",
    "USER_SKILLS_DIR_ENV",
    "check_skill_id",
    "load_all_skills",
    "load_user_skills",
    "merge_unique_skills",
    "user_skills_dir",
    "write_skill",
]
